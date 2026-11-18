"""Excel 导出（P5）：团队日报。

权限与 listTeamEntries 完全一致（require_manager），列头与数据页一致：
日期、成员、提交状态 + 模板字段中文名。
"""
from io import BytesIO

from openpyxl import Workbook

from .. import db
from ..handlers.common import BusinessError, require_date, require_manager

_MAX_ROWS = 50000
_PAGE_SIZE = 1000
_STATUS_TEXT = {"submitted": "已提交", "draft": "草稿"}


def _field_columns(conn, team_id, template_id=None):
    """按最高版本优先收集字段定义，保持模板中的原始顺序。"""
    sql = ("SELECT * FROM `form_templates` WHERE team_id = %s "
           "AND status IN ('published', 'archived')")
    args = [team_id]
    if template_id:
        sql += " AND template_id = %s"
        args.append(template_id)
    sql += " ORDER BY version DESC, effective_from DESC, id DESC"
    rows = db.rows_to_dicts(db.query(conn, sql, tuple(args)), "form_templates")

    columns = []
    seen = set()
    for template in rows:
        for field in template.get("fields") or []:
            if not isinstance(field, dict):
                continue
            key = field.get("fieldKey")
            if not key or key in seen:
                continue
            seen.add(key)
            label = field.get("label") or key
            unit = field.get("unit") or ""
            columns.append({"key": key, "label": label + ("（%s）" % unit if unit else "")})
    return columns


def _entry_where(ctx, from_day, to_day, template_id=None):
    where = ["team_id = %s", "entry_date BETWEEN %s AND %s"]
    args = [ctx["team_id"], from_day, to_day]
    if ctx.get("workspace_id"):
        where.append("workspace_id = %s")
        args.append(ctx["workspace_id"])
    if template_id:
        where.append("template_id = %s")
        args.append(template_id)
    return " AND ".join(where), args


def _count_entries(conn, ctx, from_day, to_day, template_id=None):
    clause, args = _entry_where(ctx, from_day, to_day, template_id)
    row = db.one(conn, "SELECT COUNT(*) AS c FROM `daily_entries` WHERE " + clause, tuple(args))
    return int((row or {}).get("c") or 0)


def _entry_rows(conn, ctx, from_day, to_day, template_id=None):
    """分页读取；单条填报记录本身超过上限时要求缩小范围。"""
    clause, args = _entry_where(ctx, from_day, to_day, template_id)
    sql = ("SELECT * FROM `daily_entries` WHERE " + clause +
           " ORDER BY entry_date ASC, id ASC LIMIT %s OFFSET %s")

    offset = 0
    while True:
        rows = db.rows_to_dicts(
            db.query(conn, sql, tuple(args) + (_PAGE_SIZE, offset)),
            "daily_entries",
        )
        if not rows:
            return
        for row in rows:
            yield row
        offset += len(rows)
        if len(rows) < _PAGE_SIZE:
            return


def build_entries_export(conn, uid, payload):
    """返回 (字节流迭代器, 文件名)。"""
    team_id = str(payload.get("teamId") or "").strip()
    if not team_id:
        raise BusinessError("请选择团队")
    from_day = require_date(payload.get("startDate"), "开始日期")
    to_day = require_date(payload.get("endDate"), "结束日期")
    if to_day < from_day:
        raise BusinessError("结束日期不能早于开始日期")

    ctx = require_manager(conn, uid, team_id)
    template_id = str(payload.get("templateId") or "").strip() or None

    total = _count_entries(conn, ctx, from_day, to_day, template_id)
    if total > _MAX_ROWS:
        raise BusinessError("导出数据超过 %d 条，请缩小日期范围或按模板筛选" % _MAX_ROWS)

    columns = _field_columns(conn, ctx["team_id"], template_id)
    members = db.query(
        conn, "SELECT user_id, name FROM `members` WHERE team_id = %s",
        (ctx["team_id"],),
    )
    names = {r.get("user_id"): r.get("name") for r in members}

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("日报数据")
    sheet.append(["日期", "成员", "提交状态"] + [c["label"] for c in columns])

    row_count = 0
    for entry in _entry_rows(conn, ctx, from_day, to_day, template_id):
        form_rows = entry.get("form_data") or []
        if not isinstance(form_rows, list) or not form_rows:
            form_rows = [{"values": {}}]
        for item in form_rows:
            values = item.get("values") if isinstance(item, dict) else None
            values = values if isinstance(values, dict) else {}
            line = [
                entry.get("entry_date"),
                names.get(entry.get("user_id")) or entry.get("user_id"),
                _STATUS_TEXT.get(entry.get("status"), entry.get("status") or ""),
            ]
            for column in columns:
                value = values.get(column["key"])
                if isinstance(value, (list, tuple)):
                    value = "、".join(str(v) for v in value)
                line.append(value)
            sheet.append(line)
            row_count += 1
            if row_count > _MAX_ROWS:
                raise BusinessError("导出数据超过 %d 行，请缩小日期范围或按模板筛选" % _MAX_ROWS)

    buffer = BytesIO()
    workbook.save(buffer)
    filename = "entries_%s_%s_%s.xlsx" % (ctx["team_id"], from_day, to_day)
    return iter([buffer.getvalue()]), filename
