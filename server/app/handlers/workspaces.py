"""工作空间与部门（P4）。

action：listMyWorkspaces / switchWorkspace / createWorkspace / updateWorkspace /
        listWorkspaceMembers / updateWorkspaceMember /
        listDepartments / createDepartment / updateDepartment

权限：
- 空间管理（改名、成员、部门）要求空间 owner/admin；
- 部门树读取对空间成员开放；
- 切换空间只校验「是空间成员」，返回当前空间、团队、成员与部门树。
"""
from .. import db
from ..services import org
from .common import BusinessError, audit, find_member_by_uid, require_workspace_role, team_access

_MAX_NAME = 128


# ---------------------------------------------------------------------------
# 公共序列化
# ---------------------------------------------------------------------------
def _workspace_public(ws: dict, role=None) -> dict:
    return {
        "id": ws.get("id"),
        "workspace_code": ws.get("workspace_code"),
        "name": ws.get("name"),
        "owner_uid": ws.get("owner_uid"),
        "config": ws.get("config") or {},
        "created_at": ws.get("created_at"),
        "role": role or ws.get("workspace_role"),
    }


def _team_public(team: dict) -> dict:
    return {
        "team_id": team.get("team_id"),
        "name": team.get("name"),
        "workspace_id": team.get("workspace_id"),
        "department_id": team.get("department_id"),
        "role": team.get("member_role"),
        "created_at": team.get("created_at"),
    }


def _member_view(row: dict, workspace_id: str, role: str, effective: str,
                 is_team_member: bool) -> dict:
    return {
        "id": row.get("id"),
        "team_id": row.get("team_id"),
        "user_id": row.get("user_id"),
        "name": row.get("name"),
        "role": row.get("role"),
        "status": row.get("status"),
        "department_id": row.get("department_id"),
        "joined_at": row.get("joined_at"),
        "workspace_id": workspace_id,
        "workspace_role": role,
        "effective_role": effective,
        "is_team_member": is_team_member,
    }


def _require_space_member(conn, uid, workspace_id):
    workspace = org.get_workspace(conn, workspace_id)
    if not workspace:
        raise BusinessError("工作空间不存在")
    membership = org.workspace_membership(conn, uid, workspace_id)
    if not membership or membership.get("status") != "active":
        raise BusinessError("你不是该工作空间成员")
    return workspace, membership


# ---------------------------------------------------------------------------
# 空间列表与切换
# ---------------------------------------------------------------------------
def list_my_workspaces(conn, uid, p):
    spaces = org.workspaces_of_user(conn, uid)
    out = []
    for ws in spaces:
        role = ws.get("workspace_role") or "member"
        if org.is_workspace_manager(role):
            teams = org.teams_in_workspace(conn, ws["id"])
        else:
            teams = org.teams_of_user_in_workspace(conn, uid, ws["id"])
        out.append({
            "workspace": _workspace_public(ws, role),
            "role": role,
            "teams": [_team_public(t) for t in teams],
        })
    return out


def switch_workspace(conn, uid, p):
    team_id = str(p.get("teamId") or "").strip() or None
    workspace_id = str(p.get("workspaceId") or "").strip() or None

    team = None
    if team_id:
        team = org.team_context(conn, team_id)
        if not team:
            raise BusinessError("团队不存在")
        workspace_id = team.get("workspace_id")
        if not workspace_id:
            raise BusinessError("团队尚未归属工作空间，请先执行迁移")
    elif not workspace_id:
        spaces = org.workspaces_of_user(conn, uid)
        if not spaces:
            return {"workspace": None, "workspaceRole": None, "team": None,
                    "member": None, "teams": [], "departments": []}
        workspace_id = spaces[0]["id"]

    workspace, membership = _require_space_member(conn, uid, workspace_id)
    role = membership.get("role") or "member"

    all_teams = org.teams_in_workspace(conn, workspace_id)
    my_teams = org.teams_of_user_in_workspace(conn, uid, workspace_id)
    visible = all_teams if org.is_workspace_manager(role) else my_teams

    if team is None:
        team = my_teams[0] if my_teams else (all_teams[0] if all_teams and org.is_workspace_manager(role) else None)
        team_id = team.get("team_id") if team else None
    elif team.get("workspace_id") != workspace_id:
        raise BusinessError("团队不属于该工作空间")

    member = None
    if team_id:
        row = find_member_by_uid(conn, uid, team_id)
        ctx = team_access(conn, uid, team_id)
        if row and not row.get("left_at"):
            member = _member_view(row, workspace_id, role, ctx.get("effective_role"), True)
        elif org.is_workspace_manager(role):
            # 空间管理员但非团队成员：返回带标记的视图对象，仅用于页面展示，不参与服务端权限判断
            virtual = {
                "id": None, "team_id": team_id, "user_id": uid,
                "name": membership.get("name"), "role": "manager", "status": "active",
                "department_id": team.get("department_id") if team else None,
                "joined_at": membership.get("joined_at"),
            }
            member = _member_view(virtual, workspace_id, role,
                                  ctx.get("effective_role"), False)
            member["virtual"] = True
        elif row is None:
            member = None

    return {
        "workspace": _workspace_public(workspace, role),
        "workspaceRole": role,
        "team": _team_public(team) if team else None,
        "member": member,
        "teams": [_team_public(t) for t in visible],
        "departments": org.department_tree(org.departments_of(conn, workspace_id)),
    }


# ---------------------------------------------------------------------------
# 空间 CRUD
# ---------------------------------------------------------------------------
def create_workspace(conn, uid, p):
    name = str(p.get("name") or "").strip()[:_MAX_NAME]
    member_name = str(p.get("memberName") or "").strip()[:64] or "负责人"
    if not name:
        raise BusinessError("请输入工作空间名称")

    created = org.create_workspace_record(conn, uid, name, member_name)
    workspace = created["workspace"]
    team = None
    team_name = str(p.get("teamName") or "").strip()[:_MAX_NAME]
    if team_name:
        from .teams import create_team
        result = create_team(conn, uid, {
            "name": team_name,
            "memberName": member_name,
            "workspaceId": workspace["id"],
        })
        team = result["team"]

    audit(conn, uid, None, "workspace_create", "workspaces", workspace["id"],
          {"name": name, "team": team_name or None}, workspace_id=workspace["id"])
    return {
        "workspace": _workspace_public(workspace, "owner"),
        "role": "owner",
        "team": team,
        "teams": [team] if team else [],
        "departments": [],
    }


def update_workspace(conn, uid, p):
    workspace, membership = require_workspace_role(conn, uid, p.get("workspaceId"))
    patch = {}
    if "name" in p:
        name = str(p.get("name") or "").strip()[:_MAX_NAME]
        if not name:
            raise BusinessError("请输入工作空间名称")
        patch["name"] = name
    if "config" in p:
        incoming = p.get("config")
        if not isinstance(incoming, dict):
            raise BusinessError("参数错误")
        merged = dict(workspace.get("config") or {})
        for k, v in incoming.items():
            if k in ("memberSeeTeamTotal",) and isinstance(v, bool):
                merged[k] = v
        patch["config"] = merged
    if patch:
        db.update(conn, "workspaces", workspace["id"], patch)
        audit(conn, uid, None, "workspace_update", "workspaces", workspace["id"],
              {"patch": list(patch.keys()), "by": membership.get("role")},
              workspace_id=workspace["id"])
    updated = dict(workspace, **patch)
    return _workspace_public(updated, membership.get("role"))


# ---------------------------------------------------------------------------
# 空间成员
# ---------------------------------------------------------------------------
def list_workspace_members(conn, uid, p):
    workspace, _ = require_workspace_role(conn, uid, p.get("workspaceId"))
    return org.list_workspace_members(conn, workspace["id"])


def update_workspace_member(conn, uid, p):
    workspace, me = require_workspace_role(conn, uid, p.get("workspaceId"))
    target = db.get_doc(conn, "workspace_members", p.get("id"))
    if not target or target.get("workspace_id") != workspace["id"]:
        raise BusinessError("成员不存在")

    patch = p.get("patch") or {}
    if not isinstance(patch, dict):
        raise BusinessError("参数错误")

    data = {}
    if "status" in patch:
        if patch["status"] not in ("active", "disabled"):
            raise BusinessError("状态不合法")
        if target.get("user_id") == uid and patch["status"] == "disabled":
            raise BusinessError("不能停用自己")
        data["status"] = patch["status"]
    if "name" in patch and str(patch["name"]).strip():
        data["name"] = str(patch["name"]).strip()[:64]
    if "role" in patch and patch["role"] != target.get("role"):
        if me.get("role") != "owner":
            raise BusinessError("只有空间所有者可以调整角色")
        if target.get("user_id") == uid:
            raise BusinessError("不能修改自己的角色")
        if patch["role"] not in org.WORKSPACE_ROLES:
            raise BusinessError("角色不合法")
        data["role"] = patch["role"]
    if not data:
        return target
    db.update(conn, "workspace_members", target["id"], data)
    audit(conn, uid, None, "workspace_member_update", "workspace_members",
          target["id"], dict(data, by=me.get("role")), workspace_id=workspace["id"])
    return dict(target, **data)


# ---------------------------------------------------------------------------
# 部门
# ---------------------------------------------------------------------------
def _descendants(rows, root_id):
    out = []
    frontier = [root_id]
    while frontier:
        current = frontier.pop()
        for row in rows:
            if row.get("parent_id") == current:
                out.append(row)
                frontier.append(row["id"])
    return out


def list_departments(conn, uid, p):
    workspace, _ = _require_space_member(conn, uid, p.get("workspaceId"))
    return org.department_tree(org.departments_of(conn, workspace["id"]))


def create_department(conn, uid, p):
    workspace, me = require_workspace_role(conn, uid, p.get("workspaceId"))
    name = str(p.get("name") or "").strip()[:_MAX_NAME]
    if not name:
        raise BusinessError("请输入部门名称")

    parent_id = str(p.get("parentId") or "").strip() or None
    parent = None
    if parent_id:
        parent = org.get_department(conn, parent_id)
        if not parent or parent.get("workspace_id") != workspace["id"]:
            raise BusinessError("上级部门不存在或不属于该工作空间")
    try:
        depth = org.validate_new_department_depth(parent)
    except ValueError as exc:
        raise BusinessError(str(exc))

    duplicate = db.one(
        conn,
        "SELECT id FROM `departments` WHERE workspace_id = %s AND parent_key = %s AND name = %s LIMIT 1",
        (workspace["id"], parent_id or "", name),
    )
    if duplicate:
        raise BusinessError("同级部门名称已存在")

    leader_uid = str(p.get("leaderUid") or "").strip() or None
    if leader_uid:
        _assert_space_member(conn, workspace["id"], leader_uid)

    dept_id = db.insert(conn, "departments", {
        "workspace_id": workspace["id"],
        "parent_id": parent_id,
        "name": name,
        "depth": depth,
        "leader_uid": leader_uid,
        "status": "active",
        "created_at": db.now_iso(),
    })
    audit(conn, uid, None, "department_create", "departments", dept_id,
          {"name": name, "parentId": parent_id, "depth": depth, "by": me.get("role")},
          workspace_id=workspace["id"])
    return db.get_doc(conn, "departments", dept_id)


def update_department(conn, uid, p):
    workspace, me = require_workspace_role(conn, uid, p.get("workspaceId"))
    dept = db.get_doc(conn, "departments", p.get("id"))
    if not dept or dept.get("workspace_id") != workspace["id"]:
        raise BusinessError("部门不存在")

    rows = org.departments_of(conn, workspace["id"])
    index = {r["id"]: r for r in rows}
    data = {}

    new_parent_id = dept.get("parent_id")
    if "parentId" in p:
        new_parent_id = str(p.get("parentId") or "").strip() or None
        new_parent = index.get(new_parent_id) if new_parent_id else None
        if new_parent_id and not new_parent:
            raise BusinessError("上级部门不存在或不属于该工作空间")
        if new_parent_id != dept.get("parent_id"):
            try:
                new_depth = org.validate_move_department(rows, dept, new_parent)
            except ValueError as exc:
                raise BusinessError(str(exc))
            data["parent_id"] = new_parent_id
            data["depth"] = new_depth
            descendants = _descendants(rows, dept["id"])
            delta = new_depth - int(dept.get("depth") or 1)
            for child in descendants:
                db.update(conn, "departments", child["id"],
                          {"depth": int(child.get("depth") or 1) + delta})

    if "name" in p:
        name = str(p.get("name") or "").strip()[:_MAX_NAME]
        if not name:
            raise BusinessError("请输入部门名称")
        duplicate = db.one(
            conn,
            "SELECT id FROM `departments` WHERE workspace_id = %s AND parent_key = %s "
            "AND name = %s AND id <> %s LIMIT 1",
            (workspace["id"], new_parent_id or "", name, dept["id"]),
        )
        if duplicate:
            raise BusinessError("同级部门名称已存在")
        data["name"] = name

    if "leaderUid" in p:
        leader_uid = str(p.get("leaderUid") or "").strip() or None
        if leader_uid:
            _assert_space_member(conn, workspace["id"], leader_uid)
        data["leader_uid"] = leader_uid

    if "status" in p:
        if p["status"] not in ("active", "archived"):
            raise BusinessError("状态不合法")
        data["status"] = p["status"]

    if not data:
        return dept
    db.update(conn, "departments", dept["id"], data)
    audit(conn, uid, None, "department_update", "departments", dept["id"],
          dict(data, by=me.get("role")), workspace_id=workspace["id"])
    return dict(dept, **data)


def _assert_space_member(conn, workspace_id, uid):
    membership = org.workspace_membership(conn, uid, workspace_id)
    if not membership or membership.get("status") != "active":
        raise BusinessError("负责人必须是该工作空间的成员")


HANDLERS = {
    "listMyWorkspaces": list_my_workspaces,
    "switchWorkspace": switch_workspace,
    "createWorkspace": create_workspace,
    "updateWorkspace": update_workspace,
    "listWorkspaceMembers": list_workspace_members,
    "updateWorkspaceMember": update_workspace_member,
    "listDepartments": list_departments,
    "createDepartment": create_department,
    "updateDepartment": update_department,
}
