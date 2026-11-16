"""分析数据读取器（P3 §7 任务 3/4）。

职责与边界：
- 只读：本模块只有 SELECT，任何写操作都不在此处；
- 权限：调用方（handlers.analysis）必须已执行 require_manager，本模块不做权限判断；
- 口径：应提交人一律走 services.expected，禁止在这里重新解释 scope / 工作日 / 停用；
- 输出为纯数据结构，交给 metrics / rules / report 做确定性计算。
"""
from datetime import date as date_cls, timedelta

from .. import db
from . import expected, metrics


def _iter_days(from_day, to_day):
    cursor = date_cls.fromisoformat(from_day)
    last = date_cls.fromisoformat(to_day)
    while cursor <= last:
        yield cursor.strftime("%Y-%m-%d")
        cursor = date_cls.fromordinal(cursor.toordinal() + 1)


def _collect_fields(templates):
    """汇总模板字段定义；同名字段取最高版本，保留出现过的单位用于质量检查。"""
    out = {}
    for template in templates:
        version = int(template.get("version") or 1)
        for field in template.get("fields") or []:
            if not isinstance(field, dict):
                continue
            key = field.get("fieldKey")
            if not key:
                continue
            unit = field.get("unit") or ""
            prev = out.get(key)
            units = list(prev.get("units") or []) if prev else []
            if unit and unit not in units:
                units.append(unit)
            if prev is not None and version < int(prev.get("version") or 1):
                prev["units"] = units
                continue
            out[key] = {
                "fieldKey": key,
                "label": field.get("label") or key,
                "unit": unit,
                "statType": metrics.stat_type(field),
                "type": field.get("type"),
                "version": version,
                "units": units,
            }
    return out


def _build_days(members, tasks, templates, entries, from_day, to_day):
    by_date = {}
    for entry in entries:
        by_date.setdefault(entry.get("entry_date"), {})[entry.get("user_id")] = entry

    days = []
    for day in _iter_days(from_day, to_day):
        day_members, source = expected.expected_for_day(members, tasks, templates, day)
        day_entries = by_date.get(day) or {}
        expected_ids = {m.get("user_id") for m in day_members}
        submitted = sorted(
            uid for uid in expected_ids
            if (day_entries.get(uid) or {}).get("status") == "submitted"
        )
        days.append({
            "date": day,
            "expected": day_members,
            "submitted": submitted,
            "source": source,
        })
    return days


def _load_field_templates(conn, team_id, to_day):
    """字段元数据取 published + archived：历史日报可能引用旧版本，单位检查需要覆盖。"""
    rows = db.query(
        conn,
        "SELECT * FROM `form_templates` WHERE team_id = %s "
        "AND status IN ('published', 'archived') "
        "AND (effective_from IS NULL OR effective_from = '' OR effective_from <= %s) "
        "ORDER BY version ASC, effective_from ASC",
        (team_id, to_day),
    )
    return db.rows_to_dicts(rows, "form_templates")


def _load_period(conn, team_id, from_day, to_day):
    members = expected.load_active_members(conn, team_id)
    member_ids = {m.get("user_id") for m in members}
    templates = expected.load_published_templates(conn, team_id, to_day)
    tasks = expected.load_tasks(conn, team_id, from_day, to_day)
    rows = db.query(
        conn,
        "SELECT * FROM `daily_entries` WHERE team_id = %s "
        "AND entry_date BETWEEN %s AND %s",
        (team_id, from_day, to_day),
    )
    entries = [
        e for e in db.rows_to_dicts(rows, "daily_entries")
        if e.get("user_id") in member_ids
    ]
    return {
        "from": from_day,
        "to": to_day,
        "members": members,
        "templates": templates,
        "tasks": tasks,
        "entries": entries,
        "fields": _collect_fields(_load_field_templates(conn, team_id, to_day)),
        "days": _build_days(members, tasks, templates, entries, from_day, to_day),
    }


def _previous_range(from_day, to_day):
    span = (date_cls.fromisoformat(to_day) - date_cls.fromisoformat(from_day)).days + 1
    prev_to = date_cls.fromisoformat(from_day) - timedelta(days=1)
    prev_from = prev_to - timedelta(days=span - 1)
    return prev_from.strftime("%Y-%m-%d"), prev_to.strftime("%Y-%m-%d")


def build_quality(dataset):
    """数据质量检查：缺失 / 重复 / 类型 / 单位，全部基于当前周期真实数据。"""
    days = dataset.get("days") or []
    entries = dataset.get("entries") or []
    fields = dataset.get("fields") or {}
    refs = {"missing": [], "duplicate": [], "type": [], "unit": []}

    missing_count = 0
    for day in days:
        submitted = set(day.get("submitted") or [])
        for member in day.get("expected") or []:
            uid = member.get("user_id")
            if uid in submitted:
                continue
            missing_count += 1
            if len(refs["missing"]) < 200:
                refs["missing"].append({
                    "userId": uid, "name": member.get("name"), "date": day.get("date"),
                })

    seen = {}
    for entry in entries:
        key = (entry.get("user_id"), entry.get("entry_date"))
        seen[key] = seen.get(key, 0) + 1
    duplicate_count = 0
    for key, count in sorted(seen.items()):
        if count <= 1:
            continue
        duplicate_count += count - 1
        if len(refs["duplicate"]) < 50:
            refs["duplicate"].append({"userId": key[0], "date": key[1], "count": count})

    type_count = 0
    numeric_keys = {
        key for key, meta in fields.items()
        if meta.get("statType") in ("sum", "avg")
    }
    for entry in entries:
        if entry.get("status") != "submitted":
            continue
        for row in entry.get("form_data") or []:
            values = row.get("values") if isinstance(row, dict) else None
            if not isinstance(values, dict):
                continue
            for key in sorted(numeric_keys):
                raw = values.get(key)
                if raw is None or raw == "":
                    continue
                if metrics.as_number(raw) is not None:
                    continue
                type_count += 1
                if len(refs["type"]) < 50:
                    refs["type"].append({
                        "userId": entry.get("user_id"),
                        "date": entry.get("entry_date"),
                        "fieldKey": key,
                        "value": raw,
                    })

    unit_issues = []
    for key in sorted(fields):
        units = fields[key].get("units") or []
        if len(units) > 1:
            unit_issues.append({"fieldKey": key, "units": units})
    refs["unit"] = unit_issues

    checks = [
        {
            "code": "missing_data", "level": "info", "count": missing_count,
            "message": "应提交但无提交记录 %d 人次" % missing_count,
        },
        {
            "code": "duplicate_entry", "level": "warning", "count": duplicate_count,
            "message": "同一成员同日存在重复记录 %d 条（唯一键兜底，正常应为 0）" % duplicate_count,
        },
        {
            "code": "type_mismatch", "level": "warning", "count": type_count,
            "message": "数值字段出现非数字内容 %d 处（已跳过，不参与求和）" % type_count,
        },
        {
            "code": "unit_mismatch", "level": "warning", "count": len(unit_issues),
            "message": "同名字段在不同模板版本中单位不一致 %d 个" % len(unit_issues),
        },
    ]
    return {
        "checks": checks,
        "missingCount": missing_count,
        "duplicateCount": duplicate_count,
        "typeIssueCount": type_count,
        "unitIssueCount": len(unit_issues),
        "refs": refs,
    }


def load_dataset(conn, team_id, from_day, to_day):
    """加载当前周期 + 上一个等长周期，供指标与趋势共用。"""
    current = _load_period(conn, team_id, from_day, to_day)
    prev_from, prev_to = _previous_range(from_day, to_day)
    previous = _load_period(conn, team_id, prev_from, prev_to)
    dataset = {
        "teamId": team_id,
        "from": from_day,
        "to": to_day,
        "today": expected.local_today(),
        "members": current["members"],
        "templates": current["templates"],
        "tasks": current["tasks"],
        "entries": current["entries"],
        "fields": current["fields"],
        "days": current["days"],
        "previous": {
            "from": previous["from"],
            "to": previous["to"],
            "entries": previous["entries"],
            "fields": previous["fields"],
            "days": previous["days"],
        },
    }
    dataset["quality"] = build_quality(dataset)
    return dataset
