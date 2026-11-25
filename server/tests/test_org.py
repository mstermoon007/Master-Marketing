"""P4 组织与多工作空间：跨空间隔离、空间管理员、只读角色、部门层级、迁移脚本。

沿用 test_contract / test_baseline 的 monkeypatch 风格，不依赖真实 MySQL：
权限判定走真实的 common.require_*，只把 org 的查库函数替换成内存实现。
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.handlers import BusinessError, common
from app.services import org

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 辅助

def _team(team_id="T1", workspace_id="W1", department_id=None):
    return {
        "id": "row-" + team_id,
        "team_id": team_id,
        "workspace_id": workspace_id,
        "department_id": department_id,
        "name": team_id + " 队",
        "owner_name": "张三",
        "owner_uid": "openid-owner",
        "config": {"memberSeeTeamTotal": False},
    }


def _member(uid="openid-1", role="member", team_id="T1", status="active", left_at=None):
    return {
        "id": "m-" + uid,
        "team_id": team_id,
        "user_id": uid,
        "name": "成员",
        "role": role,
        "status": status,
        "left_at": left_at,
        "joined_at": "2026-11-01T00:00:00.000Z",
    }


def _ctx(uid, role, team_id="T1", workspace_id="W1", member=None, is_team_member=True):
    return {
        "user_id": uid, "team_id": team_id, "workspace_id": workspace_id,
        "workspace_role": role if role in org.WORKSPACE_ROLES else None,
        "effective_role": role,
        "member": member, "is_team_member": is_team_member,
        "is_department_leader": False,
        "membership_id": None,
    }


def _patch_access(monkeypatch, *, team=None, member=None, ws_role=None,
                  dept_leader=False):
    """替换 org 的查库函数，让 common.team_access 在内存里组装上下文。"""
    monkeypatch.setattr(org, "team_context", lambda conn, tid: team)
    monkeypatch.setattr(org, "workspace_role", lambda conn, uid, wid: ws_role)
    monkeypatch.setattr(org, "is_department_leader", lambda *a, **k: dept_leader)
    monkeypatch.setattr(common, "find_member_by_uid", lambda conn, uid, tid=None: member)


# ---------------------------------------------------------------- 1. 跨空间拒绝

def test_cross_workspace_read_and_write_denied(monkeypatch):
    """W1 的用户拿 W2 的 teamId：读、写 action 都必须拒绝。"""
    from app.handlers import entries as en

    _patch_access(monkeypatch, team=_team("T2", "W2"), member=None, ws_role=None)
    monkeypatch.setattr(en, "_check_entry_date", lambda d: d)

    with pytest.raises(BusinessError, match="不是该团队成员"):
        en.list_my_entries(None, "openid-a", {"teamId": "T2", "limit": 10})
    with pytest.raises(BusinessError, match="不是该团队成员"):
        en.save_entry(None, "openid-a", {"payload": {
            "team_id": "T2", "entry_date": TODAY, "template_id": "tpl_1",
        }})


def test_require_member_rejects_team_without_membership(monkeypatch):
    _patch_access(monkeypatch, team=_team("T2", "W2"), member=None, ws_role=None)
    with pytest.raises(BusinessError, match="不是该团队成员"):
        common.require_member(None, "openid-a", "T2")
    with pytest.raises(BusinessError, match="不是该团队成员"):
        common.require_writer(None, "openid-a", "T2")


# ---------------------------------------------------------------- 2. 空间 owner 非团队成员

def test_space_owner_without_team_row_gets_context(monkeypatch):
    """空间 owner 不是团队成员时，上下文 member=None 但仍可读写管理。"""
    _patch_access(monkeypatch, team=_team(), member=None, ws_role="owner")

    ctx = common.require_manager(None, "openid-admin", "T1")
    assert ctx["member"] is None
    assert ctx["is_team_member"] is False
    assert ctx["workspace_id"] == "W1"
    assert ctx["effective_role"] == "owner"
    assert common.is_manager(ctx) is True


def test_create_draft_by_space_owner_uses_uid_and_workspace(monkeypatch):
    from app.handlers import templates as tpl

    _patch_access(monkeypatch, team=_team(), member=None, ws_role="owner")
    captured = {}
    monkeypatch.setattr(tpl.db, "insert",
                        lambda conn, table, data: captured.update(data) or "tpl-new")
    monkeypatch.setattr(tpl.db, "now_iso", lambda: "2026-11-15T00:00:00.000Z")
    monkeypatch.setattr(tpl, "audit", lambda *a, **k: None)

    row = tpl.create_draft(None, "openid-admin", {"payload": {
        "team_id": "T1", "template_id": "tpl_1", "version": 1, "name": "日报",
    }})
    assert captured["created_by"] == "openid-admin"
    assert captured["workspace_id"] == "W1"
    assert row["id"] == "tpl-new"


def test_list_members_by_space_owner(monkeypatch):
    from app.handlers import members as mb

    _patch_access(monkeypatch, team=_team(), member=None, ws_role="owner")
    monkeypatch.setattr(mb.db, "query", lambda *a, **k: [{"id": "m1", "name": "张三"}])

    rows = mb.list_members(None, "openid-admin", {"teamId": "T1"})
    assert rows == [{"id": "m1", "name": "张三"}]


# ---------------------------------------------------------------- 3. owner 保护与自保护

def test_space_admin_cannot_touch_team_owner(monkeypatch):
    from app.handlers import members as mb

    target = _member("openid-owner", role="owner")
    _patch_access(monkeypatch, team=_team(), member=None, ws_role="admin")
    monkeypatch.setattr(mb.db, "get_doc", lambda *a, **k: dict(target))

    with pytest.raises(BusinessError, match="需要负责人权限"):
        mb.update_member(None, "openid-admin", {"id": target["id"], "patch": {"name": "改名"}})
    with pytest.raises(BusinessError, match="需要负责人权限"):
        mb.remove_member(None, "openid-admin", {"id": target["id"]})


def test_self_protection_uses_uid(monkeypatch):
    from app.handlers import members as mb

    target = _member("openid-owner", role="member")
    _patch_access(monkeypatch, team=_team(), member=target, ws_role="owner")
    monkeypatch.setattr(mb.db, "get_doc", lambda *a, **k: dict(target))
    monkeypatch.setattr(mb.db, "now_iso", lambda: "2026-11-15T00:00:00.000Z")

    with pytest.raises(BusinessError, match="不能停用自己"):
        mb.update_member(None, "openid-owner",
                         {"id": target["id"], "patch": {"status": "disabled"}})
    with pytest.raises(BusinessError, match="不能移除自己"):
        mb.remove_member(None, "openid-owner", {"id": target["id"]})


# ---------------------------------------------------------------- 4. 只读角色

def test_viewer_can_read_but_not_write(monkeypatch):
    viewer = _member("openid-v", role="viewer")
    _patch_access(monkeypatch, team=_team(), member=viewer, ws_role=None)

    ctx = common.require_member(None, "openid-v", "T1")
    assert ctx["effective_role"] == "viewer"
    assert org.can_read_team(ctx) is True
    assert org.can_write_team(ctx) is False
    with pytest.raises(BusinessError, match="只读成员"):
        common.require_writer(None, "openid-v", "T1")


def test_viewer_rejected_by_write_actions(monkeypatch):
    from app.handlers import entries as en
    from app.handlers import tasks as tk
    from app.handlers import templates as tpl

    viewer = _member("openid-v", role="viewer")
    _patch_access(monkeypatch, team=_team(), member=viewer, ws_role=None)
    monkeypatch.setattr(en, "_check_entry_date", lambda d: d)

    with pytest.raises(BusinessError, match="只读成员"):
        en.save_entry(None, "openid-v", {"payload": {
            "team_id": "T1", "entry_date": TODAY, "template_id": "tpl_1",
        }})
    # 只读成员不具备管理权限，不能建模板/建任务
    with pytest.raises(BusinessError, match="需要管理员权限"):
        tpl.create_draft(None, "openid-v", {"payload": {
            "team_id": "T1", "template_id": "tpl_1", "version": 1, "name": "日报",
        }})
    with pytest.raises(BusinessError, match="需要管理员权限"):
        tk.create_report_task(None, "openid-v", {
            "teamId": "T1",
            "payload": {"title": "任务", "start_date": TODAY},
        })


def test_viewer_can_read_templates_and_own_entry(monkeypatch):
    from app.handlers import entries as en
    from app.handlers import templates as tpl

    viewer = _member("openid-v", role="viewer")
    _patch_access(monkeypatch, team=_team(), member=viewer, ws_role=None)
    monkeypatch.setattr(tpl.db, "query",
                        lambda *a, **k: [{"id": "tpl-1", "fields": [], "scope": {}}])
    monkeypatch.setattr(en.db, "one", lambda *a, **k: None)

    assert tpl.list_templates(None, "openid-v", {"teamId": "T1"})[0]["id"] == "tpl-1"
    assert en.get_my_entry(None, "openid-v", {"teamId": "T1", "date": TODAY}) is None


# ---------------------------------------------------------------- 5. 一人两空间

def test_list_my_workspaces_returns_two_spaces(monkeypatch):
    from app.handlers import workspaces as ws

    monkeypatch.setattr(org, "workspaces_of_user", lambda conn, uid: [
        {"id": "W1", "workspace_code": "W1", "name": "A 空间",
         "workspace_role": "owner", "config": {}},
        {"id": "W2", "workspace_code": "W2", "name": "B 空间",
         "workspace_role": "member", "config": {}},
    ])
    monkeypatch.setattr(org, "teams_in_workspace",
                        lambda conn, wid: [{"team_id": "T1", "name": "A 队",
                                            "workspace_id": wid}])
    monkeypatch.setattr(org, "teams_of_user_in_workspace",
                        lambda conn, uid, wid: [{"team_id": "T2", "name": "B 队",
                                                 "workspace_id": wid,
                                                 "member_role": "member"}])

    out = ws.list_my_workspaces(None, "openid-x", {})
    assert [s["role"] for s in out] == ["owner", "member"]
    assert [t["team_id"] for t in out[0]["teams"]] == ["T1"]
    assert [t["team_id"] for t in out[1]["teams"]] == ["T2"]


def test_switch_workspace_returns_role_and_team(monkeypatch):
    from app.handlers import workspaces as ws

    team = _team("T2", "W2")
    monkeypatch.setattr(org, "team_context", lambda conn, tid: team)
    monkeypatch.setattr(org, "get_workspace", lambda conn, wid: {
        "id": "W2", "workspace_code": "W2", "name": "B 空间",
        "owner_uid": "openid-owner", "config": {},
    })
    monkeypatch.setattr(org, "workspace_membership", lambda conn, uid, wid: {
        "id": "wm-1", "workspace_id": "W2", "user_id": uid, "name": "我",
        "role": "member", "status": "active", "joined_at": "2026-11-01T00:00:00.000Z",
    })
    monkeypatch.setattr(org, "teams_in_workspace", lambda conn, wid: [team])
    monkeypatch.setattr(org, "teams_of_user_in_workspace", lambda conn, uid, wid: [team])
    monkeypatch.setattr(org, "departments_of", lambda conn, wid: [])
    monkeypatch.setattr(ws, "find_member_by_uid",
                        lambda conn, uid, tid=None: _member(uid, "member", "T2"))
    monkeypatch.setattr(ws, "team_access", lambda conn, uid, tid: {
        "effective_role": "member", "workspace_id": "W2", "workspace_role": "member",
    })

    out = ws.switch_workspace(None, "openid-x", {"teamId": "T2"})
    assert out["workspace"]["id"] == "W2"
    assert out["workspaceRole"] == "member"
    assert out["team"]["owner_name"] == "张三"
    assert out["team"]["team_id"] == "T2"
    assert out["member"]["workspace_role"] == "member"


# ---------------------------------------------------------------- 6. 部门层级

def test_department_depth_limit():
    assert org.validate_new_department_depth(None) == 1
    assert org.validate_new_department_depth({"id": "d2", "depth": 2}) == 3
    with pytest.raises(ValueError, match="最多 3 级"):
        org.validate_new_department_depth({"id": "d3", "depth": 3})


def test_move_department_rejects_descendant_and_overflow():
    rows = [
        {"id": "d1", "parent_id": None, "depth": 1},
        {"id": "d2", "parent_id": "d1", "depth": 2},
        {"id": "d3", "parent_id": "d2", "depth": 3},
        {"id": "d4", "parent_id": None, "depth": 1},
    ]
    with pytest.raises(ValueError, match="自己的下级"):
        org.validate_move_department(rows, rows[0], rows[2])
    with pytest.raises(ValueError, match="超过 3 级"):
        org.validate_move_department(rows, rows[0], rows[3])


def _patch_department_deps(monkeypatch, ws, duplicate):
    monkeypatch.setattr(ws, "require_workspace_role", lambda *a, **k: (
        {"id": "W1", "workspace_code": "W1", "name": "A 空间", "config": {}},
        {"id": "wm-1", "role": "owner"},
    ))
    monkeypatch.setattr(ws.db, "one", lambda *a, **k: duplicate)
    inserted = []
    monkeypatch.setattr(ws.db, "insert",
                        lambda conn, table, data: inserted.append((table, data)) or "d-new")
    monkeypatch.setattr(ws.db, "get_doc", lambda *a, **k: {
        "id": "d-new", "workspace_id": "W1", "name": "研发", "depth": 1,
    })
    monkeypatch.setattr(ws, "audit", lambda *a, **k: None)
    return inserted


def test_duplicate_department_name_rejected(monkeypatch):
    from app.handlers import workspaces as ws

    _patch_department_deps(monkeypatch, ws, {"id": "d-exist"})
    with pytest.raises(BusinessError, match="同级部门名称已存在"):
        ws.create_department(None, "openid-x", {"workspaceId": "W1", "name": "研发"})


def test_same_name_allowed_in_other_workspace(monkeypatch):
    """唯一键含 workspace_id：另一空间无同名冲突时允许创建。"""
    from app.handlers import workspaces as ws

    inserted = _patch_department_deps(monkeypatch, ws, None)
    out = ws.create_department(None, "openid-x", {"workspaceId": "W1", "name": "研发"})
    assert inserted[0][0] == "departments"
    assert inserted[0][1]["workspace_id"] == "W1"
    assert out["id"] == "d-new"


def test_create_department_rejects_fourth_level(monkeypatch):
    from app.handlers import workspaces as ws

    _patch_department_deps(monkeypatch, ws, None)
    monkeypatch.setattr(org, "get_department", lambda conn, did: {
        "id": "d3", "workspace_id": "W1", "depth": 3, "status": "active",
    })
    with pytest.raises(BusinessError, match="最多 3 级"):
        ws.create_department(None, "openid-x", {
            "workspaceId": "W1", "name": "第四级", "parentId": "d3",
        })


# ---------------------------------------------------------------- 7. 重新加入

def test_join_second_workspace_adds_space_member(monkeypatch):
    from app.handlers import teams as tm

    team = _team("T2", "W2")
    monkeypatch.setattr(tm, "find_team_by_id", lambda *a, **k: team)
    monkeypatch.setattr(tm.db, "one", lambda *a, **k: None)
    monkeypatch.setattr(tm.db, "insert", lambda *a, **k: "m-new")
    monkeypatch.setattr(tm.db, "now_iso", lambda: "2026-11-15T00:00:00.000Z")
    monkeypatch.setattr(tm, "audit", lambda *a, **k: None)
    space = {}
    monkeypatch.setattr(
        tm.org, "ensure_workspace_member",
        lambda conn, wid, uid, name, role="member": space.update(
            {"workspace_id": wid, "user_id": uid, "role": role}),
    )

    tm.join_team(None, "openid-x", {"teamId": "T2", "memberName": "李四"})
    assert space == {"workspace_id": "W2", "user_id": "openid-x", "role": "member"}


def test_join_team_reactivates_left_row_without_insert(monkeypatch):
    """主动退出后重新加入：复用原行，避免撞 uk_members_team_user。"""
    from app.handlers import teams as tm

    mine = _member("openid-x", "member", "T2", status="disabled",
                   left_at="2026-11-01T00:00:00.000Z")
    monkeypatch.setattr(tm, "find_team_by_id", lambda *a, **k: _team("T2", "W2"))
    monkeypatch.setattr(tm.db, "one", lambda *a, **k: dict(mine))
    updates, inserts = [], []
    monkeypatch.setattr(tm.db, "update",
                        lambda conn, table, doc_id, patch: updates.append((table, doc_id, patch)))
    monkeypatch.setattr(tm.db, "insert", lambda *a, **k: inserts.append(a) or "new")
    monkeypatch.setattr(tm.db, "now_iso", lambda: "2026-11-15T00:00:00.000Z")
    monkeypatch.setattr(tm, "audit", lambda *a, **k: None)
    monkeypatch.setattr(tm.org, "ensure_workspace_member", lambda *a, **k: {})

    out = tm.join_team(None, "openid-x", {"teamId": "T2", "memberName": "新名"})
    assert not inserts
    assert updates[0][1] == mine["id"]
    assert updates[0][2] == {"status": "active", "left_at": None, "name": "新名"}
    assert out["status"] == "active"
    assert out["left_at"] is None


# ---------------------------------------------------------------- 8. 迁移脚本

MIGRATE = (SQL_DIR / "migrate_p4_workspaces.sql").read_text("utf-8")
ROLLBACK = (SQL_DIR / "migrate_p4_rollback.sql").read_text("utf-8")
SCHEMA = (SQL_DIR / "schema.sql").read_text("utf-8")


def test_generated_column_uses_mysql8_order():
    """生成列的 NOT NULL 必须在 STORED 之后，否则 MySQL 8 直接语法报错。"""
    for sql in (SCHEMA, MIGRATE):
        assert "GENERATED ALWAYS AS" in sql
        assert "STORED NOT NULL" in sql
        assert "NOT NULL GENERATED" not in sql


def test_migration_creates_org_tables_and_is_guarded():
    for table in ("workspaces", "departments", "workspace_members"):
        assert "CREATE TABLE IF NOT EXISTS `%s`" % table in MIGRATE
    # MySQL 8 无 ADD COLUMN IF NOT EXISTS，必须用 information_schema + PREPARE 守卫
    assert MIGRATE.count("information_schema.COLUMNS") >= 8
    assert "PREPARE stmt FROM @ddl" in MIGRATE
    assert "ON DUPLICATE KEY UPDATE" in MIGRATE
    # INSERT ... SELECT 的 ODKU 必须限定目标表，否则 role 列歧义（MySQL 1052）
    assert "`workspace_members`.`role` = CASE" in MIGRATE


def test_migration_backfills_teams_and_child_tables():
    assert "CONCAT('W', t.`team_id`)" in MIGRATE
    assert "SUBSTR(SHA2(CONCAT('ws:', t.`team_id`)" in MIGRATE
    for table in ("form_templates", "daily_entries", "report_tasks", "audit_logs"):
        assert "UPDATE `%s`" % table in MIGRATE


def test_migration_has_self_checks():
    for check in ("teams_without_workspace", "form_templates_null_workspace",
                  "daily_entries_null_workspace", "report_tasks_null_workspace",
                  "audit_logs_null_workspace", "workspace_members_distinct",
                  "departments_depth_over_3"):
        assert check in MIGRATE


def test_rollback_documents_loss_and_drops_org_tables():
    assert "有损" in ROLLBACK
    for table in ("workspace_members", "departments", "workspaces"):
        assert "DROP TABLE IF EXISTS `%s`" % table in ROLLBACK
    for table in ("teams", "members", "form_templates", "daily_entries",
                  "report_tasks", "audit_logs"):
        assert "ALTER TABLE `%s` DROP COLUMN" % table in ROLLBACK
