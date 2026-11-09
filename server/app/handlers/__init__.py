"""action -> handler 注册表。

与旧云函数 cloudfunctions/api/index.js 的 handlers 表对应，
共 22 个在用业务 action（零调用的 listEntriesByUser 审阅后未迁移）；
另有 /auth/login 登录端点。
"""
from . import audit, entries, members, teams, templates
from .common import BusinessError

HANDLERS = {}
for _module in (teams, members, templates, entries, audit):
    HANDLERS.update(_module.HANDLERS)


def dispatch(conn, uid: str, event: dict):
    """分发单个 action；未知 action 抛业务错误。"""
    action = event.get("action")
    handler = HANDLERS.get(action)
    if not handler:
        raise BusinessError("未知操作：" + str(action))
    return handler(conn, uid, event)


__all__ = ["HANDLERS", "dispatch", "BusinessError"]
