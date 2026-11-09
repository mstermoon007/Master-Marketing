"""成员：getMyMember / listMembers / updateMember / removeMember"""
from .. import db
from .common import BusinessError, audit, find_member_by_uid, require_manager


def get_my_member(conn, uid, p):
    member = find_member_by_uid(conn, uid)
    # 停用成员在此明确报错：否则前端拿到 member 后 getTeam 才失败，
    # 页面会误判成「未登录」且退出按钮不可见，用户没有自助出口。
    if member and member.get("status") != "active":
        raise BusinessError("你已被管理员停用，请联系负责人启用")
    return member


def list_members(conn, uid, p):
    require_manager(conn, uid, p.get("teamId"))
    rows = db.query(
        conn,
        "SELECT * FROM `members` WHERE team_id = %s ORDER BY joined_at ASC LIMIT 1000",
        (p.get("teamId"),),
    )
    return db.rows_to_dicts(rows, "members")


def update_member(conn, uid, p):
    target = db.get_doc(conn, "members", p.get("id"))
    if not target:
        raise BusinessError("成员不存在")
    me = require_manager(conn, uid, target["team_id"])
    patch = p.get("patch") or {}
    if not isinstance(patch, dict):
        raise BusinessError("参数错误")

    data = {}
    if "status" in patch and patch["status"] in ("active", "disabled"):
        data["status"] = patch["status"]
    if "name" in patch and str(patch["name"]).strip():
        data["name"] = str(patch["name"]).strip()[:64]
    if "role" in patch and patch["role"] != target["role"]:
        if me["role"] != "owner":
            raise BusinessError("只有负责人可以调整角色")
        if str(target["id"]) == str(me["id"]):
            raise BusinessError("不能修改自己的角色")
        if patch["role"] not in ("member", "manager", "owner"):
            raise BusinessError("角色不合法")
        data["role"] = patch["role"]

    if not data:
        return target
    db.update(conn, "members", p.get("id"), data)
    audit(conn, uid, target["team_id"], "member_update", "members", p.get("id"), data)
    return dict(target, **data)


def remove_member(conn, uid, p):
    target = db.get_doc(conn, "members", p.get("id"))
    if not target:
        raise BusinessError("成员不存在")
    me = require_manager(conn, uid, target["team_id"])
    if str(target["id"]) == str(me["id"]):
        raise BusinessError("不能移除自己")
    if target["role"] == "owner" and me["role"] != "owner":
        raise BusinessError("需要负责人权限")
    db.remove(conn, "members", p.get("id"))
    audit(conn, uid, target["team_id"], "member_remove", "members",
          p.get("id"), {"name": target["name"]})
    return {"removed": p.get("id")}


HANDLERS = {
    "getMyMember": get_my_member,
    "listMembers": list_members,
    "updateMember": update_member,
    "removeMember": remove_member,
}
