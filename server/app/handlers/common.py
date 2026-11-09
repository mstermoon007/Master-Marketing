"""业务处理器共享工具：权限校验、团队/成员查询、审计。

对应旧云函数 api/index.js 的 requireMember / requireManager / audit 等，
身份参数由 JWT 的 sub（openid）传入，客户端无法伪造。
"""
import secrets
from typing import Optional

from .. import db


class BusinessError(Exception):
    """可安全展示给客户端的业务错误。"""


def is_manager(member: Optional[dict]) -> bool:
    return bool(member) and member.get("role") in ("manager", "owner")


def find_team_by_id(conn, team_id: str) -> Optional[dict]:
    if not team_id:
        return None
    return db.get_doc_by_field(conn, "teams", "team_id", team_id)


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


def require_member(conn, uid: str, team_id: str) -> dict:
    member = find_member_by_uid(conn, uid, team_id)
    if not member or member.get("status") != "active":
        raise BusinessError("你不是该团队成员或已被停用")
    return member


def require_manager(conn, uid: str, team_id: str) -> dict:
    member = require_member(conn, uid, team_id)
    if not is_manager(member):
        raise BusinessError("需要管理员权限")
    return member


def audit(conn, uid: str, team_id: str, action: str,
          target_type=None, target_id=None, detail=None) -> None:
    """审计失败不阻断主流程。"""
    try:
        db.insert(conn, "audit_logs", {
            "team_id": team_id,
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
