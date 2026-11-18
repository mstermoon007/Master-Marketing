"""action -> handler 注册表。

历史 22 个业务 action（零调用的 listEntriesByUser 未迁移）+ P2 填报任务 5 个
+ P3 分析 8 个 + P4 组织与多工作空间 9 个 + P5 Web 管理后台 3 个
+ P6 消息通知与运行监控 4 个 + P1 模板单一配置源 1 个，共 52 个；
另有 /auth/login 与 /auth/web/* 登录端点、/api/export/entries 导出端点。

元数据（模块归属 / Web 白名单 / 是否写操作 / 用途摘要）集中在 `registry.py`，
`HANDLERS` 与两个白名单均由元数据派生，不在本文件重复维护。
"""
from .common import BusinessError
from .registry import ACTIONS, HANDLERS, MINI_ONLY_ACTIONS, WEB_ACTIONS, dispatch

__all__ = [
    "ACTIONS", "HANDLERS", "WEB_ACTIONS", "MINI_ONLY_ACTIONS",
    "dispatch", "BusinessError",
]
