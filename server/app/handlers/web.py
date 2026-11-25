"""Web 管理后台服务端入口（P5）。

action：confirmWebLogin / getWorkspaceOverview / listAuditLogs

- confirmWebLogin：仅小程序令牌可调用，把扫码票据标记为 confirmed；
- getWorkspaceOverview：团队创建人/管理员及以上权限的工作台汇总，指标必须复用
  services.dataset + services.metrics，不得另写口径；
- listAuditLogs：同权限范围的审计分页，workspace_id 强制过滤。
"""
import re
from datetime import date as date_cls
from datetime import timedelta

from .. import db
from ..services import dataset, expected, metrics, org
from .common import BusinessError, audit, require_date

_TICKET_RE = re.compile(r"^[0-9a-f]{32}$")
_MAX_PAGE_SIZE = 200


def _rate_text(rate):
    return "数据不足" if rate is None else "%.1f%%" % (rate * 100)


def managed_workspaces(conn, uid):
    rows = db.query(
        conn,
        "SELECT w.* FROM `workspaces` w "
        "WHERE w.owner_uid = %s "
        "OR EXISTS (SELECT 1 FROM `workspace_members` wm "
        "WHERE wm.workspace_id = w.id AND wm.user_id = %s "
        "AND wm.status = 'active' AND wm.role IN ('owner', 'admin')) "
        "OR EXISTS (SELECT 1 FROM `teams` t "
        "WHERE t.workspace_id = w.id AND (t.owner_uid = %s OR EXISTS ("
        "SELECT 1 FROM `members` m WHERE m.team_id = t.team_id AND m.user_id = %s "
        "AND m.status = 'active' AND m.role IN ('owner', 'manager')))) "
        "ORDER BY w.created_at ASC, w.id ASC",
        (uid, uid, uid, uid),
    )
    return db.rows_to_dicts(rows, "workspaces")


def _role_in_workspace(conn, uid, workspace):
    if workspace.get("owner_uid") == uid:
        return "owner"

    membership = org.workspace_membership(conn, uid, workspace["id"])
    if (membership and membership.get("status") == "active"
            and membership.get("role") in org.WORKSPACE_MANAGER_ROLES):
        return membership.get("role")

    rows = db.query(
        conn,
        "SELECT t.owner_uid AS team_owner_uid, m.role AS member_role "
        "FROM `teams` t "
        "LEFT JOIN `members` m ON m.team_id = t.team_id AND m.user_id = %s "
        "AND m.status = 'active' "
        "WHERE t.workspace_id = %s AND (t.owner_uid = %s OR m.id IS NOT NULL)",
        (uid, workspace["id"], uid),
    )
    for row in rows:
        if row.get("team_owner_uid") == uid or row.get("member_role") == "owner":
            return "owner"
        if row.get("member_role") == "manager":
            return "manager"
    return None


def _require_managed_workspace(conn, uid, workspace_id):
    workspace = org.get_workspace(conn, workspace_id)
    if not workspace:
        raise BusinessError("工作空间不存在")
    role = _role_in_workspace(conn, uid, workspace)
    if role not in ("owner", "admin", "manager"):
        raise BusinessError("仅团队创建人及以上权限人员可登录管理后台")
    return workspace, {"role": role, "status": "active"}


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

    spaces = managed_workspaces(conn, uid)
    if not spaces:
        raise BusinessError("仅团队创建人及以上权限人员可登录管理后台")

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
    workspace, membership = _require_managed_workspace(conn, uid, p.get("workspaceId"))
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
        "JOIN `teams` tm ON tm.team_id = t.team_id "
        "WHERE tm.workspace_id = %s AND f.level IN ('warning', 'critical') "
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
    workspace, _ = _require_managed_workspace(conn, uid, p.get("workspaceId"))

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
