"""成员：getMyMember / listMembers / updateMember / removeMember

P4：
- getMyMember 支持可选 teamId；返回值附加 workspace_id / workspace_role / effective_role；
- 成员角色扩展 owner|manager|member|viewer；
- updateMember 支持调整成员所属部门（同工作空间）；
- removeMember 改为软移除（status=disabled + left_at），重新加入时复用原行。
"""
from .. import db
from ..services import org
from .common import BusinessError, audit, find_member_by_uid, require_manager, team_access


def _augment(conn, member):
    if not member:
        return None
    ctx = team_access(conn, member["user_id"], member["team_id"])
    out = dict(member)
    out["workspace_id"] = ctx.get("workspace_id")
    out["workspace_role"] = ctx.get("workspace_role")
    out["effective_role"] = ctx.get("effective_role")
    return out


def get_my_member(conn, uid, p):
    team_id = str(p.get("teamId") or "").strip() or None
    member = find_member_by_uid(conn, uid, team_id)
    if not member:
        return None
    # 主动退出（有 left_at）视为不在团队，不报停用；被管理员停用才明确提示。
    if member.get("left_at"):
        return None
    if member.get("status") != "active":
        raise BusinessError("你已被管理员停用，请联系负责人启用")
    return _augment(conn, member)


def list_members(conn, uid, p):
    ctx = require_manager(conn, uid, p.get("teamId"))
    rows = db.query(
        conn,
        "SELECT * FROM `members` WHERE team_id = %s AND left_at IS NULL "
        "ORDER BY joined_at ASC LIMIT 1000",
        (ctx["team_id"],),
    )
    return db.rows_to_dicts(rows, "members")


def update_member(conn, uid, p):
    target = db.get_doc(conn, "members", p.get("id"))
    if not target:
        raise BusinessError("成员不存在")
    ctx = require_manager(conn, uid, target["team_id"])
    patch = p.get("patch") or {}
    if not isinstance(patch, dict):
        raise BusinessError("参数错误")
    if target.get("role") == "owner" and ctx.get("effective_role") != "owner":
        raise BusinessError("需要负责人权限")

    data = {}
    if "status" in patch:
        if patch["status"] not in ("active", "disabled"):
            raise BusinessError("状态不合法")
        if str(target.get("user_id")) == str(uid) and patch["status"] == "disabled":
            raise BusinessError("不能停用自己")
        data["status"] = patch["status"]
        data["left_at"] = None if patch["status"] == "active" else db.now_iso()
    if "name" in patch and str(patch["name"]).strip():
        data["name"] = str(patch["name"]).strip()[:64]
    if "role" in patch and patch["role"] != target["role"]:
        if ctx.get("effective_role") != "owner":
            raise BusinessError("只有负责人可以调整角色")
        if str(target.get("user_id")) == str(uid):
            raise BusinessError("不能修改自己的角色")
        if patch["role"] not in org.TEAM_ROLES:
            raise BusinessError("角色不合法")
        data["role"] = patch["role"]
    if "departmentId" in patch:
        dept_id = str(patch.get("departmentId") or "").strip() or None
        if dept_id:
            dept = org.get_department(conn, dept_id)
            if not dept or dept.get("workspace_id") != ctx.get("workspace_id"):
                raise BusinessError("部门不存在或不属于该工作空间")
        data["department_id"] = dept_id

    if not data:
        return target
    db.update(conn, "members", p.get("id"), data)
    audit(conn, uid, target["team_id"], "member_update", "members", p.get("id"),
          dict(data, by=ctx.get("effective_role")), workspace_id=ctx.get("workspace_id"))
    return dict(target, **data)


def remove_member(conn, uid, p):
    target = db.get_doc(conn, "members", p.get("id"))
    if not target:
        raise BusinessError("成员不存在")
    ctx = require_manager(conn, uid, target["team_id"])
    if str(target.get("user_id")) == str(uid):
        raise BusinessError("不能移除自己")
    if target.get("role") == "owner" and ctx.get("effective_role") != "owner":
        raise BusinessError("需要负责人权限")
    db.update(conn, "members", p.get("id"), {
        "status": "disabled",
        "left_at": db.now_iso(),
    })
    audit(conn, uid, target["team_id"], "member_remove", "members",
          p.get("id"), {"name": target["name"]}, workspace_id=ctx.get("workspace_id"))
    return {"removed": p.get("id")}


HANDLERS = {
    "getMyMember": get_my_member,
    "listMembers": list_members,
    "updateMember": update_member,
    "removeMember": remove_member,
}
