"""业务处理器共享工具：权限校验、团队/成员查询、审计。

对应旧云函数 api/index.js 的 requireMember / requireManager / audit 等，
身份参数由 JWT 的 sub（openid）传入，客户端无法伪造。

P4 起权限返回「访问上下文」而非成员行，包含团队/空间/有效角色，
调用方一律用上下文里的 user_id / effective_role 做判断与写入。
"""
import secrets
from typing import Optional

from .. import db
from ..services import org


class BusinessError(Exception):
    """可安全展示给客户端的业务错误。"""


def is_manager(ctx: Optional[dict]) -> bool:
    """兼容两种入参：访问上下文（effective_role）或旧成员行（role）。"""
    if not ctx:
        return False
    if "effective_role" in ctx:
        return ctx.get("effective_role") in ("owner", "admin", "manager")
    return ctx.get("role") in ("manager", "owner")


def find_team_by_id(conn, team_id: str) -> Optional[dict]:
    return org.team_context(conn, team_id)


def find_member_by_uid(conn, uid: str, team_id: Optional[str] = None) -> Optional[dict]:
    if team_id:
        return db.one(
            conn,
            "SELECT * FROM `members` WHERE team_id = %s AND user_id = %s LIMIT 1",
            (team_id, uid),
        )
    # 确定性排序：即使历史数据存在多团队记录，也始终取最早加入的那一条
    return db.one(
        conn,
        "SELECT * FROM `members` WHERE user_id = %s ORDER BY joined_at ASC, id ASC LIMIT 1",
        (uid,),
    )


def team_access(conn, uid: str, team_id: Optional[str]) -> dict:
    """组装团队访问上下文（不做放行判断）。"""
    team = org.team_context(conn, team_id)
    if not team:
        raise BusinessError("团队不存在")
    ws_id = team.get("workspace_id")
    ws_role = org.workspace_role(conn, uid, ws_id) if ws_id else None
    member = find_member_by_uid(conn, uid, team_id)
    is_team_member = bool(member and member.get("status") == "active")
    dept_leader = org.is_department_leader(conn, uid, ws_id, team.get("department_id"))
    return {
        "team": team,
        "member": member,
        "membership_id": member.get("id") if member else None,
        "user_id": uid,
        "team_id": team_id,
        "workspace_id": ws_id,
        "workspace_role": ws_role,
        "effective_role": org.effective_role(member, ws_role, dept_leader),
        "is_team_member": is_team_member,
        "is_department_leader": dept_leader,
    }


def require_member(conn, uid: str, team_id: str) -> dict:
    """读权限：团队成员，或空间 owner/admin，或团队所属部门的上级负责人。"""
    ctx = team_access(conn, uid, team_id)
    if not org.can_read_team(ctx):
        raise BusinessError("你不是该团队成员或已被停用")
    return ctx


def require_manager(conn, uid: str, team_id: str) -> dict:
    """管理权限：团队 owner/manager，或空间 owner/admin，或部门负责人。"""
    ctx = require_member(conn, uid, team_id)
    if not org.can_manage_team(ctx):
        raise BusinessError("需要管理员权限")
    return ctx


def require_writer(conn, uid: str, team_id: str) -> dict:
    """写权限：读权限之上排除只读角色。"""
    ctx = require_member(conn, uid, team_id)
    if not org.can_write_team(ctx):
        raise BusinessError("只读成员不能进行此操作")
    return ctx


def require_workspace_role(conn, uid: str, workspace_id: Optional[str],
                           roles=org.WORKSPACE_MANAGER_ROLES):
    """校验空间级权限，返回 (workspace, membership)。"""
    workspace = org.get_workspace(conn, workspace_id)
    if not workspace:
        raise BusinessError("工作空间不存在")
    membership = org.workspace_membership(conn, uid, workspace_id)
    if not membership or membership.get("status") != "active":
        raise BusinessError("你不是该工作空间成员")
    if roles and membership.get("role") not in roles:
        raise BusinessError("需要工作空间管理员权限")
    return workspace, membership


def audit(conn, uid: str, team_id: Optional[str], action: str,
          target_type=None, target_id=None, detail=None,
          workspace_id: Optional[str] = None) -> None:
    """审计失败不阻断主流程；空间级操作可只传 workspace_id。"""
    try:
        if not workspace_id and team_id:
            team = org.team_context(conn, team_id)
            workspace_id = team.get("workspace_id") if team else None
        db.insert(conn, "audit_logs", {
            "team_id": team_id,
            "workspace_id": workspace_id,
            "actor": uid,
            "action": action,
            "target_type": target_type,
            "target_id": str(target_id) if target_id else None,
            "detail": detail,
            "created_at": db.now_iso(),
        })
    except Exception:
        pass


def gen_team_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "T" + "".join(secrets.choice(alphabet) for _ in range(6))


def require_date(value, field: str = "日期") -> str:
    import re
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise BusinessError(f"{field}格式不正确")
    return value
