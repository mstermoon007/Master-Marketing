"""团队：createTeam / findTeam / joinTeam / getTeam / updateTeamConfig

P4 起一个 openid 可属于多个工作空间与团队：
- createTeam 未指定 workspaceId 时，自动创建「团队名 工作空间」，保证每个团队都有空间；
- createTeam 指定 workspaceId 时，要求当前用户是该空间 owner/admin；
- joinTeam 自动补空间成员记录，角色只升不降；
- 同一团队内仍按 uk_members_team_user 保证唯一，重复加入返回已有成员。
"""
from .. import db
from ..services import org
from .common import (BusinessError, audit, find_team_by_id, gen_team_code,
                     require_manager, require_member, require_workspace_role)


def _validate_department(conn, workspace_id: str, department_id):
    if not department_id:
        return None
    dept = org.get_department(conn, department_id)
    if not dept or dept.get("workspace_id") != workspace_id:
        raise BusinessError("部门不存在或不属于该工作空间")
    if dept.get("status") != "active":
        raise BusinessError("该部门已归档")
    return department_id


def _pick_team_code(conn) -> str:
    for _ in range(5):
        candidate = gen_team_code()
        if not find_team_by_id(conn, candidate):
            return candidate
    raise BusinessError("生成团队编号失败，请重试")


def create_team(conn, uid, p):
    name = str(p.get("name") or "").strip()
    member_name = str(p.get("memberName") or "").strip() or "负责人"
    if not name:
        raise BusinessError("请输入团队名称")

    workspace_id = str(p.get("workspaceId") or "").strip()
    department_id = str(p.get("departmentId") or "").strip() or None
    team_code = _pick_team_code(conn)

    if workspace_id:
        workspace, _ = require_workspace_role(conn, uid, workspace_id)
        _validate_department(conn, workspace_id, department_id)
    else:
        created = org.create_workspace_record(
            conn, uid,
            name=f"{name} 工作空间",
            member_name=member_name,
            workspace_code=f"W{team_code}",
        )
        workspace = created["workspace"]
        workspace_id = workspace["id"]
        department_id = None

    now = db.now_iso()
    config = {"memberSeeTeamTotal": False}
    team_id = db.insert(conn, "teams", {
        "team_id": team_code,
        "workspace_id": workspace_id,
        "department_id": department_id,
        "name": name,
        "owner_uid": uid,
        "config": config,
        "created_at": now,
    })
    member_id = db.insert(conn, "members", {
        "team_id": team_code,
        "user_id": uid,
        "name": member_name,
        "role": "owner",
        "status": "active",
        "department_id": department_id,
        "joined_at": now,
    })
    org.ensure_workspace_member(conn, workspace_id, uid, member_name, role="owner")
    audit(conn, uid, team_code, "team_create", "teams", team_code,
          {"name": name, "workspace_id": workspace_id}, workspace_id=workspace_id)
    return {
        "team": {"id": team_id, "team_id": team_code, "name": name,
                 "workspace_id": workspace_id, "department_id": department_id,
                 "owner_uid": uid, "config": config, "created_at": now},
        "member": {"id": member_id, "team_id": team_code, "user_id": uid,
                   "name": member_name, "role": "owner", "status": "active",
                   "department_id": department_id, "joined_at": now},
    }


def find_team(conn, uid, p):
    return find_team_by_id(conn, str(p.get("code") or "").strip())


def join_team(conn, uid, p):
    team_code = str(p.get("teamId") or "").strip()
    member_name = str(p.get("memberName") or "").strip() or "成员"
    team = find_team_by_id(conn, team_code)
    if not team:
        raise BusinessError("邀请码不存在，请核对后重试")

    mine = db.one(
        conn,
        "SELECT * FROM `members` WHERE team_id = %s AND user_id = %s LIMIT 1",
        (team_code, uid),
    )
    now = db.now_iso()

    if mine:
        if mine.get("status") == "active" and not mine.get("left_at"):
            return mine
        if mine.get("status") != "active" and not mine.get("left_at"):
            raise BusinessError("你已在团队名单中但处于停用状态，请联系管理员启用")
        # 主动退出后重新加入：复用原行，避免撞 uk_members_team_user
        db.update(conn, "members", mine["id"], {
            "status": "active", "left_at": None, "name": member_name,
        })
        mine.update({"status": "active", "left_at": None, "name": member_name})
        _ensure_space_member(conn, team, uid, member_name)
        audit(conn, uid, team_code, "member_rejoin", "members", uid, {"name": member_name})
        return mine

    _ensure_space_member(conn, team, uid, member_name)
    member_id = db.insert(conn, "members", {
        "team_id": team_code,
        "user_id": uid,
        "name": member_name,
        "role": "member",
        "status": "active",
        "department_id": team.get("department_id"),
        "joined_at": now,
    })
    audit(conn, uid, team_code, "member_join", "members", uid, {"name": member_name})
    return {"id": member_id, "team_id": team_code, "user_id": uid,
            "name": member_name, "role": "member", "status": "active",
            "department_id": team.get("department_id"), "joined_at": now}


def _ensure_space_member(conn, team, uid, member_name):
    workspace_id = team.get("workspace_id")
    if not workspace_id:
        return
    try:
        org.ensure_workspace_member(conn, workspace_id, uid, member_name)
    except ValueError as exc:
        raise BusinessError(str(exc))


def get_team(conn, uid, p):
    ctx = require_member(conn, uid, p.get("teamId"))
    return ctx["team"]


def update_team_config(conn, uid, p):
    ctx = require_manager(conn, uid, p.get("teamId"))
    team = ctx["team"]

    merged = dict(team.get("config") or {})
    incoming = p.get("config") or {}
    if not isinstance(incoming, dict):
        raise BusinessError("参数错误")
    for k, v in incoming.items():
        if k in ("memberSeeTeamTotal",) and isinstance(v, bool):
            merged[k] = v
    db.update(conn, "teams", team["id"], {"config": merged})

    patch = {"config": merged}
    if "departmentId" in p:
        if not org.is_workspace_manager(ctx.get("workspace_role")):
            raise BusinessError("只有工作空间管理员可以调整团队所属部门")
        dept_id = str(p.get("departmentId") or "").strip() or None
        _validate_department(conn, ctx.get("workspace_id"), dept_id)
        db.update(conn, "teams", team["id"], {"department_id": dept_id})
        patch["department_id"] = dept_id

    audit(conn, uid, p.get("teamId"), "team_config_update", "teams",
          p.get("teamId"), {"config": merged, "by": ctx.get("effective_role")},
          workspace_id=ctx.get("workspace_id"))
    return {"id": team["id"], "team_id": team["team_id"], "name": team["name"],
            "workspace_id": ctx.get("workspace_id"),
            "department_id": patch.get("department_id", team.get("department_id")),
            "config": merged}


HANDLERS = {
    "createTeam": create_team,
    "findTeam": find_team,
    "joinTeam": join_team,
    "getTeam": get_team,
    "updateTeamConfig": update_team_config,
}
