"""action 元数据注册表（P1）。

每个 action 在这里声明一次：所属模块、Web 端是否可用、是否写操作、用途摘要。
`HANDLERS` / `WEB_ACTIONS` / `MINI_ONLY_ACTIONS` 全部由此派生，不再三处手工维护。

新增 action 的步骤：
1. 在对应 handler 模块实现函数并加入该模块 HANDLERS；
2. 在本文件 `_ROWS` 增加一行元数据；
3. 同步 `utils/store.js` 与 `tests/test_contract.py`。

导入时即校验 handler 与元数据双向一一对应，缺失、多余、重复都会直接抛错，
避免「注册了但没声明」「声明了但没实现」的静默漂移。
"""
from dataclasses import dataclass
from typing import Callable

from . import analysis, audit, entries, members, notify, tasks, teams, templates, web, workspaces
from .common import BusinessError

_MODULES = {
    "teams": teams,
    "members": members,
    "templates": templates,
    "entries": entries,
    "audit": audit,
    "tasks": tasks,
    "analysis": analysis,
    "workspaces": workspaces,
    "web": web,
    "notify": notify,
}


@dataclass(frozen=True)
class ActionMeta:
    name: str
    module: str
    handler: Callable
    web: bool = False
    mini_only: bool = False
    mutating: bool = False
    summary: str = ""


# (action, module, Web 可用, 写操作, 摘要)
_ROWS = (
    # ---- 团队 ----
    ("createTeam", "teams", True, True, "创建团队并成为创建者"),
    ("findTeam", "teams", False, False, "按邀请码查找团队"),
    ("getTeam", "teams", False, False, "读取当前团队与本人角色"),
    ("joinTeam", "teams", False, True, "加入团队"),
    ("updateTeamConfig", "teams", True, True, "修改团队名称与配置"),
    # ---- 成员 ----
    ("getMyMember", "members", False, False, "读取本人成员信息"),
    ("listMembers", "members", False, False, "读取成员列表"),
    ("removeMember", "members", True, True, "移除团队成员"),
    ("updateMember", "members", True, True, "修改成员角色"),
    # ---- 模板 ----
    ("listTemplates", "templates", True, False, "读取模板列表（含草稿）"),
    ("listPublishedTemplates", "templates", False, False, "读取已发布模板"),
    ("getTemplate", "templates", True, False, "读取单个模板版本"),
    ("createDraft", "templates", True, True, "创建模板草稿"),
    ("updateTemplateRow", "templates", True, True, "修改草稿行"),
    ("deleteTemplateRow", "templates", True, True, "删除草稿行"),
    ("nextVersion", "templates", True, True, "基于现有模板生成新版本"),
    ("publishTemplate", "templates", True, True, "发布模板版本"),
    # ---- 填报 ----
    ("getMyEntry", "entries", False, False, "读取本人某日填报"),
    ("saveEntry", "entries", False, True, "保存草稿或提交填报"),
    ("listMyEntries", "entries", False, False, "读取本人历史填报"),
    ("listTeamEntries", "entries", True, False, "读取团队填报列表"),
    # ---- 审计 ----
    ("log", "audit", False, True, "记录前端审计事件"),
    # ---- 填报任务 ----
    ("createReportTask", "tasks", True, True, "创建填报任务"),
    ("closeReportTask", "tasks", True, True, "关闭填报任务"),
    ("listReportTasks", "tasks", True, False, "读取任务列表"),
    ("getReportTask", "tasks", True, False, "读取任务详情"),
    ("getReportTaskStatus", "tasks", True, False, "读取任务完成状态"),
    # ---- 分析 ----
    ("runAnalysis", "analysis", False, True, "执行确定性分析"),
    ("retryAnalysisTask", "analysis", False, True, "重试失败的分析任务"),
    ("listAnalysisTasks", "analysis", True, False, "读取分析任务列表"),
    ("getAnalysisTask", "analysis", True, False, "读取分析任务详情"),
    ("listAnalysisFindings", "analysis", True, False, "读取异常发现"),
    ("listAnalysisMetrics", "analysis", False, False, "读取指标明细"),
    ("listAnalysisRules", "analysis", False, False, "读取异常规则"),
    ("getAnalysisOverview", "analysis", True, False, "读取分析总览"),
    # ---- 工作空间与部门 ----
    ("listMyWorkspaces", "workspaces", True, False, "读取我的工作空间"),
    ("switchWorkspace", "workspaces", True, True, "切换当前工作空间"),
    ("createWorkspace", "workspaces", True, True, "创建工作空间"),
    ("updateWorkspace", "workspaces", True, True, "修改工作空间"),
    ("listWorkspaceMembers", "workspaces", True, False, "读取空间成员"),
    ("updateWorkspaceMember", "workspaces", True, True, "修改空间成员角色"),
    ("listDepartments", "workspaces", True, False, "读取部门树"),
    ("createDepartment", "workspaces", True, True, "创建部门"),
    ("updateDepartment", "workspaces", True, True, "修改部门"),
    # ---- Web 登录与工作台 ----
    ("confirmWebLogin", "web", False, True, "小程序确认 Web 扫码登录"),
    ("getWorkspaceOverview", "web", True, False, "读取工作台总览"),
    ("listAuditLogs", "web", True, False, "读取审计日志"),
    # ---- 通知与监控 ----
    ("getSubscribeTemplates", "notify", False, False, "读取已配置的订阅模板 ID"),
    ("getNotificationSettings", "notify", True, False, "读取本人订阅设置"),
    ("saveNotificationSettings", "notify", True, True, "保存本人订阅设置"),
    ("listNotificationLogs", "notify", True, False, "读取通知记录"),
    ("getRuntimeMonitor", "notify", True, False, "读取运行监控"),
)


def _build() -> dict:
    modules = {}
    for name, module in _MODULES.items():
        modules[name] = module.HANDLERS

    actions = {}
    for row in _ROWS:
        name, module_name, is_web, is_mutating, summary = row
        if name in actions:
            raise RuntimeError("action 元数据重复：" + name)
        handlers = modules.get(module_name)
        if handlers is None:
            raise RuntimeError("action 元数据模块不存在：%s -> %s" % (name, module_name))
        handler = handlers.get(name)
        if handler is None:
            raise RuntimeError("action 元数据缺少实现：%s (%s)" % (name, module_name))
        actions[name] = ActionMeta(
            name=name,
            module=module_name,
            handler=handler,
            web=is_web,
            mini_only=(name == "confirmWebLogin"),
            mutating=is_mutating,
            summary=summary,
        )

    registered = set()
    for module_name, handlers in modules.items():
        registered.update(handlers)
    missing = registered - set(actions)
    if missing:
        raise RuntimeError("以下 action 已注册但缺少元数据：" + ", ".join(sorted(missing)))
    extra = set(actions) - registered
    if extra:
        raise RuntimeError("以下 action 有元数据但未注册：" + ", ".join(sorted(extra)))

    for meta in actions.values():
        if meta.web and meta.mini_only:
            raise RuntimeError("action 不能同时是 Web 可用与小程序专属：" + meta.name)
    return actions


ACTIONS = _build()
HANDLERS = {name: meta.handler for name, meta in ACTIONS.items()}

# Web 令牌（aud=web）只能调用这里列出的 action；小程序令牌不受该白名单限制
WEB_ACTIONS = frozenset(name for name, meta in ACTIONS.items() if meta.web)

# 仅小程序令牌可调用（Web 令牌即使将来加入白名单也必须拒绝）
MINI_ONLY_ACTIONS = frozenset(name for name, meta in ACTIONS.items() if meta.mini_only)


def dispatch(conn, uid: str, event: dict):
    """分发单个 action；未知 action 抛业务错误。"""
    action = event.get("action")
    meta = ACTIONS.get(action)
    if not meta:
        raise BusinessError("未知操作：" + str(action))
    return meta.handler(conn, uid, event)


__all__ = [
    "ActionMeta", "ACTIONS", "HANDLERS", "WEB_ACTIONS", "MINI_ONLY_ACTIONS",
    "dispatch", "BusinessError",
]
