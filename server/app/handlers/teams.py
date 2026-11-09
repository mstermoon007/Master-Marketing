"""团队：createTeam / findTeam / joinTeam / getTeam / updateTeamConfig

一人一团队约束：项目当前的数据模型用 getMyMember() 取"我的团队"（不带 team_id），
若允许同一 openid 属于多个团队，页面上下文会随机落到其中一个团队，
导致填报、看板、报表读到别队数据。因此在创建/加入入口统一拦截。
"""
from .. import db
from .common import (BusinessError, audit, find_member_by_uid, find_team_by_id,
                     gen_team_code, require_manager, require_member)

_TEAM_LIMIT_MSG = "你已加入团队，暂不支持创建或加入多个团队"


def _existing_membership(conn, uid):
    """返回该用户已有的成员记录（含停用），没有则 None。"""
    return find_member_by_uid(conn, uid)


def create_team(conn, uid, p):
    name = str(p.get("name") or "").strip()
    member_name = str(p.get("memberName") or "").strip() or "负责人"
    if not name:
        raise BusinessError("请输入团队名称")
    if _existing_membership(conn, uid):
        raise BusinessError(_TEAM_LIMIT_MSG)

    team_code = None
    for _ in range(5):
        candidate = gen_team_code()
        if not find_team_by_id(conn, candidate):
            team_code = candidate
            break
    if not team_code:
        raise BusinessError("生成团队编号失败，请重试")

    now = db.now_iso()
    config = {"memberSeeTeamTotal": False}
    team_id = db.insert(conn, "teams", {
        "team_id": team_code,
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
        "joined_at": now,
    })
    audit(conn, uid, team_code, "team_create", "teams", team_code, {"name": name})
    return {
        "team": {"id": team_id, "team_id": team_code, "name": name,
                 "owner_uid": uid, "config": config, "created_at": now},
        "member": {"id": member_id, "team_id": team_code, "user_id": uid,
                   "name": member_name, "role": "owner", "status": "active", "joined_at": now},
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
    if mine:
        if mine.get("status") != "active":
            raise BusinessError("你已在团队名单中但处于停用状态，请联系管理员启用")
        return mine

    other = _existing_membership(conn, uid)
    if other and str(other.get("team_id")) != str(team_code):
        raise BusinessError(_TEAM_LIMIT_MSG)

    now = db.now_iso()
    member_id = db.insert(conn, "members", {
        "team_id": team_code,
        "user_id": uid,
        "name": member_name,
        "role": "member",
        "status": "active",
        "joined_at": now,
    })
    audit(conn, uid, team_code, "member_join", "members", uid, {"name": member_name})
    return {"id": member_id, "team_id": team_code, "user_id": uid,
            "name": member_name, "role": "member", "status": "active", "joined_at": now}


def get_team(conn, uid, p):
    require_member(conn, uid, p.get("teamId"))
    return find_team_by_id(conn, p.get("teamId"))


def update_team_config(conn, uid, p):
    me = require_manager(conn, uid, p.get("teamId"))
    team = find_team_by_id(conn, p.get("teamId"))
    if not team:
        raise BusinessError("团队不存在")
    merged = dict(team.get("config") or {})
    incoming = p.get("config") or {}
    if not isinstance(incoming, dict):
        raise BusinessError("参数错误")
    for k, v in incoming.items():
        if k in ("memberSeeTeamTotal",) and isinstance(v, bool):
            merged[k] = v
    db.update(conn, "teams", team["id"], {"config": merged})
    audit(conn, uid, p.get("teamId"), "team_config_update", "teams",
          p.get("teamId"), {"config": merged, "by": me["role"]})
    return {"id": team["id"], "team_id": team["team_id"],
            "name": team["name"], "config": merged}


HANDLERS = {
    "createTeam": create_team,
    "findTeam": find_team,
    "joinTeam": join_team,
    "getTeam": get_team,
    "updateTeamConfig": update_team_config,
}
