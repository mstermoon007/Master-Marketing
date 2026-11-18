"""审计：log（客户端主动上报，失败不阻断）"""
from .common import audit, require_writer


def log(conn, uid, p):
    # 防止向其他团队写入伪造的审计记录；只读成员不能写
    ctx = require_writer(conn, uid, p.get("teamId"))
    audit(conn, uid, ctx["team_id"], p.get("action"),
          p.get("targetType"), p.get("targetId"), p.get("detail"),
          workspace_id=ctx.get("workspace_id"))
    return True


HANDLERS = {"log": log}
