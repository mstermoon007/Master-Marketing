"""action -> handler 注册表。

历史 22 个业务 action（零调用的 listEntriesByUser 未迁移）+ P2 填报任务 5 个
+ P3 分析 8 个，共 35 个；另有 /auth/login 登录端点。
"""
from . import analysis, audit, entries, members, tasks, teams, templates
from .common import BusinessError

HANDLERS = {}
for _module in (teams, members, templates, entries, audit, tasks, analysis):
    HANDLERS.update(_module.HANDLERS)


def dispatch(conn, uid: str, event: dict):
    """分发单个 action；未知 action 抛业务错误。"""
    action = event.get("action")
    handler = HANDLERS.get(action)
    if not handler:
        raise BusinessError("未知操作：" + str(action))
    return handler(conn, uid, event)


__all__ = ["HANDLERS", "dispatch", "BusinessError"]
