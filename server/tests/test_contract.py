"""契约回归：action 覆盖、JWT 往返、字段白名单、时间格式、幂等键定义。

这些测试不依赖真实 MySQL，可在无数据库环境下执行：
    cd server && python -m pytest -q
"""
import re
from pathlib import Path

import pytest

from app import auth, config, db
from app.handlers import HANDLERS, BusinessError, dispatch

# 旧云函数 handlers 表中在用的 22 个 action（逐一迁移，缺一即为回归）
LEGACY_ACTIONS = {
    "createTeam", "findTeam", "joinTeam", "getTeam", "updateTeamConfig",
    "getMyMember", "listMembers", "updateMember", "removeMember",
    "listTemplates", "listPublishedTemplates", "getTemplate", "createDraft",
    "updateTemplateRow", "deleteTemplateRow", "nextVersion", "publishTemplate",
    "getMyEntry", "saveEntry", "listMyEntries", "listTeamEntries", "log",
}

# listEntriesByUser 在旧云函数中零调用，审阅确认为死分支，本次清理未迁移
REMOVED_DEAD_ACTIONS = {"listEntriesByUser"}


def test_all_legacy_actions_migrated():
    assert set(HANDLERS) == LEGACY_ACTIONS
    assert len(HANDLERS) == 22
    assert not (REMOVED_DEAD_ACTIONS & set(HANDLERS))


def test_unknown_action_raises_business_error():
    with pytest.raises(BusinessError, match="未知操作"):
        dispatch(None, "openid-x", {"action": "notExist"})


def test_jwt_roundtrip(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "unit-test-secret")
    token = auth.issue_token("openid-abc", "unionid-1")
    assert auth.extract_uid("Bearer " + token) == "openid-abc"


def test_jwt_rejects_tampered_and_malformed(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "unit-test-secret")
    assert auth.extract_uid(None) is None
    assert auth.extract_uid("Basic abc") is None
    assert auth.extract_uid("Bearer garbage") is None
    token = auth.issue_token("openid-abc")
    flipped = ("A" if token[0] != "A" else "B") + token[1:]
    assert auth.extract_uid("Bearer " + flipped) is None


def test_expired_token_rejected(monkeypatch):
    import jwt
    import time
    monkeypatch.setattr(config, "JWT_SECRET", "unit-test-secret")
    now = int(time.time())
    expired = jwt.encode(
        {"sub": "openid-abc", "iss": auth.JWT_ISS, "iat": now - 7200, "exp": now - 3600},
        "unit-test-secret", algorithm=auth.JWT_ALG,
    )
    assert auth.extract_uid("Bearer " + expired) is None


def test_now_iso_matches_js_to_iso_string():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", db.now_iso())


def test_string_ids_match_legacy_oid_shape():
    assert re.fullmatch(r"[0-9a-f]{24}", db.gen_id())


def test_json_column_mapping_covers_all_tables():
    assert set(db.JSON_COLUMNS) == {
        "teams", "members", "form_templates", "daily_entries", "audit_logs",
    }
    assert "form_data" in db.JSON_COLUMNS["daily_entries"]
    assert "fields" in db.JSON_COLUMNS["form_templates"]


def test_schema_has_required_unique_keys():
    sql = (Path(__file__).resolve().parent.parent / "sql" / "schema.sql").read_text("utf-8")
    for key in (
        "uk_teams_team_id", "uk_members_team_user",
        "uk_tpl_team_id_ver", "uk_entry_team_user_date",
    ):
        assert key in sql


def test_illegal_identifiers_rejected():
    with pytest.raises(ValueError):
        db._check_table("teams; DROP TABLE members")
    with pytest.raises(ValueError):
        db._check_table("unknown_table")
    with pytest.raises(ValueError):
        db._check_column("name); DROP TABLE members; --")
    assert db._check_table("daily_entries") == "daily_entries"
    assert db._check_column("effective_from") == "effective_from"


def test_entry_payload_whitelist_strips_identity():
    """客户端伪造 user_id 必须被 _clean_payload 丢弃。"""
    from app.handlers.entries import _clean_payload
    cleaned = _clean_payload({
        "team_id": "T1", "entry_date": "2026-11-09",
        "user_id": "attacker-openid", "status": "submitted",
        "id": "forged-id", "role": "owner",
    })
    assert "user_id" not in cleaned
    assert "id" not in cleaned
    assert "role" not in cleaned
    assert cleaned["team_id"] == "T1"


# ---- 业务流程回归（对应 2026-11-09 全链路走查的 P0/P1 修复）----

def test_submitted_rows_validated_by_template_fields():
    """服务端必须复核必填、数字、范围、整数与选项，不能只信前端。"""
    from app.handlers.entries import _validate_rows
    fields = [
        {"fieldKey": "visits", "label": "到访", "type": "integer", "required": True,
         "validation": {"min": 0, "max": 100}, "options": []},
        {"fieldKey": "channel", "label": "渠道", "type": "select", "required": False,
         "options": ["抖音", "视频号"], "validation": {}},
    ]
    rows = [{"rowId": "r1", "values": {"visits": 3, "channel": "抖音"}}]
    _validate_rows(fields, rows)
    with pytest.raises(BusinessError, match="必填项"):
        _validate_rows(fields, [{"rowId": "r1", "values": {"channel": "抖音"}}])
    with pytest.raises(BusinessError, match="必须是数字"):
        _validate_rows(fields, [{"rowId": "r1", "values": {"visits": "abc"}}])
    with pytest.raises(BusinessError, match="不能大于"):
        _validate_rows(fields, [{"rowId": "r1", "values": {"visits": 101}}])
    with pytest.raises(BusinessError, match="必须是整数"):
        _validate_rows(fields, [{"rowId": "r1", "values": {"visits": 1.5}}])
    with pytest.raises(BusinessError, match="选项不合法"):
        _validate_rows(fields, [{"rowId": "r1", "values": {"visits": 1, "channel": "小红书"}}])


def test_publish_keeps_draft_effective_date(monkeypatch):
    """发布不得用前端 today 覆盖管理员预设的生效日。"""
    from app.handlers import templates as tpl
    draft = {
        "id": "tpl-id", "team_id": "T1", "template_id": "tpl_1", "version": 2,
        "status": "draft", "effective_from": "2026-12-01", "name": "日报",
        "fields": [], "scope": {"type": "all"},
    }
    updates = []
    monkeypatch.setattr(tpl.db, "get_doc", lambda *a, **k: draft)
    monkeypatch.setattr(tpl.db, "now_iso", lambda: "2026-11-09T00:00:00.000Z")
    monkeypatch.setattr(tpl.db, "query", lambda *a, **k: [])
    monkeypatch.setattr(tpl.db, "insert", lambda *a, **k: "audit-id")
    monkeypatch.setattr(tpl.db, "update",
                        lambda conn, table, doc_id, patch: updates.append((table, patch)))
    # 团队行锁返回一行；版本号无冲突
    monkeypatch.setattr(tpl.db, "one",
                        lambda *a, **k: {"id": "team-row"} if "FOR UPDATE" in a[1] else None)
    monkeypatch.setattr(tpl, "require_manager",
                        lambda *a, **k: {"user_id": "u1", "role": "owner"})
    result = tpl.publish_template(None, "u1", {"id": "tpl-id", "today": "2026-11-09"})
    assert result["effective_from"] == "2026-12-01"
    assert updates[0][1]["status"] == "published"
    assert updates[0][1]["effective_from"] == "2026-12-01"


def test_create_team_blocks_second_team(monkeypatch):
    """已有团队的成员不能创建第二个团队（否则 getMyMember 上下文随机）。"""
    from app.handlers import teams as tm
    monkeypatch.setattr(tm, "find_member_by_uid", lambda *a, **k: {"team_id": "T1"})
    with pytest.raises(BusinessError, match="多个团队"):
        tm.create_team(None, "openid-x", {"name": "第二个团队", "memberName": "张三"})


def test_join_team_blocks_other_team(monkeypatch):
    """已在 A 队的用户不能用邀请码加入 B 队。"""
    from app.handlers import teams as tm
    monkeypatch.setattr(tm, "find_team_by_id", lambda *a, **k: {"team_id": "T2", "name": "B队"})
    monkeypatch.setattr(tm.db, "one", lambda *a, **k: None)
    monkeypatch.setattr(tm, "find_member_by_uid", lambda *a, **k: {"team_id": "T1"})
    with pytest.raises(BusinessError, match="多个团队"):
        tm.join_team(None, "openid-x", {"teamId": "T2", "memberName": "张三"})


def test_disabled_member_gets_clear_error(monkeypatch):
    """停用成员应得到明确提示，而不是被前端误判成未登录。"""
    from app.handlers import members as m
    monkeypatch.setattr(m, "find_member_by_uid",
                        lambda *a, **k: {"user_id": "u1", "status": "disabled"})
    with pytest.raises(BusinessError, match="停用"):
        m.get_my_member(None, "u1", {})


# ---- 边界与打磨回归（对应 2026-11-09 全链路走查的 P2 修复）----

def test_entry_date_window_rejects_future_and_stale_dates():
    """补录窗口必须在服务端独立校验，不能只信前端日历。"""
    from datetime import datetime, timedelta, timezone
    from app.handlers.entries import _check_entry_date, BACKFILL_DAYS

    assert BACKFILL_DAYS == 31
    now = datetime.now(timezone.utc)
    assert _check_entry_date(now.strftime("%Y-%m-%d")) == now.strftime("%Y-%m-%d")
    assert _check_entry_date((now - timedelta(days=7)).strftime("%Y-%m-%d"))
    with pytest.raises(BusinessError, match="补录范围"):
        _check_entry_date((now + timedelta(days=10)).strftime("%Y-%m-%d"))
    with pytest.raises(BusinessError, match="补录范围"):
        _check_entry_date((now - timedelta(days=90)).strftime("%Y-%m-%d"))
    with pytest.raises(BusinessError, match="格式"):
        _check_entry_date("2026/11/09")


def test_list_team_entries_pagination_and_stable_order(monkeypatch):
    """分页参数生效、排序稳定，且非法 page/pageSize 被夹到安全范围。"""
    from app.handlers import entries as en
    captured = {}
    monkeypatch.setattr(en, "require_manager", lambda *a, **k: {"user_id": "u1"})

    def fake_query(conn, sql, args=None):
        captured["sql"] = sql
        captured["args"] = args
        return []

    monkeypatch.setattr(en.db, "query", fake_query)
    payload = {
        "teamId": "T1", "from": "2026-11-01", "to": "2026-11-30",
        "page": 2, "pageSize": 500,
    }
    assert en.list_team_entries(None, "u1", payload) == []
    assert "ORDER BY entry_date DESC, id DESC" in captured["sql"]
    assert "LIMIT %s OFFSET %s" in captured["sql"]
    assert captured["args"] == ("T1", "2026-11-01", "2026-11-30", 500, 1000)

    en.list_team_entries(None, "u1", dict(payload, page="bad", pageSize=99999))
    assert captured["args"][-2:] == (1000, 0)


def test_draft_template_preview_requires_manager(monkeypatch):
    """草稿/归档模板只有管理员可读；已发布版本对普通成员开放。"""
    from app.handlers import templates as tpl
    calls = []
    row = {"id": "t1", "team_id": "T1", "status": "draft"}
    monkeypatch.setattr(tpl.db, "get_doc", lambda *a, **k: row)
    monkeypatch.setattr(tpl, "require_manager", lambda *a, **k: calls.append("manager"))
    monkeypatch.setattr(tpl, "require_member", lambda *a, **k: calls.append("member"))

    tpl.get_template(None, "u1", {"id": "t1"})
    assert calls == ["manager"]

    row["status"] = "published"
    tpl.get_template(None, "u1", {"id": "t1"})
    assert calls == ["manager", "member"]


def test_publish_resolves_concurrent_version_conflict(monkeypatch):
    """两个管理员基于同一版本建草稿时，发布应顺延版本号而不是撞唯一键。"""
    from app.handlers import templates as tpl
    draft = {
        "id": "tpl-new", "team_id": "T1", "template_id": "tpl_1", "version": 2,
        "status": "draft", "effective_from": "2026-12-01", "name": "日报",
        "fields": [], "scope": {"type": "all"},
    }
    updates = []
    locked = []

    def fake_one(conn, sql, args=None):
        if "FOR UPDATE" in sql:
            locked.append(sql)
            return {"id": "team-row"}
        if "SELECT id FROM `form_templates`" in sql:
            return {"id": "tpl-old"}  # 同版本已存在 -> 冲突
        if "MAX(version)" in sql:
            return {"v": 3}
        return None

    monkeypatch.setattr(tpl.db, "get_doc", lambda *a, **k: draft)
    monkeypatch.setattr(tpl.db, "one", fake_one)
    monkeypatch.setattr(tpl.db, "now_iso", lambda: "2026-11-09T00:00:00.000Z")
    monkeypatch.setattr(tpl.db, "query", lambda *a, **k: [])
    monkeypatch.setattr(tpl.db, "insert", lambda *a, **k: "audit-id")
    monkeypatch.setattr(tpl.db, "update",
                        lambda conn, table, doc_id, patch: updates.append((table, patch)))
    monkeypatch.setattr(tpl, "require_manager",
                        lambda *a, **k: {"user_id": "u1", "role": "owner"})

    result = tpl.publish_template(None, "u1", {"id": "tpl-new", "today": "2026-11-09"})
    assert locked and "FOR UPDATE" in locked[0]
    assert result["version"] == 4
    assert updates[0][1]["version"] == 4
    assert result["effective_from"] == "2026-12-01"
