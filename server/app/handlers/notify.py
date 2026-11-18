"""消息通知与运行监控（P6）。

action：
- getNotificationSettings：当前用户在某空间内的四类订阅开关与模板配置状态；
- saveNotificationSettings：记录小程序订阅授权结果（只写本人，不接受客户端 user_id）；
- listNotificationLogs：空间管理员查看通知投递记录（含 skipped/failed 原因）；
- getRuntimeMonitor：工作台运行监控（分析成功率/耗时、通知投递汇总、调度器状态）。
"""
from datetime import datetime, timedelta

from .. import db
from ..services import notify, org, scheduler
from .common import BusinessError, audit, require_date, require_member, require_workspace_role

_MAX_PAGE_SIZE = 200


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "accept")
    return bool(value)


def _workspace_id(conn, uid, p, require_joined=True) -> str:
    """解析工作空间：优先 workspaceId，其次 teamId，最后回退用户首个空间。"""
    workspace_id = str(p.get("workspaceId") or "").strip()
    if workspace_id:
        workspace = org.get_workspace(conn, workspace_id)
        if not workspace:
            raise BusinessError("工作空间不存在")
        if require_joined and not org.workspace_membership(conn, uid, workspace_id):
            raise BusinessError("你不是该工作空间成员")
        return workspace_id

    team_id = p.get("teamId")
    if team_id:
        ctx = require_member(conn, uid, team_id)
        return ctx.get("workspace_id") or ""

    spaces = org.workspaces_of_user(conn, uid)
    return spaces[0]["id"] if spaces else ""


def _settings_items(p) -> list:
    """兼容三种入参：settings 字典、settings 列表、granted 已授权类型列表。"""
    raw = p.get("settings")
    items = []
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                items.append((item.get("type") or item.get("notifyType"),
                              item.get("enabled")))
            elif isinstance(item, str):
                items.append((item, True))
    granted = p.get("granted")
    if isinstance(granted, list):
        items.extend((name, True) for name in granted)

    out, seen = [], set()
    for notify_type, enabled in items:
        name = str(notify_type or "").strip()
        if name in notify.NOTIFY_TYPES and name not in seen:
            out.append((name, _as_bool(enabled)))
            seen.add(name)
    return out


def _settings_view(conn, workspace_id, uid) -> dict:
    return {
        "workspaceId": workspace_id,
        "settings": notify.list_settings(conn, workspace_id, uid),
        "templates": [
            {"type": key, "typeText": value["text"], "configured": value["configured"]}
            for key, value in notify.template_status().items()
        ],
    }


# ---------------------------------------------------------------------------
# 订阅设置
# ---------------------------------------------------------------------------
def get_notification_settings(conn, uid, p):
    workspace_id = _workspace_id(conn, uid, p)
    return _settings_view(conn, workspace_id, uid)


def save_notification_settings(conn, uid, p):
    workspace_id = _workspace_id(conn, uid, p)
    items = _settings_items(p)
    if not items:
        raise BusinessError("没有可保存的通知设置")
    for notify_type, enabled in items:
        notify.save_setting(conn, workspace_id, uid, notify_type, enabled)
    audit(conn, uid, None, "notification_settings_save", "notification_settings",
          workspace_id or uid, {name: enabled for name, enabled in items},
          workspace_id=workspace_id or None)
    return _settings_view(conn, workspace_id, uid)


# ---------------------------------------------------------------------------
# 通知记录
# ---------------------------------------------------------------------------
def _int(value, default, lo, hi):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, lo), hi)


def list_notification_logs(conn, uid, p):
    workspace_id = _workspace_id(conn, uid, p)
    require_workspace_role(conn, uid, workspace_id)

    where = ["workspace_id = %s"]
    args = [workspace_id]

    notify_type = str(p.get("notifyType") or "").strip()
    if notify_type in notify.NOTIFY_TYPES:
        where.append("notify_type = %s")
        args.append(notify_type)
    state = str(p.get("status") or "").strip()
    if state in notify.NOTIFY_STATUS_TEXT:
        where.append("status = %s")
        args.append(state)
    if p.get("from"):
        require_date(p.get("from"), "开始日期")
        where.append("created_at >= %s")
        args.append(str(p.get("from")) + "T00:00:00.000Z")
    if p.get("to"):
        require_date(p.get("to"), "结束日期")
        where.append("created_at <= %s")
        args.append(str(p.get("to")) + "T23:59:59.999Z")

    clause = " AND ".join(where)
    page = _int(p.get("page"), 0, 0, 10000)
    page_size = _int(p.get("pageSize"), 50, 1, _MAX_PAGE_SIZE)

    total = db.one(conn, "SELECT COUNT(*) AS c FROM `notification_logs` WHERE " + clause,
                   tuple(args))
    rows = db.query(
        conn,
        "SELECT * FROM `notification_logs` WHERE " + clause +
        " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
        tuple(args) + (page_size, page * page_size),
    )
    items = db.rows_to_dicts(rows, "notification_logs")
    for item in items:
        item["typeText"] = notify.NOTIFY_TYPE_TEXT.get(
            item.get("notify_type"), item.get("notify_type"))
        item["statusText"] = notify.NOTIFY_STATUS_TEXT.get(
            item.get("status"), item.get("status"))
    return {
        "items": items,
        "total": int((total or {}).get("c") or 0),
        "page": page,
        "pageSize": page_size,
    }


# ---------------------------------------------------------------------------
# 运行监控
# ---------------------------------------------------------------------------
def _duration_ms(row):
    started, finished = row.get("started_at"), row.get("finished_at")
    if not started or not finished:
        return None
    try:
        begin = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(finished).replace("Z", "+00:00"))
        return max(int((end - begin).total_seconds() * 1000), 0)
    except (TypeError, ValueError):
        return None


def get_runtime_monitor(conn, uid, p):
    workspace_id = _workspace_id(conn, uid, p)
    require_workspace_role(conn, uid, workspace_id)

    window_days = _int(p.get("windowDays"), 7, 1, 30)
    since_day = (datetime.now().date() - timedelta(days=window_days - 1)).strftime("%Y-%m-%d")
    since = since_day + "T00:00:00.000Z"

    rows = db.rows_to_dicts(db.query(
        conn,
        "SELECT * FROM `analysis_tasks` "
        "WHERE workspace_id = %s AND created_at >= %s "
        "ORDER BY created_at DESC LIMIT 2000",
        (workspace_id, since),
    ), "analysis_tasks")

    success = sum(1 for r in rows if r.get("status") == "success")
    failed = sum(1 for r in rows if r.get("status") == "failed")
    running = sum(1 for r in rows if r.get("status") == "running")
    durations = [d for d in (_duration_ms(r) for r in rows if r.get("status") == "success")
                 if d is not None]
    avg_duration = int(sum(durations) / len(durations)) if durations else None

    notify_rows = db.query(
        conn,
        "SELECT notify_type, status, COUNT(*) AS c FROM `notification_logs` "
        "WHERE workspace_id = %s AND created_at >= %s "
        "GROUP BY notify_type, status",
        (workspace_id, since),
    )
    by_type = {t: {"type": t, "typeText": notify.NOTIFY_TYPE_TEXT[t],
                   "sent": 0, "skipped": 0, "failed": 0, "pending": 0}
               for t in notify.NOTIFY_TYPES}
    totals = {"total": 0, "sent": 0, "skipped": 0, "failed": 0, "pending": 0}
    for row in notify_rows:
        name = row.get("notify_type")
        state = row.get("status")
        count = int(row.get("c") or 0)
        totals["total"] += count
        if state in totals:
            totals[state] += count
        if name in by_type and state in by_type[name]:
            by_type[name][state] += count

    return {
        "workspaceId": workspace_id,
        "windowDays": window_days,
        "since": since_day,
        "analysis": {
            "total": len(rows),
            "success": success,
            "failed": failed,
            "running": running,
            "successRate": round(success / len(rows), 4) if rows else None,
            "avgDurationMs": avg_duration,
        },
        "notifications": {
            **totals,
            "byType": [by_type[t] for t in notify.NOTIFY_TYPES],
        },
        "scheduler": scheduler.status(conn),
    }


def get_subscribe_templates(conn, uid, p):
    """小程序订阅授权用：返回服务端已配置的模板 ID。

    模板 ID 只来自 WX_TMPL_*，小程序不再维护第二份配置。
    """
    return {"templates": notify.subscribe_templates(),
            "status": notify.template_status()}


HANDLERS = {
    "getSubscribeTemplates": get_subscribe_templates,
    "getNotificationSettings": get_notification_settings,
    "saveNotificationSettings": save_notification_settings,
    "listNotificationLogs": list_notification_logs,
    "getRuntimeMonitor": get_runtime_monitor,
}
