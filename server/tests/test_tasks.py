"""P2 填报任务：应提交口径、任务 CRUD、任务状态机。

全部通过 monkeypatch 隔离数据库，可在无 MySQL 环境下执行：
    cd server && python3 -m pytest -q
"""
import pytest

from app.handlers import BusinessError
from app.handlers import tasks as tk
from app.services import expected

MEMBERS = [
    {"id": "m1", "user_id": "u1", "name": "张三", "role": "member",
     "status": "active", "joined_at": "2026-01-01T00:00:00.000Z"},
    {"id": "m2", "user_id": "u2", "name": "李四", "role": "manager",
     "status": "active", "joined_at": "2026-01-02T00:00:00.000Z"},
]

TEMPLATES = [
    {"id": "t1", "team_id": "T1", "template_id": "tpl_1", "version": 1,
     "name": "成员日报", "status": "published", "effective_from": "2026-11-01",
     "scope": {"type": "members", "memberIds": ["u1"]}},
    {"id": "t2", "team_id": "T1", "template_id": "tpl_2", "version": 1,
     "name": "管理日报", "status": "published", "effective_from": "2026-11-01",
     "scope": {"type": "roles", "roles": ["manager"]}},
]


def _task(**over):
    row = {
        "id": "task-1", "team_id": "T1", "task_key": "tk_1", "title": "11 月日报",
        "template_id": "tpl_1", "template_version": 1,
        "scope": {"type": "all"}, "start_date": "2026-11-01", "end_date": "",
        "due_time": "", "workdays_only": 0, "status": "active",
        "created_by": "u1", "created_at": "2026-11-01T00:00:00.000Z", "closed_at": None,
    }
    row.update(over)
    return row


# ---------------------------------------------------------------- 应提交口径

def test_no_task_falls_back_to_template_scope_union():
    members, source = expected.expected_for_day(MEMBERS, [], TEMPLATES, "2026-11-16")
    assert source == "template"
    assert [m["user_id"] for m in members] == ["u1", "u2"]


def test_task_overrides_template_scope():
    task = _task(scope={"type": "members", "memberIds": ["u1"]})
    members, source = expected.expected_for_day(MEMBERS, [task], TEMPLATES, "2026-11-16")
    assert source == "task"
    assert [m["user_id"] for m in members] == ["u1"]


def test_task_workdays_only_excludes_weekend_without_fallback():
    task = _task(start_date="2026-11-01", workdays_only=1)
    # 2026-11-14 是周六：任务存在但当天不应提交，也不能回退模板口径
    members, source = expected.expected_for_day(MEMBERS, [task], TEMPLATES, "2026-11-14")
    assert source == "task"
    assert members == []


def test_no_task_and_no_template_keeps_legacy_all_members():
    members, source = expected.expected_for_day(MEMBERS, [], [], "2026-11-16")
    assert source == "none"
    assert [m["user_id"] for m in members] == ["u1", "u2"]


def test_resolve_expected_uses_active_member_query(monkeypatch):
    captured = []

    def fake_query(conn, sql, args=None):
        captured.append(sql)
        if "FROM `members`" in sql:
            return MEMBERS
        if "FROM `form_templates`" in sql:
            return TEMPLATES
        if "FROM `report_tasks`" in sql:
            return []
        return []

    monkeypatch.setattr(expected.db, "query", fake_query)
    result = expected.resolve_expected(None, "T1", "2026-11-16")
    assert result["source"] == "template"
    assert [m["user_id"] for m in result["members"]] == ["u1", "u2"]
    assert any("status = 'active'" in sql for sql in captured)


def test_task_scope_matches_roles_and_members():
    assert expected.scope_matches({"type": "all"}, MEMBERS[0])
    assert expected.scope_matches({"type": "members", "memberIds": ["u1"]}, MEMBERS[0])
    assert not expected.scope_matches({"type": "members", "memberIds": ["u2"]}, MEMBERS[0])
    assert expected.scope_matches({"type": "roles", "roles": ["manager"]}, MEMBERS[1])
    assert not expected.scope_matches({"type": "roles", "roles": ["manager"]}, MEMBERS[0])


# ---------------------------------------------------------------- 状态机

def test_member_status_transitions():
    today = "2026-11-16"
    submitted = {"status": "submitted", "created_at": "2026-11-16T01:00:00.000Z",
                 "entry_date": "2026-11-16"}
    backfilled = {"status": "submitted", "created_at": "2026-11-18T01:00:00.000Z",
                  "entry_date": "2026-11-16"}

    assert tk._member_status(None, today, today, "10:00", False) == "pending"
    assert tk._member_status(None, "2026-11-15", today, "10:00", False) == "late"
    assert tk._member_status(None, today, today, "10:00", True) == "closed"
    assert tk._member_status(submitted, today, today, "10:00", False) == "submitted"
    assert tk._member_status(backfilled, today, today, "10:00", False) == "backfilled"
    # 当天过了截止时间即视为逾期
    assert tk._member_status(None, today, today, "19:00", False, "18:00") == "late"


def test_status_view_counts_and_missing_list():
    entries = {
        "u1": {"status": "submitted", "created_at": "2026-11-16T01:00:00.000Z"},
        "u3": {"status": "draft", "created_at": "2026-11-16T01:00:00.000Z"},
    }
    members = MEMBERS + [
        {"id": "m3", "user_id": "u3", "name": "王五", "role": "member", "status": "active"},
    ]
    view = tk._status_view(members, entries, "2026-11-16", "2026-11-16", "10:00", False)
    assert view["expectedCount"] == 3
    assert view["submittedCount"] == 1
    assert view["pendingCount"] == 2
    assert view["missingCount"] == 2
    assert view["rateText"] == "33%"
    draft = [m for m in view["missing"] if m["userId"] == "u3"][0]
    assert draft["draft"] is True


# ---------------------------------------------------------------- 创建任务

def _patch_create(monkeypatch, template=None, inserted=None, audits=None):
    inserted = inserted if inserted is not None else []
    audits = audits if audits is not None else []
    monkeypatch.setattr(tk, "require_manager", lambda *a, **k: {"user_id": "u1"})
    monkeypatch.setattr(tk, "_resolve_template",
                        lambda *a, **k: template or {
                            "template_id": "tpl_1", "version": 3, "name": "日报",
                            "scope": {"type": "roles", "roles": ["member"]},
                        })
    monkeypatch.setattr(tk.db, "gen_id", lambda: "abcdef1234567890")
    monkeypatch.setattr(tk.db, "now_iso", lambda: "2026-11-16T00:00:00.000Z")
    monkeypatch.setattr(
        tk.db, "insert",
        lambda conn, table, data: inserted.append((table, data)) or "task-new",
    )
    monkeypatch.setattr(tk, "audit", lambda *a, **k: audits.append(a))
    return inserted, audits


def _create_payload(**over):
    payload = {
        "team_id": "T1",
        "title": "11 月日报任务",
        "template_id": "tpl_1",
        "start_date": "2026-11-16",
        "end_date": "2026-11-30",
        "due_time": "18:00",
        "workdays_only": True,
    }
    payload.update(over)
    return {"payload": payload}


def test_create_task_snapshots_scope_and_template_version(monkeypatch):
    inserted, audits = _patch_create(monkeypatch)
    result = tk.create_report_task(None, "u1", _create_payload())

    assert [t for t, _ in inserted] == ["report_tasks"]
    data = inserted[0][1]
    assert data["task_key"] == "tk_abcdef123456"
    assert data["template_version"] == 3
    assert data["scope"] == {"type": "roles", "roles": ["member"]}
    assert data["workdays_only"] == 1
    assert data["status"] == "active"
    assert result["id"] == "task-new"
    assert result["statusText"] == "进行中"
    assert result["scopeText"] == "指定角色：成员"
    assert audits and audits[0][3] == "task_create"


def test_create_task_validates_title_and_dates(monkeypatch):
    _patch_create(monkeypatch)
    with pytest.raises(BusinessError, match="任务名称"):
        tk.create_report_task(None, "u1", _create_payload(title="  "))
    with pytest.raises(BusinessError, match="开始日期"):
        tk.create_report_task(None, "u1", _create_payload(start_date=""))
    with pytest.raises(BusinessError, match="不能早于"):
        tk.create_report_task(None, "u1", _create_payload(end_date="2026-11-01"))
    with pytest.raises(BusinessError, match="截止时间"):
        tk.create_report_task(None, "u1", _create_payload(due_time="25:00"))
    with pytest.raises(BusinessError, match="周期"):
        tk.create_report_task(None, "u1", _create_payload(end_date="2027-12-31"))


def test_resolve_template_rejects_missing_and_draft(monkeypatch):
    monkeypatch.setattr(tk.db, "one", lambda *a, **k: None)
    with pytest.raises(BusinessError, match="不存在"):
        tk._resolve_template(None, "T1", "tpl_x", None)

    row = dict(TEMPLATES[0], status="draft")
    monkeypatch.setattr(tk.db, "one", lambda *a, **k: row)
    with pytest.raises(BusinessError, match="已发布"):
        tk._resolve_template(None, "T1", "tpl_1", None)


# ---------------------------------------------------------------- 列表与关闭

def test_list_tasks_filters_and_decorates(monkeypatch):
    captured = {}
    monkeypatch.setattr(tk, "require_manager", lambda *a, **k: {"user_id": "u1"})

    def fake_query(conn, sql, args=None):
        captured["sql"] = sql
        captured["args"] = args
        return [_task(template_version=1)]

    monkeypatch.setattr(tk.db, "query", fake_query)
    monkeypatch.setattr(tk, "_template_name_map", lambda *a, **k: (
        {("tpl_1", 1): "成员日报"}, {"tpl_1": "成员日报"},
    ))
    rows = tk.list_report_tasks(None, "u1", {"teamId": "T1", "status": "closed", "limit": 20})
    assert "status = %s" in captured["sql"]
    assert captured["args"] == ("T1", "closed", 20)
    assert rows[0]["templateName"] == "成员日报"
    assert rows[0]["dateText"] == "2026-11-01 起"


def test_close_task_is_idempotent(monkeypatch):
    updates = []
    monkeypatch.setattr(tk, "require_manager", lambda *a, **k: {"user_id": "u1"})
    monkeypatch.setattr(tk, "_template_name_map", lambda *a, **k: ({}, {}))
    monkeypatch.setattr(tk.db, "now_iso", lambda: "2026-11-16T00:00:00.000Z")
    monkeypatch.setattr(tk.db, "update",
                        lambda conn, table, doc_id, patch: updates.append((table, doc_id, patch)))
    monkeypatch.setattr(tk, "audit", lambda *a, **k: None)

    monkeypatch.setattr(tk.db, "get_doc", lambda *a, **k: _task())
    first = tk.close_report_task(None, "u1", {"id": "task-1"})
    assert first["status"] == "closed"
    assert updates[0][2]["status"] == "closed"

    monkeypatch.setattr(tk.db, "get_doc", lambda *a, **k: _task(status="closed"))
    second = tk.close_report_task(None, "u1", {"id": "task-1"})
    assert second["status"] == "closed"
    assert len(updates) == 1, "已关闭任务重复关闭不应再次写库"


# ---------------------------------------------------------------- 状态查询

def test_day_status_without_task(monkeypatch):
    monkeypatch.setattr(tk, "require_manager", lambda *a, **k: {"user_id": "u1"})
    monkeypatch.setattr(expected, "local_today", lambda: "2026-11-16")
    monkeypatch.setattr(expected, "resolve_expected", lambda *a, **k: {
        "members": MEMBERS, "source": "template", "tasks": [], "templates": TEMPLATES,
    })
    monkeypatch.setattr(tk, "_entries_on", lambda *a, **k: {
        "u1": {"status": "submitted", "created_at": "2026-11-16T01:00:00.000Z"},
    })
    view = tk.get_report_task_status(None, "u1", {"teamId": "T1", "date": "2026-11-16"})
    assert view["source"] == "template"
    assert view["expectedCount"] == 2
    assert view["submittedCount"] == 1
    assert view["rateText"] == "50%"
    assert view["missing"][0]["userId"] == "u2"


def test_task_status_closed_marks_non_submitters_closed(monkeypatch):
    monkeypatch.setattr(tk, "require_manager", lambda *a, **k: {"user_id": "u1"})
    monkeypatch.setattr(expected, "local_today", lambda: "2026-11-16")
    monkeypatch.setattr(expected, "load_active_members", lambda *a, **k: MEMBERS)
    monkeypatch.setattr(tk, "_entries_on", lambda *a, **k: {})
    monkeypatch.setattr(tk, "_template_name_map", lambda *a, **k: ({}, {}))
    monkeypatch.setattr(tk.db, "get_doc", lambda *a, **k: _task(status="closed"))
    view = tk.get_report_task_status(
        None, "u1", {"teamId": "T1", "taskId": "task-1", "date": "2026-11-16"}
    )
    assert view["closedCount"] == 2
    assert view["missingCount"] == 0
    assert all(m["status"] == "closed" for m in view["expected"])


def test_range_status_dedupes_expected_users(monkeypatch):
    monkeypatch.setattr(tk, "require_manager", lambda *a, **k: {"user_id": "u1"})
    monkeypatch.setattr(expected, "load_active_members", lambda *a, **k: MEMBERS)
    monkeypatch.setattr(expected, "load_published_templates", lambda *a, **k: TEMPLATES)
    monkeypatch.setattr(expected, "load_tasks", lambda *a, **k: [])
    monkeypatch.setattr(tk.db, "query", lambda *a, **k: [
        {"user_id": "u1", "entry_date": "2026-11-15"},
    ])
    view = tk.get_report_task_status(
        None, "u1", {"teamId": "T1", "from": "2026-11-14", "to": "2026-11-16"}
    )
    assert view["expectedCount"] == 2
    assert view["submittedCount"] == 1
    assert view["rateText"] == "50%"
    assert view["missingCount"] == 1
