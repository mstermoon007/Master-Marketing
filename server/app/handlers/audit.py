"""审计：log（客户端主动上报，失败不阻断）"""
from .common import audit, require_member


def log(conn, uid, p):
    # 防止向其他团队写入伪造的审计记录
    require_member(conn, uid, p.get("teamId"))
    audit(conn, uid, p.get("teamId"), p.get("action"),
          p.get("targetType"), p.get("targetId"), p.get("detail"))
    return True


HANDLERS = {"log": log}
