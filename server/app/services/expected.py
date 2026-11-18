"""应提交口径的单一实现（升级文档 §3.6）。

看板、报表、分析引擎必须共用本模块，禁止各自实现：
1. 当日有覆盖该日期的 active 任务时，任务 scope 并集即应提交口径；
   - 任务命中 workdays_only 但当天是周末时，该任务当天不产生应提交人；
   - 有任务但当天被工作日规则全部过滤掉时，应提交为空，不回退模板口径。
2. 当日没有任何任务时，回退到「已生效模板 scope 并集」以兼容旧行为。
3. 两种情况都只统计 status='active' 的成员（disabled 一律排除）。
"""
from datetime import datetime, timedelta, timezone

from .. import db

SHANGHAI = timezone(timedelta(hours=8))


def local_today() -> str:
    """业务日期按东八区计算，避免凌晨提交被判成前一天。"""
    return datetime.now(SHANGHAI).strftime("%Y-%m-%d")


def is_workday(day: str) -> bool:
    try:
        return datetime.strptime(day, "%Y-%m-%d").weekday() < 5
    except (TypeError, ValueError):
        return True


def scope_matches(scope, member) -> bool:
    """与成员端 getActiveTemplate / 原 inScope 语义保持一致。"""
    if not isinstance(scope, dict):
        return True
    stype = scope.get("type")
    if not stype or stype == "all":
        return True
    if not member:
        return False
    if stype == "members":
        return member.get("user_id") in (scope.get("memberIds") or [])
    if stype == "roles":
        return member.get("role") in (scope.get("roles") or [])
    return True


def load_active_members(conn, team_id):
    """应提交成员：active 且未主动退出；只读成员不计入应提交口径。"""
    rows = db.query(
        conn,
        "SELECT * FROM `members` WHERE team_id = %s AND status = 'active' "
        "AND left_at IS NULL AND role <> 'viewer' "
        "ORDER BY joined_at ASC, id ASC",
        (team_id,),
    )
    return db.rows_to_dicts(rows, "members")


def load_published_templates(conn, team_id, until_day):
    """取截至 until_day 已生效的已发布模板，按生效日与版本排序。"""
    rows = db.query(
        conn,
        "SELECT * FROM `form_templates` WHERE team_id = %s AND status = 'published' "
        "AND (effective_from IS NULL OR effective_from = '' OR effective_from <= %s) "
        "ORDER BY effective_from ASC, version DESC",
        (team_id, until_day),
    )
    return db.rows_to_dicts(rows, "form_templates")


def load_tasks(conn, team_id, from_day, to_day):
    """取与 [from_day, to_day] 有交集的 active 任务。"""
    rows = db.query(
        conn,
        "SELECT * FROM `report_tasks` WHERE team_id = %s AND status = 'active' "
        "AND start_date <= %s AND (end_date IS NULL OR end_date = '' OR end_date >= %s) "
        "ORDER BY created_at ASC, id ASC",
        (team_id, to_day, from_day),
    )
    return db.rows_to_dicts(rows, "report_tasks")


def task_covers(task, day) -> bool:
    start = task.get("start_date") or ""
    end = task.get("end_date") or ""
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def _task_active_on(task, day) -> bool:
    if not task_covers(task, day):
        return False
    if int(task.get("workdays_only") or 0) and not is_workday(day):
        return False
    return True


def _templates_for_day(templates, day):
    out = []
    for t in templates:
        effective = t.get("effective_from") or ""
        if not effective or effective <= day:
            out.append(t)
    return out


def expected_for_day(members, tasks, templates, day):
    """纯函数：返回 (应提交成员列表, 口径来源 task|template|none)。"""
    covering = [t for t in tasks if task_covers(t, day)]
    if covering:
        active = [t for t in covering if _task_active_on(t, day)]
        expected = [
            m for m in members
            if any(scope_matches(t.get("scope"), m) for t in active)
        ]
        return expected, "task"

    day_templates = _templates_for_day(templates, day)
    if not day_templates:
        # 无任务、无生效模板：沿用旧行为（全员应提交），由调用方提示无模板
        return list(members), "none"
    expected = [
        m for m in members
        if any(scope_matches(t.get("scope"), m) for t in day_templates)
    ]
    return expected, "template"


def resolve_expected(conn, team_id, day):
    """单日口径：供看板/任务状态/日报复核共用。"""
    members = load_active_members(conn, team_id)
    templates = load_published_templates(conn, team_id, day)
    tasks = load_tasks(conn, team_id, day, day)
    members, source = expected_for_day(members, tasks, templates, day)
    return {"members": members, "source": source, "tasks": tasks, "templates": templates}


def compute_expected_submitters(conn, team_id, day):
    """对外唯一入口：返回某日应提交成员列表。"""
    return resolve_expected(conn, team_id, day)["members"]
