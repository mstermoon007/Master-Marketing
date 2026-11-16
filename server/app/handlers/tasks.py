"""填报任务：createReportTask / listReportTasks / getReportTask /
getReportTaskStatus / closeReportTask

任务是被考核的下发单元：模板回答「填什么」，任务回答「谁、哪天、什么时候前填」。
应提交口径统一走 services.expected，禁止在本文件另写一套。
"""
import re
from datetime import date as date_cls, datetime

from .. import db
from ..services import expected
from .common import BusinessError, audit, require_date, require_manager

_TASK_STATUS_TEXT = {"active": "进行中", "closed": "已关闭"}
_MEMBER_STATUS_TEXT = {
    "pending": "待提交",
    "submitted": "已提交",
    "late": "已逾期",
    "backfilled": "已补录",
    "closed": "已关闭",
}
_ROLE_NAMES = {"owner": "负责人", "manager": "管理员", "member": "成员"}
_MAX_TASK_DAYS = 366
_DUE_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------------------------------------------------------------- 通用工具

def _payload(p):
    value = p.get("payload")
    return value if isinstance(value, dict) else p


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _team_id(p):
    team_id = p.get("teamId") or _payload(p).get("team_id")
    if not team_id:
        raise BusinessError("参数错误：team_id 缺失")
    return team_id


def _normalize_scope(scope):
    if not isinstance(scope, dict):
        return {"type": "all"}
    stype = scope.get("type")
    if stype not in ("all", "members", "roles"):
        stype = "all"
    out = {"type": stype}
    if stype == "members":
        out["memberIds"] = [str(x) for x in (scope.get("memberIds") or []) if x]
    elif stype == "roles":
        out["roles"] = [str(x) for x in (scope.get("roles") or []) if x]
    return out


def _scope_text(scope):
    if not isinstance(scope, dict) or not scope.get("type") or scope["type"] == "all":
        return "全员"
    if scope["type"] == "members":
        return "指定成员（%d 人）" % len(scope.get("memberIds") or [])
    if scope["type"] == "roles":
        names = [_ROLE_NAMES.get(r, r) for r in (scope.get("roles") or [])]
        return "指定角色：" + ("、".join(names) if names else "无")
    return "全员"


def _template_name_map(conn, team_id):
    rows = db.query(
        conn,
        "SELECT template_id, version, name FROM `form_templates` "
        "WHERE team_id = %s ORDER BY version DESC",
        (team_id,),
    )
    exact, latest = {}, {}
    for row in rows:
        exact[(row["template_id"], row["version"])] = row["name"]
        latest.setdefault(row["template_id"], row["name"])
    return exact, latest


def _template_name(maps, template_id, version):
    exact, latest = maps
    return exact.get((template_id, version)) or latest.get(template_id, "")


def _decorate(row, template_name=""):
    out = dict(row)
    out["statusText"] = _TASK_STATUS_TEXT.get(row.get("status"), row.get("status"))
    out["scopeText"] = _scope_text(row.get("scope"))
    end = row.get("end_date") or ""
    out["dateText"] = row.get("start_date", "") + (" 起" if not end else " 至 " + end)
    out["dueText"] = row.get("due_time") or ""
    out["templateName"] = template_name
    return out


def _resolve_template(conn, team_id, template_id, version):
    if not template_id:
        raise BusinessError("请选择填报模板")
    sql = "SELECT * FROM `form_templates` WHERE team_id = %s AND template_id = %s"
    args = [team_id, template_id]
    if version not in (None, ""):
        try:
            args.append(int(version))
        except (TypeError, ValueError):
            raise BusinessError("模板版本不正确")
        sql += " AND version = %s"
    sql += " ORDER BY version DESC LIMIT 1"
    row = db.one(conn, sql, tuple(args))
    if not row:
        raise BusinessError("模板不存在或不属于当前团队")
    row = db.row_to_dict(row, "form_templates")
    if row.get("status") != "published":
        raise BusinessError("只能基于已发布模板创建任务")
    return row


def _submitted_local_date(entry):
    """提交时间换算成东八区日期，用于判定「当天提交」还是「事后补录」。"""
    raw = entry.get("created_at")
    if not raw:
        return entry.get("entry_date") or ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.astimezone(expected.SHANGHAI).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return entry.get("entry_date") or ""


def _member_status(entry, day, today, now_hm, task_closed, due_time=""):
    submitted = bool(entry) and entry.get("status") == "submitted"
    if submitted:
        return "backfilled" if _submitted_local_date(entry) > day else "submitted"
    if task_closed:
        return "closed"
    if day < today:
        return "late"
    if day == today and due_time and now_hm > due_time:
        return "late"
    return "pending"


def _rate_text(submitted, total):
    if total <= 0:
        return "0%"
    return "%d%%" % min(100, int(round(submitted * 100.0 / total)))


def _status_view(members, entries, day, today, now_hm, task_closed, due_time=""):
    """把成员与当日记录合成带状态的名单。"""
    rows = []
    submitted_count = 0
    pending_count = 0
    late_count = 0
    closed_count = 0
    for member in members:
        uid = member.get("user_id")
        entry = entries.get(uid)
        status = _member_status(entry, day, today, now_hm, task_closed, due_time)
        if status == "pending":
            pending_count += 1
        elif status == "late":
            late_count += 1
        elif status == "closed":
            closed_count += 1
        else:
            submitted_count += 1
        rows.append({
            "userId": uid,
            "name": member.get("name"),
            "role": member.get("role"),
            "status": status,
            "statusText": _MEMBER_STATUS_TEXT.get(status, status),
            "draft": bool(entry) and entry.get("status") == "draft",
        })
    missing = [r for r in rows if r["status"] in ("pending", "late")]
    return {
        "expected": rows,
        "missing": missing,
        "expectedCount": len(rows),
        "submittedCount": submitted_count,
        "pendingCount": pending_count,
        "lateCount": late_count,
        "closedCount": closed_count,
        "missingCount": len(missing),
        "rateText": _rate_text(submitted_count, len(rows)),
        "rate": int(round(submitted_count * 100.0 / len(rows))) if rows else 0,
    }


def _entries_on(conn, team_id, day):
    rows = db.query(
        conn,
        "SELECT * FROM `daily_entries` WHERE team_id = %s AND entry_date = %s",
        (team_id, day),
    )
    return {r["user_id"]: db.row_to_dict(r, "daily_entries") for r in rows}


# ---------------------------------------------------------------- 任务 CRUD

def create_report_task(conn, uid, p):
    payload = _payload(p)
    team_id = _team_id(p)
    me = require_manager(conn, uid, team_id)

    title = str(payload.get("title") or "").strip()[:128]
    if not title:
        raise BusinessError("请填写任务名称")

    start_date = require_date(payload.get("start_date"), "开始日期")
    end_date = payload.get("end_date") or None
    if end_date:
        end_date = require_date(end_date, "结束日期")
        if end_date < start_date:
            raise BusinessError("结束日期不能早于开始日期")
        span = (date_cls.fromisoformat(end_date) - date_cls.fromisoformat(start_date)).days
        if span > _MAX_TASK_DAYS:
            raise BusinessError("任务周期不能超过 %d 天" % _MAX_TASK_DAYS)

    due_time = payload.get("due_time") or None
    if due_time:
        due_time = str(due_time).strip()
        if not _DUE_TIME_RE.fullmatch(due_time):
            raise BusinessError("截止时间格式应为 HH:MM")

    template = _resolve_template(
        conn, team_id, payload.get("template_id"), payload.get("template_version")
    )
    scope = _normalize_scope(payload.get("scope") or template.get("scope"))

    task = {
        "team_id": team_id,
        "task_key": "tk_" + db.gen_id()[:12],
        "title": title,
        "template_id": template["template_id"],
        "template_version": int(template.get("version") or 1),
        "scope": scope,
        "start_date": start_date,
        "end_date": end_date,
        "due_time": due_time,
        "workdays_only": 1 if _as_bool(payload.get("workdays_only")) else 0,
        "status": "active",
        "created_by": me.get("user_id"),
        "created_at": db.now_iso(),
    }
    new_id = db.insert(conn, "report_tasks", task)
    audit(conn, uid, team_id, "task_create", "report_tasks", new_id, {
        "title": title,
        "templateId": task["template_id"],
        "templateVersion": task["template_version"],
        "startDate": start_date,
        "endDate": end_date,
        "scope": scope,
    })
    return _decorate(dict(task, id=new_id), template.get("name") or "")


def list_report_tasks(conn, uid, p):
    team_id = _team_id(p)
    require_manager(conn, uid, team_id)
    status = p.get("status")
    sql = "SELECT * FROM `report_tasks` WHERE team_id = %s"
    args = [team_id]
    if status in ("active", "closed"):
        sql += " AND status = %s"
        args.append(status)
    try:
        limit = int(p.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    sql += " ORDER BY created_at DESC, id DESC LIMIT %s"
    args.append(min(max(limit, 1), 500))
    rows = db.rows_to_dicts(db.query(conn, sql, tuple(args)), "report_tasks")
    maps = _template_name_map(conn, team_id)
    return [
        _decorate(r, _template_name(maps, r.get("template_id"), r.get("template_version")))
        for r in rows
    ]


def get_report_task(conn, uid, p):
    row = db.get_doc(conn, "report_tasks", p.get("id"))
    if not row:
        raise BusinessError("任务不存在")
    require_manager(conn, uid, row["team_id"])
    maps = _template_name_map(conn, row["team_id"])
    name = _template_name(maps, row.get("template_id"), row.get("template_version"))
    return _decorate(row, name)


def close_report_task(conn, uid, p):
    row = db.get_doc(conn, "report_tasks", p.get("id"))
    if not row:
        raise BusinessError("任务不存在")
    require_manager(conn, uid, row["team_id"])
    maps = _template_name_map(conn, row["team_id"])
    name = _template_name(maps, row.get("template_id"), row.get("template_version"))
    if row.get("status") == "closed":
        return _decorate(row, name)
    now = db.now_iso()
    db.update(conn, "report_tasks", p.get("id"), {"status": "closed", "closed_at": now})
    audit(conn, uid, row["team_id"], "task_close", "report_tasks", p.get("id"),
          {"title": row.get("title")})
    return _decorate(dict(row, status="closed", closed_at=now), name)


# ---------------------------------------------------------------- 任务状态

def _task_for_status(conn, team_id, p):
    task = db.get_doc(conn, "report_tasks", p.get("taskId"))
    if not task:
        raise BusinessError("任务不存在")
    if task["team_id"] != team_id:
        raise BusinessError("任务不属于当前团队")
    return task


def _task_day_status(conn, team_id, task, day):
    require_date(day, "统计日期")
    today = expected.local_today()
    now_hm = datetime.now(expected.SHANGHAI).strftime("%H:%M")
    members = expected.load_active_members(conn, team_id)
    applicable = expected.task_covers(task, day)
    if applicable and int(task.get("workdays_only") or 0):
        applicable = expected.is_workday(day)
    if applicable:
        members = [m for m in members if expected.scope_matches(task.get("scope"), m)]
    else:
        members = []
    entries = _entries_on(conn, team_id, day)
    view = _status_view(members, entries, day, today, now_hm,
                        task_closed=task.get("status") == "closed",
                        due_time=task.get("due_time") or "")
    maps = _template_name_map(conn, team_id)
    name = _template_name(maps, task.get("template_id"), task.get("template_version"))
    view.update({
        "date": day,
        "source": "task",
        "hasTemplate": True,
        "templateName": name,
        "task": _decorate(task, name),
        "applicable": applicable,
    })
    return view


def _day_status(conn, team_id, day):
    require_date(day, "统计日期")
    resolved = expected.resolve_expected(conn, team_id, day)
    entries = _entries_on(conn, team_id, day)
    today = expected.local_today()
    now_hm = datetime.now(expected.SHANGHAI).strftime("%H:%M")
    view = _status_view(resolved["members"], entries, day, today, now_hm, task_closed=False)
    names = [t.get("name") for t in resolved["templates"] if t.get("name")]
    view.update({
        "date": day,
        "source": resolved["source"],
        "hasTemplate": bool(resolved["templates"]) or bool(resolved["tasks"]),
        "templateName": "、".join(names[:3]) + ("等" if len(names) > 3 else ""),
        "task": None,
        "applicable": True,
    })
    return view


def _range_status(conn, team_id, from_day, to_day):
    require_date(from_day, "开始日期")
    require_date(to_day, "结束日期")
    if to_day < from_day:
        raise BusinessError("结束日期不能早于开始日期")
    span = (date_cls.fromisoformat(to_day) - date_cls.fromisoformat(from_day)).days
    if span > _MAX_TASK_DAYS:
        raise BusinessError("统计周期不能超过 %d 天" % _MAX_TASK_DAYS)

    members = expected.load_active_members(conn, team_id)
    templates = expected.load_published_templates(conn, team_id, to_day)
    tasks = expected.load_tasks(conn, team_id, from_day, to_day)

    expected_ids = {}
    sources = set()
    cursor = date_cls.fromisoformat(from_day)
    last = date_cls.fromisoformat(to_day)
    while cursor <= last:
        day = cursor.strftime("%Y-%m-%d")
        day_members, source = expected.expected_for_day(members, tasks, templates, day)
        sources.add(source)
        for m in day_members:
            expected_ids[m["user_id"]] = m
        cursor = date_cls.fromordinal(cursor.toordinal() + 1)

    rows = db.query(
        conn,
        "SELECT user_id, entry_date FROM `daily_entries` WHERE team_id = %s "
        "AND entry_date BETWEEN %s AND %s AND status = 'submitted'",
        (team_id, from_day, to_day),
    )
    submitted_users = {
        r["user_id"] for r in rows if r["user_id"] in expected_ids
    }
    expected_rows = [
        {
            "userId": m["user_id"],
            "name": m.get("name"),
            "role": m.get("role"),
            "draft": False,
        }
        for m in expected_ids.values()
    ]
    missing = [r for r in expected_rows if r["userId"] not in submitted_users]

    source = "task" if "task" in sources else ("template" if "template" in sources else "none")
    names = [t.get("name") for t in templates if t.get("name")]
    return {
        "from": from_day,
        "to": to_day,
        "source": source,
        "hasTemplate": bool(templates) or bool(tasks),
        "templateName": "、".join(names[:3]) + ("等" if len(names) > 3 else ""),
        "task": None,
        "applicable": True,
        "expected": expected_rows,
        "missing": missing,
        "expectedCount": len(expected_rows),
        "submittedCount": len(submitted_users),
        "missingCount": len(missing),
        "pendingCount": len(missing),
        "lateCount": 0,
        "closedCount": 0,
        "rateText": _rate_text(len(submitted_users), len(expected_rows)),
        "rate": int(round(len(submitted_users) * 100.0 / len(expected_rows))) if expected_rows else 0,
    }


def get_report_task_status(conn, uid, p):
    team_id = _team_id(p)
    require_manager(conn, uid, team_id)
    if p.get("taskId"):
        task = _task_for_status(conn, team_id, p)
        day = p.get("date") or expected.local_today()
        return _task_day_status(conn, team_id, task, day)
    from_day = p.get("from")
    to_day = p.get("to")
    if from_day or to_day:
        return _range_status(conn, team_id, from_day or to_day, to_day or from_day)
    return _day_status(conn, team_id, p.get("date") or expected.local_today())


HANDLERS = {
    "createReportTask": create_report_task,
    "listReportTasks": list_report_tasks,
    "getReportTask": get_report_task,
    "getReportTaskStatus": get_report_task_status,
    "closeReportTask": close_report_task,
}
