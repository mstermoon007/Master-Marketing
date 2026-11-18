"""分析执行引擎（P3 §7/§3.4/§8）。

确定性闭环：dataset（只读）→ metrics → rules → report → analysis_* 落库。
关键约束：
- 幂等：analysis_tasks(team_id, analysis_type, period_start, period_end, rule_version)
  唯一键 + 事务内 SELECT ... FOR UPDATE，重复触发返回既有结果；
- 可追溯：结果记录 data_snapshot_time / metric_version / rule_version / execution_id；
- 只读业务表：所有写操作统一走 _insert/_update/_delete，白名单仅 analysis_*；
- 无模型：不引入任何外部推理服务，报告只拼接已计算结果。
"""
from .. import db
from . import dataset as dataset_service
from . import metrics as metric_service
from . import report as report_service
from . import rules as rule_service

ANALYSIS_TYPE = "period"

WRITABLE_TABLES = frozenset({
    "analysis_metrics", "analysis_rules", "analysis_tasks",
    "analysis_results", "analysis_findings",
})

TASK_STATUS_TEXT = {"running": "执行中", "success": "已完成", "failed": "失败"}
LEVEL_TEXT = {"critical": "严重", "warning": "预警", "info": "提示"}
_LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}


# ---------------------------------------------------------------- 写入护栏

def _guard(table):
    if table not in WRITABLE_TABLES:
        raise RuntimeError("分析引擎禁止写入业务表：%s" % table)


def _insert(conn, table, data):
    _guard(table)
    return db.insert(conn, table, data)


def _update(conn, table, doc_id, patch):
    _guard(table)
    db.update(conn, table, doc_id, patch)


def _delete_findings(conn, task_id):
    _guard("analysis_findings")
    db.execute(conn, "DELETE FROM `analysis_findings` WHERE task_id = %s", (task_id,))


def _commit(conn):
    """任务状态需要先落库：计算失败时才能留下可重试的 failed 记录。"""
    commit = getattr(conn, "commit", None)
    if callable(commit):
        commit()


def _rollback(conn):
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        rollback()


# ---------------------------------------------------------------- 注册表

def ensure_registry(conn):
    """指标/规则注册表以代码为准，缺失行幂等补齐（已有版本不覆盖）。"""
    metric_rows = db.query(conn, "SELECT metric_code, version FROM `analysis_metrics`")
    existed = {(r["metric_code"], int(r["version"])) for r in metric_rows}
    for item in metric_service.definitions():
        if (item["code"], item["version"]) in existed:
            continue
        _insert(conn, "analysis_metrics", {
            "metric_code": item["code"],
            "version": item["version"],
            "name": item["name"],
            "category": item["category"],
            "unit": item["unit"],
            "formula": item["formula"],
            "description": item["description"],
            "status": "active",
            "created_at": db.now_iso(),
        })

    rule_rows = db.query(conn, "SELECT rule_code, version FROM `analysis_rules`")
    existed = {(r["rule_code"], int(r["version"])) for r in rule_rows}
    for item in rule_service.definitions():
        if (item["code"], item["version"]) in existed:
            continue
        _insert(conn, "analysis_rules", {
            "rule_code": item["code"],
            "version": item["version"],
            "name": item["name"],
            "level": item["level"],
            "condition_text": item["condition"],
            "description": item["description"],
            "params": item["params"],
            "status": "active",
            "created_at": db.now_iso(),
        })


def _runtime(conn):
    """返回 (metric_version, rule_version, params_by_code)。"""
    metric_rows = db.query(
        conn, "SELECT version FROM `analysis_metrics` WHERE status = 'active'",
    )
    rule_rows = db.query(
        conn,
        "SELECT rule_code, version, params FROM `analysis_rules` "
        "WHERE status = 'active' ORDER BY rule_code ASC, version DESC",
    )
    metric_version = max([int(r["version"]) for r in metric_rows] or [1])
    rule_version = max([int(r["version"]) for r in rule_rows] or [1])
    params = {}
    for row in rule_rows:
        code = row["rule_code"]
        if code in params:
            continue
        value = row.get("params")
        if isinstance(value, str):
            import json
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                value = None
        params[code] = value if isinstance(value, dict) else {}
    return metric_version, rule_version, params


def list_metrics(conn):
    rows = db.rows_to_dicts(
        db.query(conn, "SELECT * FROM `analysis_metrics` WHERE status = 'active'"),
        "analysis_metrics",
    )
    order = {d["code"]: i for i, d in enumerate(metric_service.definitions())}
    rows.sort(key=lambda r: (order.get(r.get("metric_code"), 99), r.get("metric_code")))
    return [{
        "code": r["metric_code"],
        "version": r["version"],
        "name": r["name"],
        "category": r["category"],
        "unit": r.get("unit") or "",
        "formula": r.get("formula") or "",
        "description": r.get("description") or "",
    } for r in rows]


def list_rules(conn):
    rows = db.rows_to_dicts(
        db.query(
            conn,
            "SELECT * FROM `analysis_rules` WHERE status = 'active' "
            "ORDER BY rule_code ASC, version DESC",
        ),
        "analysis_rules",
    )
    order = {d["code"]: i for i, d in enumerate(rule_service.definitions())}
    rows.sort(key=lambda r: (order.get(r.get("rule_code"), 99), r.get("rule_code")))
    return [{
        "code": r["rule_code"],
        "version": r["version"],
        "name": r["name"],
        "level": r["level"],
        "conditionText": r.get("condition_text") or "",
        "description": r.get("description") or "",
        "params": r.get("params") or {},
    } for r in rows]


# ---------------------------------------------------------------- 任务与结果

def _lock_task(conn, team_id, from_day, to_day, rule_version):
    row = db.one(
        conn,
        "SELECT * FROM `analysis_tasks` WHERE team_id = %s AND analysis_type = %s "
        "AND period_start = %s AND period_end = %s AND rule_version = %s FOR UPDATE",
        (team_id, ANALYSIS_TYPE, from_day, to_day, rule_version),
    )
    return db.row_to_dict(row, "analysis_tasks")


def _workspace_of(conn, team_id):
    """按团队反查工作空间：分析任务落库时固化租户归属，查询不再 JOIN teams。"""
    row = db.one(
        conn,
        "SELECT workspace_id FROM `teams` WHERE team_id = %s LIMIT 1",
        (team_id,),
    )
    return (row or {}).get("workspace_id") or None


def _create_task(conn, team_id, from_day, to_day, metric_version, rule_version, actor):
    payload = {
        "team_id": team_id,
        "workspace_id": _workspace_of(conn, team_id),
        "analysis_type": ANALYSIS_TYPE,
        "period_start": from_day,
        "period_end": to_day,
        "scope": {"teamIds": [team_id], "from": from_day, "to": to_day},
        "status": "running",
        "metric_version": metric_version,
        "rule_version": rule_version,
        "request_by": actor,
        "retry_count": 0,
        "created_at": db.now_iso(),
        "started_at": db.now_iso(),
    }
    try:
        new_id = _insert(conn, "analysis_tasks", payload)
    except Exception:
        # 并发抢同一幂等键：回读已存在任务
        existing = _lock_task(conn, team_id, from_day, to_day, rule_version)
        if not existing:
            raise
        return existing
    return dict(payload, id=new_id)


def _save_result(conn, task, snapshot, execution_id, summary, quality, report_text):
    data = {
        "task_id": task["id"],
        "team_id": task["team_id"],
        "analysis_type": task["analysis_type"],
        "period_start": task["period_start"],
        "period_end": task["period_end"],
        "data_snapshot_time": snapshot,
        "metric_version": task["metric_version"],
        "rule_version": task["rule_version"],
        "execution_id": execution_id,
        "summary": summary,
        "data_quality": quality,
        "report_text": report_text,
        "created_at": snapshot,
    }
    existing = db.get_doc_by_field(conn, "analysis_results", "task_id", task["id"])
    if existing:
        _update(conn, "analysis_results", existing["id"], data)
        return existing["id"]
    return _insert(conn, "analysis_results", data)


def _save_findings(conn, task, result_id, findings, snapshot):
    _delete_findings(conn, task["id"])
    for finding in findings:
        _insert(conn, "analysis_findings", {
            "task_id": task["id"],
            "result_id": result_id,
            "rule_code": finding["ruleCode"],
            "rule_version": finding["ruleVersion"],
            "level": finding["level"],
            "finding_code": finding["findingCode"],
            "title": finding["title"],
            "detail": finding.get("detail"),
            "data_refs": finding.get("dataRefs"),
            "created_at": snapshot,
        })


def _execute(conn, task, params):
    snapshot = db.now_iso()
    execution_id = db.gen_id()
    try:
        ds = dataset_service.load_dataset(
            conn, task["team_id"], task["period_start"], task["period_end"],
        )
        payload = metric_service.compute(ds)
        findings = rule_service.evaluate(ds, payload, params, task["rule_version"])
        payload["period"] = {
            "from": task["period_start"], "to": task["period_end"],
            "days": len(ds.get("days") or []),
        }
        payload["quality"] = ds["quality"]
        payload["findings"] = findings

        team = db.get_doc_by_field(conn, "teams", "team_id", task["team_id"]) or {}
        text = report_service.build(team.get("name"), ds, payload, {
            "snapshotTime": snapshot,
            "metricVersion": task["metric_version"],
            "ruleVersion": task["rule_version"],
            "executionId": execution_id,
        })
        summary = {k: v for k, v in payload.items() if k != "findings"}
        result_id = _save_result(
            conn, task, snapshot, execution_id, summary, ds["quality"], text,
        )
        _save_findings(conn, task, result_id, findings, snapshot)
        finished = db.now_iso()
        _update(conn, "analysis_tasks", task["id"], {
            "status": "success",
            "error_message": None,
            "finished_at": finished,
        })
        task = dict(task, status="success", finished_at=finished, error_message=None)
    except Exception as exc:
        # 丢弃本次未完成的结果，单独提交失败状态，保证任务可被重试
        _rollback(conn)
        _update(conn, "analysis_tasks", task["id"], {
            "status": "failed",
            "error_message": str(exc)[:500],
            "finished_at": db.now_iso(),
        })
        _commit(conn)
        raise
    return _view(conn, task, reused=False)


def _decorate_task(row):
    return {
        "id": row.get("id"),
        "teamId": row.get("team_id"),
        "analysisType": row.get("analysis_type"),
        "from": row.get("period_start"),
        "to": row.get("period_end"),
        "status": row.get("status"),
        "statusText": TASK_STATUS_TEXT.get(row.get("status"), row.get("status")),
        "metricVersion": row.get("metric_version"),
        "ruleVersion": row.get("rule_version"),
        "retryCount": row.get("retry_count") or 0,
        "errorMessage": row.get("error_message") or "",
        "createdAt": row.get("created_at"),
        "finishedAt": row.get("finished_at"),
    }


def _decorate_finding(row):
    return {
        "id": row.get("id"),
        "ruleCode": row.get("rule_code"),
        "ruleVersion": row.get("rule_version"),
        "level": row.get("level"),
        "levelText": LEVEL_TEXT.get(row.get("level"), row.get("level")),
        "findingCode": row.get("finding_code"),
        "title": row.get("title"),
        "detail": row.get("detail"),
        "dataRefs": row.get("data_refs"),
    }


def _view(conn, task, reused):
    result = db.get_doc_by_field(conn, "analysis_results", "task_id", task["id"])
    rows = db.rows_to_dicts(db.query(
        conn,
        "SELECT * FROM `analysis_findings` WHERE task_id = %s",
        (task["id"],),
    ), "analysis_findings")
    rows.sort(key=lambda r: (
        _LEVEL_ORDER.get(r.get("level"), 9), str(r.get("finding_code")),
    ))
    return {
        "task": _decorate_task(task),
        "result": {
            "id": result.get("id") if result else None,
            "dataSnapshotTime": result.get("data_snapshot_time") if result else None,
            "metricVersion": result.get("metric_version") if result else task.get("metric_version"),
            "ruleVersion": result.get("rule_version") if result else task.get("rule_version"),
            "executionId": result.get("execution_id") if result else None,
            "summary": result.get("summary") if result else None,
            "reportText": result.get("report_text") if result else "",
            "createdAt": result.get("created_at") if result else None,
        },
        "findings": [_decorate_finding(r) for r in rows],
        "reused": reused,
    }


# ---------------------------------------------------------------- 对外入口

def run(conn, team_id, from_day, to_day, actor):
    """幂等执行：同一团队/周期/规则版本只产生一条任务与一份结果。"""
    ensure_registry(conn)
    metric_version, rule_version, params = _runtime(conn)
    task = _lock_task(conn, team_id, from_day, to_day, rule_version)
    if task and task.get("status") == "success":
        return _view(conn, task, reused=True)
    if task:
        task = dict(task, status="running", started_at=db.now_iso(),
                    error_message=None, retry_count=int(task.get("retry_count") or 0) + 1,
                    metric_version=metric_version, rule_version=rule_version)
        _update(conn, "analysis_tasks", task["id"], {
            "status": "running",
            "started_at": task["started_at"],
            "error_message": None,
            "retry_count": task["retry_count"],
            "metric_version": metric_version,
        })
    else:
        task = _create_task(
            conn, team_id, from_day, to_day, metric_version, rule_version, actor,
        )
    _commit(conn)
    return _execute(conn, task, params)


def retry(conn, task, actor):
    """失败/中断任务重试：复用同一条任务与结果，不产生重复报告。"""
    row = task
    if row.get("status") == "success":
        return _view(conn, row, reused=True)
    metric_version, _, params = _runtime(conn)
    started = db.now_iso()
    patch = {
        "status": "running",
        "started_at": started,
        "error_message": None,
        "request_by": actor,
        "retry_count": int(row.get("retry_count") or 0) + 1,
        "metric_version": metric_version,
    }
    _update(conn, "analysis_tasks", row["id"], patch)
    _commit(conn)
    return _execute(conn, dict(row, **patch), params)


def list_tasks(conn, team_id, limit=50):
    rows = db.rows_to_dicts(db.query(
        conn,
        "SELECT * FROM `analysis_tasks` WHERE team_id = %s "
        "ORDER BY created_at DESC, id DESC LIMIT %s",
        (team_id, min(max(int(limit), 1), 200)),
    ), "analysis_tasks")
    return [_decorate_task(r) for r in rows]


def get_task_view(conn, task_row):
    return _view(conn, task_row, reused=False)


def list_findings(conn, task_id=None, team_id=None, limit=100):
    limit = min(max(int(limit), 1), 500)
    if task_id:
        rows = db.query(
            conn,
            "SELECT * FROM `analysis_findings` WHERE task_id = %s",
            (task_id,),
        )
    else:
        rows = db.query(
            conn,
            "SELECT f.* FROM `analysis_findings` f "
            "JOIN `analysis_tasks` t ON t.id = f.task_id "
            "WHERE t.team_id = %s ORDER BY f.created_at DESC, f.id DESC LIMIT %s",
            (team_id, limit),
        )
    rows = db.rows_to_dicts(rows, "analysis_findings")
    if task_id:
        rows.sort(key=lambda r: (
            _LEVEL_ORDER.get(r.get("level"), 9), str(r.get("finding_code")),
        ))
    return [_decorate_finding(r) for r in rows]


def overview(conn, team_id):
    ensure_registry(conn)
    tasks = list_tasks(conn, team_id, 5)
    latest_row = db.one(
        conn,
        "SELECT * FROM `analysis_tasks` WHERE team_id = %s AND status = 'success' "
        "ORDER BY finished_at DESC, id DESC LIMIT 1",
        (team_id,),
    )
    latest = _view(conn, db.row_to_dict(latest_row, "analysis_tasks"), reused=True) \
        if latest_row else None
    task_count = db.one(
        conn, "SELECT COUNT(*) AS n FROM `analysis_tasks` WHERE team_id = %s", (team_id,),
    )
    finding_count = db.one(
        conn,
        "SELECT COUNT(*) AS n FROM `analysis_findings` f "
        "JOIN `analysis_tasks` t ON t.id = f.task_id WHERE t.team_id = %s",
        (team_id,),
    )
    return {
        "latest": latest,
        "tasks": tasks,
        "taskCount": int((task_count or {}).get("n") or 0),
        "findingCount": int((finding_count or {}).get("n") or 0),
        "metrics": list_metrics(conn),
        "rules": list_rules(conn),
    }
