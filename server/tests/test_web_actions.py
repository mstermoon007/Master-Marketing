"""P5 Web 业务 action：确认登录、工作台口径复用、审计过滤、Excel 导出。"""
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.handlers import BusinessError, web
from app.services import export

TICKET = "fedcba9876543210fedcba9876543210"


@pytest.fixture(autouse=True)
def _ticket_time(monkeypatch):
    monkeypatch.setattr(web.db, "now_iso", lambda: "2026-11-16T00:00:00.000Z")


def _ticket_row(**overrides):
    row = {
        "id": "t1", "ticket": TICKET, "user_id": None, "status": "pending",
        "workspace_ids": None, "expires_at": "2026-11-16T00:05:00.000Z",
    }
    row.update(overrides)
    return row


def _patch_confirm_db(monkeypatch, row, owner_spaces, legacy=None, id_spaces=None):
    updates = []

    def fake_query(conn, sql, args=None):
        if "FROM `teams`" in sql:
            return legacy or []
        if "WHERE id IN" in sql:
            return id_spaces or []
        return owner_spaces

    monkeypatch.setattr(web.db, "one", lambda *a, **k: row)
    monkeypatch.setattr(web.db, "query", fake_query)
    monkeypatch.setattr(
        web.db, "update", lambda conn, table, rid, data: updates.append(data),
    )
    monkeypatch.setattr(web, "audit", lambda *a, **k: None)
    return updates


# ---------------------------------------------------------------- confirmWebLogin

def test_confirm_login_marks_ticket_and_returns_spaces(monkeypatch):
    spaces = [
        {"id": "W1", "workspace_code": "W1", "name": "一号空间"},
        {"id": "W2", "workspace_code": "W2", "name": "二号空间"},
    ]
    updates = _patch_confirm_db(monkeypatch, _ticket_row(), spaces)

    result = web.confirm_web_login(None, "openid-owner", {"ticket": TICKET})
    assert [w["id"] for w in result["workspaces"]] == ["W1", "W2"]
    assert updates[-1]["status"] == "confirmed"
    assert updates[-1]["user_id"] == "openid-owner"
    assert updates[-1]["workspace_ids"] == ["W1", "W2"]


def test_confirm_login_falls_back_to_legacy_team_owner(monkeypatch):
    spaces = [{"id": "W9", "workspace_code": "W9", "name": "老数据空间"}]
    legacy = [{"workspace_id": "W9"}]
    _patch_confirm_db(monkeypatch, _ticket_row(), [], legacy, id_spaces=spaces)
    result = web.confirm_web_login(None, "openid-owner", {"ticket": TICKET})
    assert result["workspaces"][0]["id"] == "W9"


def test_confirm_login_rejects_non_owner(monkeypatch):
    _patch_confirm_db(monkeypatch, _ticket_row(), [], [])
    with pytest.raises(BusinessError, match="所有者"):
        web.confirm_web_login(None, "openid-member", {"ticket": TICKET})


@pytest.mark.parametrize("row_kwargs, message", [
    ({"status": "consumed"}, "已使用"),
    ({"expires_at": "2026-11-15T00:00:00.000Z"}, "已过期"),
])
def test_confirm_login_rejects_unusable_ticket(monkeypatch, row_kwargs, message):
    _patch_confirm_db(monkeypatch, _ticket_row(**row_kwargs), [])
    with pytest.raises(BusinessError, match=message):
        web.confirm_web_login(None, "openid-owner", {"ticket": TICKET})


def test_confirm_login_rejects_bad_ticket_format(monkeypatch):
    monkeypatch.setattr(web.db, "one", lambda *a, **k: pytest.fail("不应查库"))
    with pytest.raises(BusinessError, match="二维码无效"):
        web.confirm_web_login(None, "openid-owner", {"ticket": "bad"})


# ---------------------------------------------------------------- 工作台

def test_overview_reuses_dataset_and_metrics(monkeypatch):
    monkeypatch.setattr(web.expected, "local_today", lambda: "2026-11-16")
    workspace = {"id": "W1", "workspace_code": "W1", "name": "一号空间"}
    monkeypatch.setattr(web, "require_workspace_role", lambda conn, uid, ws_id: (
        workspace, {"role": "owner", "status": "active"}
    ))
    monkeypatch.setattr(web.org, "teams_in_workspace", lambda conn, ws_id: [
        {"team_id": "T1", "name": "销售", "department_id": "D1"},
        {"team_id": "T2", "name": "运营", "department_id": None},
    ])
    calls = []

    def fake_load(conn, team_id, from_day, to_day):
        calls.append((team_id, from_day, to_day))
        return {"team_id": team_id, "entries": []}

    def fake_compute(data):
        base = 10 if data["team_id"] == "T1" else 5
        days = []
        for offset, day in enumerate(("2026-11-10", "2026-11-11", "2026-11-12",
                                      "2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16")):
            expected = base
            submitted = base - 1 if day == "2026-11-16" else base
            days.append({"date": day, "expectedCount": expected,
                         "submittedCount": submitted, "rate": submitted / expected,
                         "rateText": "%.1f%%" % (submitted / expected * 100)})
        return {"daily": days}

    monkeypatch.setattr(web.dataset, "load_dataset", fake_load)
    monkeypatch.setattr(web.metrics, "compute", fake_compute)
    monkeypatch.setattr(web.db, "one", lambda *a, **k: {"c": 3})

    result = web.get_workspace_overview(None, "openid-owner", {"workspaceId": "W1"})

    assert len(calls) == 2
    assert calls[0][0] == "T1"
    assert calls[0][1] == "2026-11-10" and calls[0][2] == "2026-11-16"
    assert result["todayExpected"] == 15
    assert result["todaySubmitted"] == 13
    assert result["missingCount"] == 2
    assert result["activeTaskCount"] == 3
    assert result["anomalyCount"] == 3
    assert len(result["trend"]) == 7
    assert result["trend"][-1]["expectedCount"] == 15
    assert result["teams"][0]["team_id"] == "T1"


def test_overview_requires_workspace_manager(monkeypatch):
    def deny(conn, uid, ws_id):
        raise BusinessError("需要工作空间管理员权限")

    monkeypatch.setattr(web, "require_workspace_role", deny)
    with pytest.raises(BusinessError):
        web.get_workspace_overview(None, "openid-member", {"workspaceId": "W1"})


# ---------------------------------------------------------------- 审计

def test_audit_forces_workspace_and_parameterizes(monkeypatch):
    monkeypatch.setattr(web, "require_workspace_role", lambda conn, uid, ws_id: (
        {"id": "W1"}, {"role": "owner"}
    ))
    monkeypatch.setattr(web.db, "one", lambda *a, **k: {"c": 42})
    captured = {}

    def fake_query(conn, sql, args=None):
        captured["sql"] = sql
        captured["args"] = args
        return [{"id": "a1", "workspace_id": "W1", "actor": "u1",
                 "action": "template_publish", "created_at": "2026-11-16T00:00:00.000Z"}]

    monkeypatch.setattr(web.db, "query", fake_query)

    evil = "x' OR 1=1 --"
    result = web.list_audit_logs(None, "openid-owner", {
        "workspaceId": "W1", "from": "2026-11-10", "to": "2026-11-16",
        "actor": evil, "action": "template_publish", "page": 2, "pageSize": 20,
    })

    assert "workspace_id = %s" in captured["sql"]
    assert "actor = %s" in captured["sql"]
    assert "LIMIT %s OFFSET %s" in captured["sql"]
    assert evil not in captured["sql"]
    assert captured["args"][0] == "W1"
    assert evil in captured["args"]
    assert captured["args"][-2:] == (20, 40)
    assert result["total"] == 42
    assert result["items"][0]["id"] == "a1"


# ---------------------------------------------------------------- 导出

def _patch_export_db(monkeypatch, entries, templates=None, members=None):
    monkeypatch.setattr(
        export, "require_manager",
        lambda conn, uid, team_id: {"team_id": team_id, "workspace_id": "W1"},
    )

    def fake_query(conn, sql, args=None):
        if "FROM `form_templates`" in sql:
            return templates or [{
                "id": "tpl1", "team_id": "T1", "template_id": "daily", "version": 2,
                "status": "published",
                "fields": [
                    {"fieldKey": "amount", "label": "金额", "unit": "元"},
                    {"fieldKey": "note", "label": "备注"},
                ],
            }]
        if "FROM `members`" in sql:
            return members or [{"user_id": "u1", "name": "张三"}]
        if "FROM `daily_entries`" in sql:
            return entries
        return []

    monkeypatch.setattr(export.db, "query", fake_query)
    monkeypatch.setattr(export.db, "one", lambda *a, **k: {"c": len(entries)})


def test_export_headers_and_rows(monkeypatch):
    entries = [{
        "id": "e1", "entry_date": "2026-11-15", "user_id": "u1", "status": "submitted",
        "form_data": [{"rowId": "r1", "values": {"amount": 12, "note": "完成"}}],
    }]
    _patch_export_db(monkeypatch, entries)

    stream, filename = export.build_entries_export(
        None, "openid-owner",
        {"teamId": "T1", "startDate": "2026-11-10", "endDate": "2026-11-16"},
    )
    assert filename == "entries_T1_2026-11-10_2026-11-16.xlsx"

    workbook = load_workbook(BytesIO(b"".join(stream)), read_only=True)
    rows = list(workbook["日报数据"].iter_rows(values_only=True))
    assert rows[0] == ("日期", "成员", "提交状态", "金额（元）", "备注")
    assert rows[1] == ("2026-11-15", "张三", "已提交", 12, "完成")


def test_export_rejects_oversized_result(monkeypatch):
    entries = [{
        "id": "e1", "entry_date": "2026-11-15", "user_id": "u1", "status": "submitted",
        "form_data": [{"values": {}}],
    }] * 2
    _patch_export_db(monkeypatch, entries)
    monkeypatch.setattr(export, "_MAX_ROWS", 1)

    with pytest.raises(BusinessError, match="缩小日期范围"):
        export.build_entries_export(
            None, "openid-owner",
            {"teamId": "T1", "startDate": "2026-11-10", "endDate": "2026-11-16"},
        )


def test_export_requires_manager(monkeypatch):
    def deny(conn, uid, team_id):
        raise BusinessError("需要管理员权限")

    monkeypatch.setattr(export, "require_manager", deny)
    with pytest.raises(BusinessError):
        export.build_entries_export(
            None, "openid-member",
            {"teamId": "T1", "startDate": "2026-11-10", "endDate": "2026-11-16"},
        )
