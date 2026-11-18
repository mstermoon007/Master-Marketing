"""消息通知服务（P6）：订阅设置、去重记录与微信订阅消息投递。

四类通知：
- daily_remind   填报提醒（每日固定时间，预告未提交成员）
- due_remind     截止提醒（任务截止前 N 分钟）
- missing_remind 未提交提醒（当日截止后）
- anomaly_alert  异常预警（分析发现 warning/critical 后通知管理者）

边界：
- 未配置模板 ID 时不调用微信，只落 status='skipped' 记录（先上线骨架）；
- 去重键 (user_id, notify_type, scope_key, period_key) 由 INSERT IGNORE 抢占，抢不到即视为已处理；
  其中 scope_key 取团队 id（无团队时取空间 id），保证同一用户在不同团队/空间各发各的；
- 用户未授权 / 已关闭订阅、微信 43101/43004 均记 skipped，不当作失败反复重试；
- 微信原始错误码只落库，不返回客户端。
"""
import logging
from datetime import datetime, timedelta

from .. import config, db
from . import expected, wechat

logger = logging.getLogger("jinribao.notify")

DAILY_REMIND = "daily_remind"
DUE_REMIND = "due_remind"
MISSING_REMIND = "missing_remind"
ANOMALY_ALERT = "anomaly_alert"

NOTIFY_TYPES = (DAILY_REMIND, DUE_REMIND, MISSING_REMIND, ANOMALY_ALERT)

NOTIFY_TYPE_TEXT = {
    DAILY_REMIND: "填报提醒",
    DUE_REMIND: "截止提醒",
    MISSING_REMIND: "未提交提醒",
    ANOMALY_ALERT: "异常预警",
}

NOTIFY_STATUS_TEXT = {
    "pending": "发送中",
    "sent": "已发送",
    "skipped": "已跳过",
    "failed": "失败",
}

# 微信：用户未订阅 / 已取消关注 -> 视为 skipped，不再重试
_SKIP_ERRCODES = frozenset({43101, 43004})

_TEMPLATE_ENV = {
    DAILY_REMIND: "WX_TMPL_DAILY_REMIND",
    DUE_REMIND: "WX_TMPL_DUE_REMIND",
    MISSING_REMIND: "WX_TMPL_MISSING_REMIND",
    ANOMALY_ALERT: "WX_TMPL_ANOMALY_ALERT",
}

_PAGE = "pages/index/index"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def template_id(notify_type: str) -> str:
    """读取该类型当前配置的模板 ID；空串表示尚未配置（dry-run）。"""
    return str(getattr(config, _TEMPLATE_ENV.get(notify_type, ""), "") or "").strip()


def template_status() -> dict:
    return {t: {"configured": bool(template_id(t)), "text": NOTIFY_TYPE_TEXT[t]}
            for t in NOTIFY_TYPES}


def subscribe_templates() -> dict:
    """已配置的模板 ID，供小程序订阅授权使用。

    模板 ID 的唯一来源是服务端 WX_TMPL_* 环境变量；小程序不再本地硬编码，
    避免两侧人工同步导致「弹窗模板」与「发送模板」不一致。
    """
    out = {}
    for notify_type in NOTIFY_TYPES:
        tid = template_id(notify_type)
        if tid:
            out[notify_type] = tid
    return out


def _cut(value, limit: int = 20) -> str:
    """微信 thing 类型字段最多 20 个字符。"""
    text = str(value or "").strip()
    return text[:limit]


def _template_data(team_name, title, day, count=None) -> dict:
    data = {
        "thing1": {"value": _cut(team_name) or "报数机器人"},
        "thing2": {"value": _cut(title) or "填报提醒"},
        "date3": {"value": day},
    }
    if count is not None:
        data["number4"] = {"value": str(int(count))}
    return data


# ---------------------------------------------------------------------------
# 订阅设置
# ---------------------------------------------------------------------------
def settings_enabled(conn, workspace_id: str, user_id: str, notify_type: str) -> bool:
    """未记录设置时视为未订阅：订阅消息必须由用户主动授权。"""
    row = db.one(
        conn,
        "SELECT enabled FROM `notification_settings` "
        "WHERE workspace_id = %s AND user_id = %s AND notify_type = %s LIMIT 1",
        (workspace_id or "", user_id, notify_type),
    )
    return bool(row and int(row.get("enabled") or 0))


def list_settings(conn, workspace_id: str, user_id: str) -> list:
    rows = db.query(
        conn,
        "SELECT notify_type, enabled, updated_at FROM `notification_settings` "
        "WHERE workspace_id = %s AND user_id = %s",
        (workspace_id or "", user_id),
    )
    saved = {r.get("notify_type"): r for r in rows}
    out = []
    for notify_type in NOTIFY_TYPES:
        row = saved.get(notify_type) or {}
        out.append({
            "type": notify_type,
            "typeText": NOTIFY_TYPE_TEXT[notify_type],
            "enabled": bool(row.get("enabled") or 0),
            "configured": bool(template_id(notify_type)),
            "updatedAt": row.get("updated_at"),
        })
    return out


def save_setting(conn, workspace_id: str, user_id: str,
                 notify_type: str, enabled: bool) -> None:
    """按 (workspace, user, type) upsert；并发写入交给唯一键收敛。"""
    now = db.now_iso()
    db.execute(
        conn,
        "INSERT INTO `notification_settings` "
        "(`id`, `workspace_id`, `user_id`, `notify_type`, `enabled`, `updated_at`) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE `enabled` = VALUES(`enabled`), "
        "`updated_at` = VALUES(`updated_at`)",
        (db.gen_id(), workspace_id or "", user_id, notify_type,
         1 if enabled else 0, now),
    )


# ---------------------------------------------------------------------------
# 投递
# ---------------------------------------------------------------------------
def _finish(conn, log_id: str, status: str, error_message=None) -> None:
    patch = {"status": status, "error_message": error_message}
    if status == "sent":
        patch["sent_at"] = db.now_iso()
    db.update(conn, "notification_logs", log_id, patch)


def _scope_key(team_id, workspace_id) -> str:
    """去重作用域：优先团队，其次空间。

    同一 openid 可能同时属于多个团队，只按 (user, type, period) 去重会导致
    先执行的团队抢走唯一键、其他团队的通知被当成重复丢弃。
    """
    return str(team_id or workspace_id or "")


def notify_user(conn, user_id: str, notify_type: str, period_key: str,
                team_name: str, title: str, day: str, count=None,
                team_id=None, workspace_id=None) -> dict:
    """给单个用户投递一条通知；返回 {status, reason}，不抛业务异常。"""
    if notify_type not in NOTIFY_TYPES:
        return {"status": "skipped", "reason": "unknown_type"}

    tid = template_id(notify_type)
    data = _template_data(team_name, title, day, count)
    log_id = db.gen_id()
    payload = {"data": data, "teamName": team_name, "title": title,
               "day": day, "count": count}
    inserted = db.execute(
        conn,
        "INSERT IGNORE INTO `notification_logs` "
        "(`id`, `workspace_id`, `team_id`, `scope_key`, `user_id`, `notify_type`, "
        "`period_key`, `template_id`, `status`, `error_message`, `payload`, "
        "`created_at`, `sent_at`) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', NULL, %s, %s, NULL)",
        (log_id, workspace_id, team_id, _scope_key(team_id, workspace_id), user_id,
         notify_type, period_key, tid or None, db.jdump(payload), db.now_iso()),
    )
    if inserted == 0:
        return {"status": "duplicate", "reason": "already_handled"}

    if not tid:
        _finish(conn, log_id, "skipped", "未配置订阅消息模板")
        return {"status": "skipped", "reason": "no_template"}

    if not settings_enabled(conn, workspace_id or "", user_id, notify_type):
        _finish(conn, log_id, "skipped", "用户未订阅或已关闭")
        return {"status": "skipped", "reason": "not_subscribed"}

    try:
        result = wechat.send_subscribe_message(user_id, tid, _PAGE, data)
    except Exception:
        logger.exception("subscribe message failed: %s/%s", user_id, notify_type)
        _finish(conn, log_id, "failed", "微信接口调用异常")
        return {"status": "failed", "reason": "exception"}

    errcode = int(result.get("errcode") or 0)
    if errcode == 0:
        _finish(conn, log_id, "sent")
        return {"status": "sent", "reason": ""}
    if errcode in _SKIP_ERRCODES:
        _finish(conn, log_id, "skipped", "用户未订阅或已取消关注")
        return {"status": "skipped", "reason": "wechat_%s" % errcode}
    _finish(conn, log_id, "failed", "微信返回错误 %s" % errcode)
    return {"status": "failed", "reason": "wechat_%s" % errcode}


# ---------------------------------------------------------------------------
# 调度任务：填报 / 截止 / 未提交
# ---------------------------------------------------------------------------
def _teams(conn) -> list:
    rows = db.query(
        conn,
        "SELECT team_id, workspace_id, name FROM `teams` "
        "ORDER BY created_at ASC, id ASC",
    )
    return rows


def _submitted_uids(conn, team_id: str, day: str) -> set:
    rows = db.query(
        conn,
        "SELECT DISTINCT user_id FROM `daily_entries` "
        "WHERE team_id = %s AND entry_date = %s AND status = 'submitted'",
        (team_id, day),
    )
    return {r.get("user_id") for r in rows if r.get("user_id")}


def _remind_unsubmitted(conn, notify_type: str, period_prefix: str,
                        title: str, day: str) -> dict:
    stats = {"sent": 0, "skipped": 0, "failed": 0, "duplicate": 0}
    for team in _teams(conn):
        team_id = team.get("team_id")
        if not team_id:
            continue
        resolved = expected.resolve_expected(conn, team_id, day)
        if resolved.get("source") == "none":
            # 当天既无任务也无生效模板：没有可填报内容，不打扰成员
            continue
        submitted = _submitted_uids(conn, team_id, day)
        members = [m for m in resolved.get("members") or []
                   if m.get("user_id") not in submitted]
        for member in members:
            result = notify_user(
                conn, member["user_id"], notify_type,
                "%s:%s" % (period_prefix, day), team.get("name") or "",
                title, day, count=len(members),
                team_id=team_id, workspace_id=team.get("workspace_id"),
            )
            if result.get("status") in stats:
                stats[result["status"]] += 1
    return stats


def run_daily_reminders(conn, day=None) -> dict:
    """每日填报提醒：今天应提交但还没提交的成员。"""
    day = day or expected.local_today()
    return _remind_unsubmitted(conn, DAILY_REMIND, "daily", "今日填报提醒", day)


def run_missing_reminders(conn, day=None) -> dict:
    """当日未提交提醒：截止后的兜底提醒。"""
    day = day or expected.local_today()
    return _remind_unsubmitted(conn, MISSING_REMIND, "missing", "今日尚未提交", day)


def _parse_due(day: str, hhmm):
    try:
        hour, minute = str(hhmm).split(":")
        return datetime.strptime("%s %02d:%02d" % (day, int(hour), int(minute)),
                                 "%Y-%m-%d %H:%M").replace(tzinfo=expected.SHANGHAI)
    except (TypeError, ValueError):
        return None


def run_due_reminders(conn, now=None) -> dict:
    """截止提醒：截止前 N 分钟到截止时刻之间，未提交的应提交成员。"""
    now = now or datetime.now(expected.SHANGHAI)
    day = now.strftime("%Y-%m-%d")
    ahead = timedelta(minutes=max(config.REMIND_BEFORE_MINUTES, 0))
    stats = {"sent": 0, "skipped": 0, "failed": 0, "duplicate": 0}
    teams = {t.get("team_id"): t for t in _teams(conn)}

    rows = db.query(
        conn,
        "SELECT * FROM `report_tasks` WHERE status = 'active' "
        "AND due_time IS NOT NULL AND due_time <> '' "
        "AND start_date <= %s AND (end_date IS NULL OR end_date = '' OR end_date >= %s) "
        "ORDER BY created_at ASC, id ASC",
        (day, day),
    )
    for task in db.rows_to_dicts(rows, "report_tasks"):
        if int(task.get("workdays_only") or 0) and not expected.is_workday(day):
            continue
        due = _parse_due(day, task.get("due_time"))
        if not due or not (due - ahead <= now < due):
            continue
        team = teams.get(task.get("team_id")) or {}
        submitted = _submitted_uids(conn, task["team_id"], day)
        members = [
            m for m in expected.load_active_members(conn, task["team_id"])
            if expected.scope_matches(task.get("scope"), m)
            and m.get("user_id") not in submitted
        ]
        for member in members:
            result = notify_user(
                conn, member["user_id"], DUE_REMIND,
                "due:%s:%s" % (day, task.get("task_key") or task.get("id")),
                team.get("name") or "", task.get("title") or "填报截止提醒",
                "%s %s" % (day, task.get("due_time")), count=len(members),
                team_id=task["team_id"], workspace_id=team.get("workspace_id"),
            )
            if result.get("status") in stats:
                stats[result["status"]] += 1
    return stats


# ---------------------------------------------------------------------------
# 异常预警
# ---------------------------------------------------------------------------
def _manager_uids(conn, team_id: str, workspace_id=None) -> list:
    rows = db.query(
        conn,
        "SELECT user_id FROM `members` WHERE team_id = %s AND status = 'active' "
        "AND role IN ('owner', 'manager') ORDER BY joined_at ASC, id ASC",
        (team_id,),
    )
    uids = [r.get("user_id") for r in rows if r.get("user_id")]
    if workspace_id:
        rows = db.query(
            conn,
            "SELECT user_id FROM `workspace_members` WHERE workspace_id = %s "
            "AND status = 'active' AND role IN ('owner', 'admin') "
            "ORDER BY joined_at ASC, id ASC",
            (workspace_id,),
        )
        for row in rows:
            uid = row.get("user_id")
            if uid and uid not in uids:
                uids.append(uid)
    return uids


def notify_anomalies(conn, team_id: str, task_id: str, findings: list,
                     team_name: str = "", workspace_id=None) -> dict:
    """把 warning/critical 发现汇总后通知团队与空间管理者（同任务只发一次）。"""
    alerts = [f for f in (findings or [])
              if f.get("level") in ("warning", "critical")]
    if not alerts:
        return {"sent": 0, "skipped": 0, "failed": 0, "duplicate": 0}

    if not team_name:
        team = db.get_doc_by_field(conn, "teams", "team_id", team_id) or {}
        team_name = team.get("name") or ""
    day = expected.local_today()
    title = "%s：%s" % (NOTIFY_TYPE_TEXT[ANOMALY_ALERT], alerts[0].get("title") or "发现异常")
    stats = {"sent": 0, "skipped": 0, "failed": 0, "duplicate": 0}
    for uid in _manager_uids(conn, team_id, workspace_id):
        result = notify_user(
            conn, uid, ANOMALY_ALERT, "anomaly:%s" % task_id,
            team_name, title, day, count=len(alerts),
            team_id=team_id, workspace_id=workspace_id,
        )
        if result.get("status") in stats:
            stats[result["status"]] += 1
    return stats
