"""action -> handler 注册表。

历史 22 个业务 action（零调用的 listEntriesByUser 未迁移）+ P2 填报任务 5 个
+ P3 分析 8 个 + P4 组织与多工作空间 9 个 + P5 Web 管理后台 3 个，共 47 个；
另有 /auth/login 与 /auth/web/* 登录端点、/api/export/entries 导出端点。
"""
from . import (analysis, audit, entries, members, tasks, teams, templates,
               web, workspaces)
from .common import BusinessError

HANDLERS = {}
for _module in (teams, members, templates, entries, audit, tasks, analysis,
                workspaces, web):
    HANDLERS.update(_module.HANDLERS)

# Web 令牌（aud=web）只能调用显式白名单内的 action：
# 小程序填报（saveEntry / getMyEntry / listMyEntries / log）与 confirmWebLogin 一律不可用。
WEB_ACTIONS = frozenset({
    # 只读
    "listMyWorkspaces", "switchWorkspace", "listWorkspaceMembers",
    "listDepartments", "listTemplates", "getTemplate",
    "listReportTasks", "getReportTask", "getReportTaskStatus",
    "listTeamEntries", "listAnalysisTasks", "getAnalysisTask",
    "listAnalysisFindings", "getAnalysisOverview",
    "getWorkspaceOverview", "listAuditLogs",
    # 管理
    "createTeam", "updateTeamConfig", "updateMember", "removeMember",
    "createWorkspace", "updateWorkspace", "updateWorkspaceMember",
    "createDepartment", "updateDepartment",
    "createDraft", "updateTemplateRow", "deleteTemplateRow",
    "nextVersion", "publishTemplate",
    "createReportTask", "closeReportTask",
})

# 仅小程序令牌可调用（Web 令牌必须被拒绝）
MINI_ONLY_ACTIONS = frozenset({"confirmWebLogin"})


def dispatch(conn, uid: str, event: dict):
    """分发单个 action；未知 action 抛业务错误。"""
    action = event.get("action")
    handler = HANDLERS.get(action)
    if not handler:
        raise BusinessError("未知操作：" + str(action))
    return handler(conn, uid, event)


__all__ = [
    "HANDLERS", "WEB_ACTIONS", "MINI_ONLY_ACTIONS", "dispatch", "BusinessError",
]
