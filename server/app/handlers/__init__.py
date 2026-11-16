"""action -> handler 注册表。

与旧云函数 cloudfunctions/api/index.js 的 handlers 表对应，
历史 22 个业务 action（零调用的 listEntriesByUser 审阅后未迁移），
P2 新增 5 个填报任务 action，共 27 个；另有 /auth/login 登录端点。
"""
from . import audit, entries, members, tasks, teams, templates
from .common import BusinessError

HANDLERS = {}
for _module in (teams, members, templates, entries, audit, tasks):
    HANDLERS.update(_module.HANDLERS)


def dispatch(conn, uid: str, event: dict):
    """分发单个 action；未知 action 抛业务错误。"""
    action = event.get("action")
    handler = HANDLERS.get(action)
    if not handler:
        raise BusinessError("未知操作：" + str(action))
    return handler(conn, uid, event)


__all__ = ["HANDLERS", "dispatch", "BusinessError"]
