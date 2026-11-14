"""P0 基线回归：登录链路、团队创建、日报幂等、库结构快照。

这些测试不依赖真实 MySQL 与真实微信接口，全部通过 monkeypatch 隔离，
用于在升级动工前把当前行为固化为可回归的基线。

    cd server && python3 -m pytest -q
"""
import re
from pathlib import Path

import pytest

from app import auth, config
from app.handlers import BusinessError

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
SCHEMA = SCHEMA_PATH.read_text("utf-8")


# ---------------------------------------------------------------- 登录链路

class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _set_wx(monkeypatch, appid="wx-test", secret="wx-secret-test"):
    monkeypatch.setattr(config, "WX_APPID", appid)
    monkeypatch.setattr(config, "WX_SECRET", secret)


def test_code2session_rejects_empty_and_oversized_code(monkeypatch):
    _set_wx(monkeypatch)
    for bad in ("", None, 123, "x" * 257):
        with pytest.raises(auth.AuthError, match="凭证无效"):
            auth.code2session(bad)


def test_code2session_requires_app_credentials(monkeypatch):
    _set_wx(monkeypatch, appid="", secret="")
    with pytest.raises(auth.AuthError, match="未配置"):
        auth.code2session("valid-code")


def test_code2session_returns_openid_and_unionid(monkeypatch):
    _set_wx(monkeypatch)
    monkeypatch.setattr(
        auth.requests, "get",
        lambda *a, **k: _FakeResp({"openid": "o-1", "unionid": "u-1"}),
    )
    assert auth.code2session("code-1") == {"openid": "o-1", "unionid": "u-1"}


def test_code2session_hides_wechat_error_detail(monkeypatch):
    """微信原始错误码与文本不得透传给客户端，避免泄露配置线索。"""
    _set_wx(monkeypatch)
    monkeypatch.setattr(
        auth.requests, "get",
        lambda *a, **k: _FakeResp({"errcode": 40029, "errmsg": "invalid code"}),
    )
    with pytest.raises(auth.AuthError) as exc:
        auth.code2session("code-1")
    assert "40029" not in str(exc.value)
    assert "invalid code" not in str(exc.value)


def test_code2session_rejects_missing_openid(monkeypatch):
    _set_wx(monkeypatch)
    monkeypatch.setattr(auth.requests, "get", lambda *a, **k: _FakeResp({"session_key": "k"}))
    with pytest.raises(auth.AuthError, match="未获取到身份"):
        auth.code2session("code-1")


def test_code2session_network_error_is_friendly(monkeypatch):
    _set_wx(monkeypatch)

    def boom(*a, **k):
        raise auth.requests.RequestException("timeout")

    monkeypatch.setattr(auth.requests, "get", boom)
    with pytest.raises(auth.AuthError, match="暂时不可用"):
        auth.code2session("code-1")


def test_token_carries_unionid_only_when_present(monkeypatch):
    import jwt as pyjwt

    monkeypatch.setattr(config, "JWT_SECRET", "unit-test-secret")
    plain = pyjwt.decode(
        auth.issue_token("o-1"), "unit-test-secret",
        algorithms=[auth.JWT_ALG], issuer=auth.JWT_ISS,
    )
    assert "unionid" not in plain
    bound = pyjwt.decode(
        auth.issue_token("o-1", "u-1"), "unit-test-secret",
        algorithms=[auth.JWT_ALG], issuer=auth.JWT_ISS,
    )
    assert bound["unionid"] == "u-1"
    assert bound["sub"] == "o-1"


# ---------------------------------------------------------------- 团队创建

def _patch_team_deps(monkeypatch, tm, existing_member=None, team_lookup=None,
                     inserted=None, audited=None):
    inserted = inserted if inserted is not None else []
    audited = audited if audited is not None else []
    monkeypatch.setattr(tm, "find_member_by_uid", lambda *a, **k: existing_member)
    monkeypatch.setattr(tm, "find_team_by_id", team_lookup or (lambda *a, **k: None))
    monkeypatch.setattr(tm.db, "now_iso", lambda: "2026-11-14T00:00:00.000Z")
    monkeypatch.setattr(
        tm.db, "insert",
        lambda conn, table, data: inserted.append((table, data)) or "id-%d" % len(inserted),
    )
    monkeypatch.setattr(tm, "audit", lambda *a, **k: audited.append(a))
    return inserted, audited


def test_create_team_normal_path(monkeypatch):
    from app.handlers import teams as tm

    inserted, audited = _patch_team_deps(monkeypatch, tm)
    result = tm.create_team(None, "o-owner", {"name": "销售一队", "memberName": "张三"})

    assert [t for t, _ in inserted] == ["teams", "members"]
    team = inserted[0][1]
    # 邀请码格式：T + 6 位（排除易混淆字符）
    assert re.fullmatch(r"T[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}", team["team_id"])
    assert team["owner_uid"] == "o-owner"
    assert team["config"] == {"memberSeeTeamTotal": False}

    member = inserted[1][1]
    assert member["role"] == "owner"
    assert member["status"] == "active"
    assert member["team_id"] == team["team_id"]
    assert member["user_id"] == "o-owner"

    assert result["team"]["team_id"] == team["team_id"]
    assert result["member"]["role"] == "owner"
    assert audited and audited[0][2] == team["team_id"]


def test_create_team_retries_on_code_collision(monkeypatch):
    from app.handlers import teams as tm

    codes = iter(["TAAAAAA", "TAAAAAA", "TBBBBBB"])
    monkeypatch.setattr(tm, "gen_team_code", lambda: next(codes))
    _patch_team_deps(
        monkeypatch, tm,
        team_lookup=lambda conn, code: {"team_id": code} if code == "TAAAAAA" else None,
    )
    result = tm.create_team(None, "o-owner", {"name": "队"})
    assert result["team"]["team_id"] == "TBBBBBB"


def test_create_team_fails_after_five_collisions(monkeypatch):
    from app.handlers import teams as tm

    monkeypatch.setattr(tm, "gen_team_code", lambda: "TDUP000")
    _patch_team_deps(monkeypatch, tm, team_lookup=lambda *a, **k: {"team_id": "dup"})
    with pytest.raises(BusinessError, match="生成团队编号失败"):
        tm.create_team(None, "o-owner", {"name": "队"})


def test_create_team_requires_name(monkeypatch):
    from app.handlers import teams as tm

    _patch_team_deps(monkeypatch, tm)
    with pytest.raises(BusinessError, match="团队名称"):
        tm.create_team(None, "o-owner", {"name": "   "})


# ---------------------------------------------------------------- 日报幂等

def _entry_payload(status="submitted", **over):
    payload = {
        "team_id": "T1",
        "entry_date": "2026-11-14",
        "template_id": "tpl_1",
        "template_version": 1,
        "form_data": [{"rowId": "r1", "values": {"visits": 3}}],
        "status": status,
    }
    payload.update(over)
    return {"payload": payload}


def _patch_entry_deps(monkeypatch, en, existing=None):
    calls = {"insert": [], "update": [], "audit": []}
    monkeypatch.setattr(en, "_check_entry_date", lambda d: d)
    monkeypatch.setattr(en, "require_member", lambda *a, **k: {"role": "member"})
    monkeypatch.setattr(en, "_template_fields", lambda *a, **k: [])
    monkeypatch.setattr(en, "_validate_rows", lambda *a, **k: None)
    monkeypatch.setattr(en, "_entry", lambda *a, **k: existing)
    monkeypatch.setattr(en.db, "now_iso", lambda: "2026-11-14T00:00:00.000Z")
    monkeypatch.setattr(
        en.db, "insert",
        lambda conn, table, data: calls["insert"].append((table, data)) or "e-new",
    )
    monkeypatch.setattr(
        en.db, "update",
        lambda *a, **k: calls["update"].append(a),
    )
    monkeypatch.setattr(en, "audit", lambda *a, **k: calls["audit"].append(a))
    return calls


def test_save_entry_first_write_inserts_and_audits(monkeypatch):
    from app.handlers import entries as en

    calls = _patch_entry_deps(monkeypatch, en, existing=None)
    row = en.save_entry(None, "o-1", _entry_payload())

    assert [t for t, _ in calls["insert"]] == ["daily_entries"]
    written = calls["insert"][0][1]
    # 身份只取 JWT，客户端无法伪造
    assert written["user_id"] == "o-1"
    assert row["id"] == "e-new"
    assert len(calls["audit"]) == 1
    assert not calls["update"]


def test_save_entry_second_write_updates_same_row(monkeypatch):
    """同人同日第二次提交必须覆盖原行，不得新增（唯一键 + FOR UPDATE 的结果）。"""
    from app.handlers import entries as en

    existing = {
        "id": "e-1", "team_id": "T1", "user_id": "o-1",
        "entry_date": "2026-11-14", "form_data": [], "status": "draft",
    }
    calls = _patch_entry_deps(monkeypatch, en, existing=existing)
    en.save_entry(None, "o-1", _entry_payload())

    assert not calls["insert"]
    assert len(calls["update"]) == 1
    _, table, doc_id, patch = calls["update"][0]
    assert table == "daily_entries"
    assert doc_id == "e-1"
    # 身份与日期字段不允许被覆盖
    assert "user_id" not in patch
    assert "team_id" not in patch
    assert "entry_date" not in patch
    assert "updated_at" in patch


def test_save_draft_does_not_audit(monkeypatch):
    from app.handlers import entries as en

    calls = _patch_entry_deps(monkeypatch, en, existing=None)
    en.save_entry(None, "o-1", _entry_payload(status="draft"))
    assert not calls["audit"]


def test_save_entry_rejects_cross_team_write(monkeypatch):
    from app.handlers import entries as en

    def deny(*a, **k):
        raise BusinessError("你不是该团队成员或已被停用")

    monkeypatch.setattr(en, "_check_entry_date", lambda d: d)
    monkeypatch.setattr(en, "require_member", deny)
    with pytest.raises(BusinessError, match="不是该团队成员"):
        en.save_entry(None, "o-1", _entry_payload())


def test_save_entry_requires_team_and_date(monkeypatch):
    from app.handlers import entries as en

    _patch_entry_deps(monkeypatch, en)
    for bad in ({"entry_date": "2026-11-14"}, {"team_id": "T1"}):
        with pytest.raises(BusinessError, match="参数错误"):
            en.save_entry(None, "o-1", {"payload": bad})


# ---------------------------------------------------------------- 库结构快照

EXPECTED_TABLES = ("teams", "members", "form_templates", "daily_entries", "audit_logs")

EXPECTED_COLUMNS = {
    "teams": ["id", "team_id", "name", "owner_uid", "config", "created_at"],
    "members": ["id", "team_id", "user_id", "name", "role", "status", "joined_at"],
    "form_templates": ["id", "team_id", "template_id", "version", "name", "description",
                       "entry_mode", "status", "fields", "scope", "effective_from",
                       "created_by", "created_at", "published_by", "published_at"],
    "daily_entries": ["id", "team_id", "user_id", "entry_date", "template_id",
                      "template_version", "form_data", "status", "source",
                      "created_at", "updated_at"],
    "audit_logs": ["id", "team_id", "actor", "action", "target_type",
                   "target_id", "detail", "created_at"],
}

EXPECTED_KEYS = (
    "uk_teams_team_id",
    "uk_members_team_user",
    "uk_tpl_team_id_ver",
    "uk_entry_team_user_date",
    "idx_members_user",
    "idx_members_team",
    "idx_tpl_team_status",
    "idx_entry_team_date",
    "idx_entry_team_user_date",
    "idx_audit_team_time",
)


def _table_block(table):
    start = SCHEMA.index("CREATE TABLE IF NOT EXISTS `%s`" % table)
    end = SCHEMA.index("ENGINE=InnoDB", start)
    return SCHEMA[start:end]


@pytest.mark.parametrize("table", EXPECTED_TABLES)
def test_schema_tables_snapshot(table):
    assert "CREATE TABLE IF NOT EXISTS `%s`" % table in SCHEMA


@pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
def test_schema_columns_snapshot(table):
    block = _table_block(table)
    for column in EXPECTED_COLUMNS[table]:
        assert "`%s`" % column in block, "%s.%s 缺失" % (table, column)


def test_schema_indexes_snapshot():
    for key in EXPECTED_KEYS:
        assert key in SCHEMA, "缺少索引 %s" % key


def test_schema_entry_idempotent_key_is_composite():
    """日报幂等依赖三元组唯一键，缺任何一个字段都会产生重复日报。"""
    block = _table_block("daily_entries")
    assert re.search(
        r"UNIQUE KEY `uk_entry_team_user_date` \(`team_id`, `user_id`, `entry_date`\)",
        block,
    )


def test_json_columns_match_schema():
    from app import db
    for table, columns in db.JSON_COLUMNS.items():
        block = _table_block(table)
        for column in columns:
            assert re.search(r"`%s`\s+JSON" % column, block), \
                "%s.%s 在代码中按 JSON 处理，但表定义不是 JSON" % (table, column)
