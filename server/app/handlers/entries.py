"""录入：getMyEntry / saveEntry / listMyEntries / listTeamEntries

幂等：daily_entries(team_id, user_id, entry_date) 唯一索引 + 事务内 SELECT FOR UPDATE。
user_id 强制取 JWT 身份，忽略客户端传值。
提交（submitted）由服务端按模板字段复核，前端校验只是体验层，不能作为唯一防线。
"""
import json
from datetime import datetime, timedelta, timezone

from .. import db
from .common import BusinessError, audit, require_date, require_manager, require_member

_ENTRY_COLUMNS = frozenset({
    "team_id", "entry_date", "template_id", "template_version",
    "form_data", "status", "source", "updated_at",
})
_NUMERIC_TYPES = ("integer", "decimal", "money")

# 与前端 utils/date.js 的 BACKFILL_DAYS 保持一致（31 天）
BACKFILL_DAYS = 31
_PAGE_SIZE_DEFAULT = 1000
_PAGE_SIZE_MAX = 1000


def _check_entry_date(value):
    """录入日期必须落在可补录窗口内；服务端独立校验，不信任客户端日历。

    前端用本地时区（UTC+8），服务端用 UTC，跨日会有一天偏差，
    因此上下各放宽 1 天，避免凌晨提交/补录被误拒。
    """
    require_date(value, "录入日期")
    now = datetime.now(timezone.utc)
    lower = (now - timedelta(days=BACKFILL_DAYS + 1)).strftime("%Y-%m-%d")
    upper = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    if not (lower <= value <= upper):
        raise BusinessError("录入日期超出可补录范围（最多回溯 %d 天）" % BACKFILL_DAYS)
    return value


def _as_int(value, default, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return min(max(n, lo), hi)


def _clean_payload(payload):
    if not isinstance(payload, dict):
        raise BusinessError("参数错误")
    out = {}
    for k, v in payload.items():
        if k in _ENTRY_COLUMNS:
            out[k] = v
    return out


def _template_fields(conn, team_id, template_id, version):
    """读取该团队该版本的字段定义；模板不存在或跨团队时直接拒绝。"""
    if not template_id:
        raise BusinessError("缺少录入模板信息")
    sql = "SELECT fields FROM `form_templates` WHERE team_id = %s AND template_id = %s"
    args = [team_id, template_id]
    if version is not None:
        sql += " AND version = %s"
        args.append(version)
    sql += " ORDER BY version DESC LIMIT 1"
    row = db.one(conn, sql, tuple(args))
    if row is None:
        raise BusinessError("录入模板不存在或不属于当前团队")
    fields = row.get("fields")
    if isinstance(fields, (str, bytes)):
        try:
            fields = json.loads(fields)
        except (ValueError, TypeError):
            fields = []
    return fields if isinstance(fields, list) else []


def _as_float(value):
    """模板里的 min/max 可能是字符串或空值；非法值按「未配置」处理，不能让请求 500。"""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_rows(fields, form_data):
    """按模板 fields 复核 submitted 数据，口径与前端 utils/validator.js 一致。"""
    if not isinstance(form_data, list):
        raise BusinessError("录入数据格式不正确")
    for idx, row in enumerate(form_data, 1):
        if not isinstance(row, dict):
            raise BusinessError("第 %d 条数据格式不正确" % idx)
        values = row.get("values") or {}
        if not isinstance(values, dict):
            raise BusinessError("第 %d 条数据格式不正确" % idx)
        for f in fields:
            if not isinstance(f, dict):
                continue
            key = f.get("fieldKey")
            label = f.get("label") or key or "字段"
            raw = values.get(key)
            empty = raw is None or raw == "" or (isinstance(raw, list) and len(raw) == 0)
            if f.get("required") and empty:
                raise BusinessError("第 %d 条：%s为必填项" % (idx, label))
            if empty:
                continue
            ftype = f.get("type")
            if ftype in _NUMERIC_TYPES:
                try:
                    num = float(raw)
                except (TypeError, ValueError):
                    raise BusinessError("第 %d 条：%s必须是数字" % (idx, label))
                validation = f.get("validation") or {}
                vmin = _as_float(validation.get("min"))
                vmax = _as_float(validation.get("max"))
                if vmin is not None and num < vmin:
                    raise BusinessError("第 %d 条：%s不能小于 %s" % (idx, label, validation["min"]))
                if vmax is not None and num > vmax:
                    raise BusinessError("第 %d 条：%s不能大于 %s" % (idx, label, validation["max"]))
                if ftype == "integer" and not num.is_integer():
                    raise BusinessError("第 %d 条：%s必须是整数" % (idx, label))
            options = f.get("options") or []
            if ftype == "select" and options and raw not in options:
                raise BusinessError("第 %d 条：%s的选项不合法" % (idx, label))
            if ftype == "multiselect" and options:
                arr = raw if isinstance(raw, list) else [raw]
                if any(x not in options for x in arr):
                    raise BusinessError("第 %d 条：%s的选项不合法" % (idx, label))


def _entry(conn, team_id, uid, date, for_update=False):
    sql = ("SELECT * FROM `daily_entries` WHERE team_id = %s AND user_id = %s "
           "AND entry_date = %s LIMIT 1")
    if for_update:
        sql += " FOR UPDATE"
    return row_to_dict_entry(db.one(conn, sql, (team_id, uid, date)))


def row_to_dict_entry(row):
    return db.row_to_dict(row, "daily_entries")


def get_my_entry(conn, uid, p):
    require_member(conn, uid, p.get("teamId"))
    return _entry(conn, p.get("teamId"), uid, require_date(p.get("date"), "录入日期"))


def save_entry(conn, uid, p):
    data = _clean_payload(p.get("payload"))
    if not data.get("team_id") or not data.get("entry_date"):
        raise BusinessError("参数错误")
    _check_entry_date(data["entry_date"])
    # 防止把数据写进别的团队（客户端 team_id 一律校验）
    require_member(conn, uid, data["team_id"])
    data["user_id"] = uid
    if data.get("status") not in ("draft", "submitted"):
        data["status"] = "draft"
    data["form_data"] = data.get("form_data") or []

    # 模板归属 + 提交字段复核（草稿允许半填，不校验必填）
    fields = _template_fields(conn, data["team_id"], data.get("template_id"),
                              data.get("template_version"))
    if data["status"] == "submitted":
        _validate_rows(fields, data["form_data"])

    existing = _entry(conn, data["team_id"], uid, data["entry_date"], for_update=True)
    if existing:
        patch = dict(data)
        patch.pop("user_id", None)  # user_id 不可变更
        patch.pop("team_id", None)
        patch.pop("entry_date", None)
        patch["updated_at"] = db.now_iso()
        db.update(conn, "daily_entries", existing["id"], patch)
        row = dict(existing, **patch)
    else:
        data["created_at"] = db.now_iso()
        new_id = db.insert(conn, "daily_entries", data)
        row = dict(data, id=new_id)

    if data.get("status") == "submitted":
        audit(conn, uid, data["team_id"], "entry_submit", "daily_entries",
              data.get("template_id"), {
                  "date": data["entry_date"],
                  "rows": len(data["form_data"]) if isinstance(data["form_data"], list) else 0,
              })
    return row


def list_my_entries(conn, uid, p):
    require_member(conn, uid, p.get("teamId"))
    limit = min(max(int(p.get("limit") or 60), 1), 1000)
    rows = db.query(
        conn,
        "SELECT * FROM `daily_entries` WHERE team_id = %s AND user_id = %s "
        "ORDER BY entry_date DESC LIMIT %s",
        (p.get("teamId"), uid, limit),
    )
    return db.rows_to_dicts(rows, "daily_entries")


def list_team_entries(conn, uid, p):
    """按页返回，配合 store.listTeamEntries 的自动翻页消除 LIMIT 静默截断。

    ORDER BY 追加 id 作稳定次序，避免同一天多条记录翻页时重复/遗漏。
    """
    require_manager(conn, uid, p.get("teamId"))
    require_date(p.get("from"), "开始日期")
    require_date(p.get("to"), "结束日期")
    page = _as_int(p.get("page"), 0, 0, 10000)
    page_size = _as_int(p.get("pageSize"), _PAGE_SIZE_DEFAULT, 1, _PAGE_SIZE_MAX)
    rows = db.query(
        conn,
        "SELECT * FROM `daily_entries` WHERE team_id = %s AND entry_date BETWEEN %s AND %s "
        "ORDER BY entry_date DESC, id DESC LIMIT %s OFFSET %s",
        (p.get("teamId"), p.get("from"), p.get("to"), page_size, page * page_size),
    )
    return db.rows_to_dicts(rows, "daily_entries")


HANDLERS = {
    "getMyEntry": get_my_entry,
    "saveEntry": save_entry,
    "listMyEntries": list_my_entries,
    "listTeamEntries": list_team_entries,
}
