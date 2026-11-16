"""确定性分析引擎入口（P3）：指标、规则、执行、结果与发现查询。

权限：全部 action 要求团队管理员（普通成员不提供分析入口，见 §8.4）。
参数：查询类用 camelCase 顶层参数（teamId / from / to / id / taskId）。
写权限：本文件只写 analysis_*（由 engine 护栏保证）与 audit_logs（审计）。
"""
from datetime import date as date_cls

from .. import db
from ..services import engine
from .common import BusinessError, audit, require_date, require_manager

_MAX_ANALYSIS_DAYS = 366


def _team_id(p):
    team_id = p.get("teamId")
    if not team_id:
        raise BusinessError("参数错误：team_id 缺失")
    return team_id


def _period(p):
    from_day = require_date(p.get("from"), "开始日期")
    to_day = require_date(p.get("to"), "结束日期")
    if to_day < from_day:
        raise BusinessError("结束日期不能早于开始日期")
    span = (date_cls.fromisoformat(to_day) - date_cls.fromisoformat(from_day)).days + 1
    if span > _MAX_ANALYSIS_DAYS:
        raise BusinessError("分析周期不能超过 %d 天" % _MAX_ANALYSIS_DAYS)
    return from_day, to_day


def _task_by_id(conn, uid, task_id):
    row = db.get_doc(conn, "analysis_tasks", task_id)
    if not row:
        raise BusinessError("分析任务不存在")
    require_manager(conn, uid, row["team_id"])
    return row


# ---------------------------------------------------------------- 指标与规则

def list_analysis_metrics(conn, uid, p):
    team_id = _team_id(p)
    require_manager(conn, uid, team_id)
    engine.ensure_registry(conn)
    return engine.list_metrics(conn)


def list_analysis_rules(conn, uid, p):
    team_id = _team_id(p)
    require_manager(conn, uid, team_id)
    engine.ensure_registry(conn)
    return engine.list_rules(conn)


# ---------------------------------------------------------------- 执行

def run_analysis(conn, uid, p):
    team_id = _team_id(p)
    require_manager(conn, uid, team_id)
    from_day, to_day = _period(p)
    result = engine.run(conn, team_id, from_day, to_day, uid)
    audit(conn, uid, team_id, "analysis_run" if not result.get("reused") else "analysis_reuse",
          "analysis_tasks", result["task"]["id"], {
              "from": from_day,
              "to": to_day,
              "metricVersion": result["task"].get("metricVersion"),
              "ruleVersion": result["task"].get("ruleVersion"),
          })
    return result


def retry_analysis_task(conn, uid, p):
    task = _task_by_id(conn, uid, p.get("id"))
    result = engine.retry(conn, task, uid)
    audit(conn, uid, task["team_id"], "analysis_retry", "analysis_tasks", task["id"], {
        "from": task.get("period_start"),
        "to": task.get("period_end"),
    })
    return result


# ---------------------------------------------------------------- 查询

def list_analysis_tasks(conn, uid, p):
    team_id = _team_id(p)
    require_manager(conn, uid, team_id)
    engine.ensure_registry(conn)
    try:
        limit = int(p.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    return engine.list_tasks(conn, team_id, limit)


def get_analysis_task(conn, uid, p):
    task = _task_by_id(conn, uid, p.get("id"))
    return engine.get_task_view(conn, task)


def list_analysis_findings(conn, uid, p):
    task_id = p.get("taskId") or p.get("id")
    if task_id:
        _task_by_id(conn, uid, task_id)
        return engine.list_findings(conn, task_id=task_id)
    team_id = _team_id(p)
    require_manager(conn, uid, team_id)
    try:
        limit = int(p.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    return engine.list_findings(conn, team_id=team_id, limit=limit)


def get_analysis_overview(conn, uid, p):
    team_id = _team_id(p)
    require_manager(conn, uid, team_id)
    return engine.overview(conn, team_id)


HANDLERS = {
    "listAnalysisMetrics": list_analysis_metrics,
    "listAnalysisRules": list_analysis_rules,
    "runAnalysis": run_analysis,
    "retryAnalysisTask": retry_analysis_task,
    "listAnalysisTasks": list_analysis_tasks,
    "getAnalysisTask": get_analysis_task,
    "listAnalysisFindings": list_analysis_findings,
    "getAnalysisOverview": get_analysis_overview,
}
