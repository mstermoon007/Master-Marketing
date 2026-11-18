"""Web 管理后台服务端入口（P5）。

action：confirmWebLogin / getWorkspaceOverview / listAuditLogs

- confirmWebLogin：仅小程序令牌可调用，把扫码票据标记为 confirmed；
- getWorkspaceOverview：空间 owner/admin 的工作台汇总，指标必须复用
  services.dataset + services.metrics，不得另写口径；
- listAuditLogs：空间 owner/admin 的审计分页，workspace_id 强制过滤。
"""
import re
from datetime import date as date_cls, timedelta

from .. import db
from ..services import dataset, expected, metrics, org
from .common import (BusinessError, audit, require_date,
                     require_workspace_role)

_TICKET_RE = re.compile(r"^[0-9a-f]{32}$")
_MAX_PAGE_SIZE = 200


def _rate_text(rate):
    return "数据不足" if rate is None else "%.1f%%" % (rate * 100)


def _owned_workspaces(conn, uid):
    """当前用户作为 owner 的空间；老数据回退到 teams.owner_uid。"""
    rows = db.query(
        conn,
        "SELECT * FROM `workspaces` WHERE owner_uid = %s "
        "ORDER BY created_at ASC, id ASC",
        (uid,),
    )
    if rows:
        return db.rows_to_dicts(rows, "workspaces")

    legacy = db.query(
        conn,
        "SELECT DISTINCT workspace_id FROM `teams` "
        "WHERE owner_uid = %s AND workspace_id IS NOT NULL AND workspace_id <> ''",
        (uid,),
    )
    ids = [r.get("workspace_id") for r in legacy if r.get("workspace_id")]
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    rows = db.query(
        conn,
        "SELECT * FROM `workspaces` WHERE id IN (%s) ORDER BY created_at ASC, id ASC"
        % placeholders,
        tuple(ids),
    )
    return db.rows_to_dicts(rows, "workspaces")


def _public_workspace(ws):
    return {
        "id": ws.get("id"),
        "workspace_code": ws.get("workspace_code"),
        "name": ws.get("name"),
    }


def confirm_web_login(conn, uid, p):
    ticket = str(p.get("ticket") or "").strip()
    if not _TICKET_RE.fullmatch(ticket):
        raise BusinessError("登录二维码无效，请刷新后重试")

    now = db.now_iso()
    row = db.one(
        conn,
        "SELECT * FROM `web_login_tickets` WHERE ticket = %s LIMIT 1 FOR UPDATE",
        (ticket,),
    )
    if not row:
        raise BusinessError("二维码已失效，请刷新后重试")
    if row.get("status") != "pending":
        raise BusinessError("二维码已使用或已失效，请刷新后重试")
    if (row.get("expires_at") or "") <= now:
        db.update(conn, "web_login_tickets", row["id"], {"status": "expired"})
        raise BusinessError("二维码已过期，请刷新后重试")

    spaces = _owned_workspaces(conn, uid)
    if not spaces:
        raise BusinessError("仅工作空间所有者可登录管理后台")

    workspace_ids = [ws["id"] for ws in spaces]
    db.update(conn, "web_login_tickets", row["id"], {
        "status": "confirmed",
        "user_id": uid,
        "workspace_ids": workspace_ids,
        "confirmed_at": now,
    })
    audit(conn, uid, None, "web_login_confirm", "web_login_tickets", row["id"],
          {"workspaceCount": len(workspace_ids)})
    return {
        "status": "confirmed",
        "workspaces": [_public_workspace(ws) for ws in spaces],
    }


# ---------------------------------------------------------------------------
# 工作台
# ---------------------------------------------------------------------------
def _sum_daily(team_days):
    """按日期汇总多团队的每日数据。"""
    acc = {}
    for day in team_days:
        item = acc.setdefault(day["date"], {
            "date": day["date"], "expectedCount": 0, "submittedCount": 0,
        })
        item["expectedCount"] += int(day.get("expectedCount") or 0)
        item["submittedCount"] += int(day.get("submittedCount") or 0)
    out = []
    for key in sorted(acc):
        item = acc[key]
        rate = (item["submittedCount"] / item["expectedCount"]) if item["expectedCount"] else None
        item["rate"] = None if rate is None else round(rate, 4)
        item["rateText"] = _rate_text(rate)
        out.append(item)
    return out


def get_workspace_overview(conn, uid, p):
    workspace, membership = require_workspace_role(conn, uid, p.get("workspaceId"))
    today = expected.local_today()
    from_day = (date_cls.fromisoformat(today) - timedelta(days=6)).strftime("%Y-%m-%d")

    teams = org.teams_in_workspace(conn, workspace["id"])
    team_rows = []
    all_days = []
    today_expected = 0
    today_submitted = 0

    for team in teams:
        data = dataset.load_dataset(conn, team["team_id"], from_day, today)
        computed = metrics.compute(data)
        days = computed.get("daily") or []
        all_days.extend(days)
        current = next((d for d in days if d.get("date") == today), None)
        if current:
            today_expected += int(current.get("expectedCount") or 0)
            today_submitted += int(current.get("submittedCount") or 0)
        team_rows.append({
            "team_id": team.get("team_id"),
            "name": team.get("name"),
            "department_id": team.get("department_id"),
            "expectedCount": int((current or {}).get("expectedCount") or 0),
            "submittedCount": int((current or {}).get("submittedCount") or 0),
            "rate": (current or {}).get("rate"),
            "rateText": (current or {}).get("rateText") or _rate_text(None),
        })

    today_rate = (today_submitted / today_expected) if today_expected else None

    active_task = db.one(
        conn,
        "SELECT COUNT(*) AS c FROM `report_tasks` WHERE workspace_id = %s "
        "AND status = 'active' AND start_date <= %s "
        "AND (end_date IS NULL OR end_date = '' OR end_date >= %s)",
        (workspace["id"], today, today),
    )
    since = (date_cls.fromisoformat(today) - timedelta(days=6)).strftime("%Y-%m-%d") + "T00:00:00.000Z"
    anomaly = db.one(
        conn,
        "SELECT COUNT(*) AS c FROM `analysis_findings` f "
        "JOIN `analysis_tasks` t ON t.id = f.task_id "
        "WHERE t.workspace_id = %s AND f.level IN ('warning', 'critical') "
        "AND f.created_at >= %s",
        (workspace["id"], since),
    )

    return {
        "workspace": _public_workspace(workspace),
        "role": membership.get("role"),
        "today": today,
        "todayExpected": today_expected,
        "todaySubmitted": today_submitted,
        "todayRate": None if today_rate is None else round(today_rate, 4),
        "todayRateText": _rate_text(today_rate),
        "missingCount": max(today_expected - today_submitted, 0),
        "activeTaskCount": int((active_task or {}).get("c") or 0),
        "anomalyCount": int((anomaly or {}).get("c") or 0),
        "trend": _sum_daily(all_days),
        "teams": team_rows,
    }


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------
def _int(value, default, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return min(max(n, lo), hi)


def list_audit_logs(conn, uid, p):
    workspace, _ = require_workspace_role(conn, uid, p.get("workspaceId"))

    where = ["workspace_id = %s"]
    args = [workspace["id"]]

    from_day = p.get("from")
    to_day = p.get("to")
    if from_day:
        require_date(from_day, "开始日期")
        where.append("created_at >= %s")
        args.append(from_day + "T00:00:00.000Z")
    if to_day:
        require_date(to_day, "结束日期")
        where.append("created_at <= %s")
        args.append(to_day + "T23:59:59.999Z")

    actor = str(p.get("actor") or "").strip()[:128]
    if actor:
        where.append("actor = %s")
        args.append(actor)
    action = str(p.get("action") or "").strip()[:64]
    if action:
        where.append("action = %s")
        args.append(action)

    clause = " AND ".join(where)
    page = _int(p.get("page"), 0, 0, 10000)
    page_size = _int(p.get("pageSize"), 50, 1, _MAX_PAGE_SIZE)

    total = db.one(conn, "SELECT COUNT(*) AS c FROM `audit_logs` WHERE " + clause, tuple(args))
    rows = db.query(
        conn,
        "SELECT * FROM `audit_logs` WHERE " + clause +
        " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
        tuple(args) + (page_size, page * page_size),
    )
    return {
        "items": db.rows_to_dicts(rows, "audit_logs"),
        "total": int((total or {}).get("c") or 0),
        "page": page,
        "pageSize": page_size,
    }


HANDLERS = {
    "confirmWebLogin": confirm_web_login,
    "getWorkspaceOverview": get_workspace_overview,
    "listAuditLogs": list_audit_logs,
}
