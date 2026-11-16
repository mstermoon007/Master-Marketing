"""确定性指标引擎（升级文档 §8.1）。

6 个 MVP 指标只在这里实现一份，看板/报表/分析/导出一律复用：
- SUBMIT_RATE / SUBMIT_COUNT / EXPECTED_COUNT 为提交类指标（按人次汇总）；
- FIELD_SUM / FIELD_AVG 取自模板字段 statType，缺失值跳过、不补零；
- PERIOD_GROWTH 与上一个等长周期比较，上期为 0 或缺失时不计算。

所有函数均为纯函数：输入 dataset（services.dataset 产出），输出普通 dict，
不访问数据库、不依赖当前时间，保证相同输入重复计算结果完全一致。
"""

METRIC_VERSION = 1

METRIC_DEFINITIONS = (
    {
        "code": "SUBMIT_RATE", "name": "提交率", "category": "submission", "unit": "%",
        "formula": "应提交范围内已提交人次 / 应提交人次",
        "description": "分母为 0 时不计算，返回 null；周期口径按人次汇总。",
    },
    {
        "code": "SUBMIT_COUNT", "name": "已提交人数", "category": "submission", "unit": "人次",
        "formula": "应提交范围内当日 status='submitted' 的去重人数逐日累加",
        "description": "排除 disabled 成员与不在应提交范围的人；草稿不计入。",
    },
    {
        "code": "EXPECTED_COUNT", "name": "应提交人数", "category": "submission", "unit": "人次",
        "formula": "compute_expected_submitters 逐日结果累加",
        "description": "与看板、报表共用 services.expected 单一口径。",
    },
    {
        "code": "FIELD_SUM", "name": "数值字段合计", "category": "field", "unit": "",
        "formula": "按模板 statType='sum'（count 字段输出计数）对提交明细求和",
        "description": "跳过缺失值，不补零；空样本返回 null。",
    },
    {
        "code": "FIELD_AVG", "name": "数值字段均值", "category": "field", "unit": "",
        "formula": "字段求和 / 有效样本数",
        "description": "有效样本为 0 时不计算，返回 null。",
    },
    {
        "code": "PERIOD_GROWTH", "name": "周期增长率", "category": "trend", "unit": "%",
        "formula": "(本期 - 上期) / 上期",
        "description": "上期为 0 或缺失时不计算；周期未结束标记 incomplete。",
    },
)

_FIELD_STAT_TYPES = ("none", "sum", "count", "avg")


def definitions():
    """返回指标定义的浅拷贝，供注册表落库与接口展示。"""
    return [dict(d, version=METRIC_VERSION) for d in METRIC_DEFINITIONS]


def definition_map():
    return {d["code"]: d for d in METRIC_DEFINITIONS}


def stat_type(field):
    """字段统计语义：优先 statType，兼容 P2 之前的 aggregate 配置。"""
    if not isinstance(field, dict):
        return "none"
    value = field.get("statType")
    if value in _FIELD_STAT_TYPES:
        return value
    aggregate = field.get("aggregate")
    if isinstance(aggregate, dict) and aggregate.get("enabled"):
        method = aggregate.get("method")
        if method in ("sum", "count", "avg"):
            return method
    return "none"


def as_number(value):
    """严格数值解析：空值、布尔、非数字文本一律返回 None（调用方不得补零）。"""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _round(value, digits=4):
    return None if value is None else round(value, digits)


def _rate_text(rate):
    return "数据不足" if rate is None else "%.1f%%" % (rate * 100)


def _overall(days):
    expected = sum(len(d.get("expected") or []) for d in days)
    submitted = sum(len(d.get("submitted") or []) for d in days)
    rate = (submitted / expected) if expected else None
    return expected, submitted, rate


def _field_acc(dataset):
    """按模板字段建立累加器；口径来自模板版本快照，不看当前草稿。"""
    fields = dataset.get("fields") or {}
    acc = {}
    for key in sorted(fields):
        meta = fields[key] or {}
        method = stat_type(meta)
        if method == "none":
            continue
        acc[key] = {
            "fieldKey": key,
            "label": meta.get("label") or key,
            "unit": meta.get("unit") or "",
            "method": method,
            "sum": 0.0,
            "count": 0,
            "samples": 0,
        }
    return acc


def _field_rows(dataset):
    """计算字段级 sum/count/有效样本数；仅统计 submitted 明细。"""
    acc = _field_acc(dataset)
    if not acc:
        return []
    for entry in dataset.get("entries") or []:
        if entry.get("status") != "submitted":
            continue
        for row in entry.get("form_data") or []:
            values = row.get("values") if isinstance(row, dict) else None
            if not isinstance(values, dict):
                continue
            for key, item in acc.items():
                raw = values.get(key)
                if raw is None or raw == "":
                    continue
                if item["method"] == "count":
                    item["count"] += 1
                    item["samples"] += 1
                    continue
                num = as_number(raw)
                if num is None:
                    continue
                item["sum"] += num
                item["count"] += 1
                item["samples"] += 1
    rows = []
    for key in sorted(acc):
        item = acc[key]
        if item["samples"] <= 0:
            value = None
        elif item["method"] == "avg":
            value = item["sum"] / item["count"] if item["count"] else None
        elif item["method"] == "count":
            value = item["count"]
        else:
            value = item["sum"]
        rows.append({
            "fieldKey": key,
            "label": item["label"],
            "unit": item["unit"],
            "method": item["method"],
            "value": _round(value, 2),
            "samples": item["samples"],
            "valueText": "数据不足" if value is None else ("%s" % _round(value, 2)),
        })
    return rows


def _growth_value(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous


def _growth_state(current, previous, incomplete):
    if incomplete:
        return "incomplete"
    if current is None or previous is None or previous == 0:
        return "no_baseline"
    return "ok"


def _growth(dataset, current_rows):
    previous = dataset.get("previous") or {}
    prev_days = previous.get("days") or []
    incomplete = bool(dataset.get("to")) and bool(dataset.get("today")) \
        and dataset["to"] > dataset["today"]
    items = []

    _, _, cur_rate = _overall(dataset.get("days") or [])
    _, _, prev_rate = _overall(prev_days)
    items.append({
        "fieldKey": "SUBMIT_RATE",
        "label": "提交率",
        "unit": "%",
        "current": _round(cur_rate),
        "previous": _round(prev_rate),
        "growth": _round(_growth_value(cur_rate, prev_rate)),
        "state": _growth_state(cur_rate, prev_rate, incomplete),
    })

    prev_rows = {r["fieldKey"]: r for r in _field_rows(previous)}
    for row in current_rows:
        if row["method"] != "sum":
            continue
        before = prev_rows.get(row["fieldKey"])
        prev_value = before["value"] if before else None
        items.append({
            "fieldKey": row["fieldKey"],
            "label": row["label"],
            "unit": row["unit"],
            "current": row["value"],
            "previous": prev_value,
            "growth": _round(_growth_value(row["value"], prev_value)),
            "state": _growth_state(row["value"], prev_value, incomplete),
        })
    return items


def compute(dataset):
    """返回结构化指标结果；同一输入多次调用结果完全一致。"""
    days = dataset.get("days") or []
    expected, submitted, rate = _overall(days)
    field_rows = _field_rows(dataset)
    growth_items = _growth(dataset, field_rows)

    daily = []
    for day in days:
        day_expected = len(day.get("expected") or [])
        day_submitted = len(day.get("submitted") or [])
        day_rate = (day_submitted / day_expected) if day_expected else None
        daily.append({
            "date": day.get("date"),
            "expectedCount": day_expected,
            "submittedCount": day_submitted,
            "rate": _round(day_rate),
            "rateText": _rate_text(day_rate),
            "source": day.get("source"),
        })

    metrics = [
        {
            "code": "SUBMIT_RATE", "name": "提交率", "unit": "%",
            "value": _round(rate),
            "valueText": _rate_text(rate),
            "state": "ok" if rate is not None else "no_data",
        },
        {
            "code": "SUBMIT_COUNT", "name": "已提交人数", "unit": "人次",
            "value": submitted,
            "valueText": "%d 人次" % submitted,
        },
        {
            "code": "EXPECTED_COUNT", "name": "应提交人数", "unit": "人次",
            "value": expected,
            "valueText": "%d 人次" % expected,
        },
        {
            "code": "FIELD_SUM", "name": "数值字段合计",
            "value": None,
            "fields": [r for r in field_rows if r["method"] in ("sum", "count")],
        },
        {
            "code": "FIELD_AVG", "name": "数值字段均值",
            "value": None,
            "fields": [r for r in field_rows if r["method"] == "avg"],
        },
        {
            "code": "PERIOD_GROWTH", "name": "周期增长率", "unit": "%",
            "value": None,
            "growth": growth_items,
        },
    ]

    return {
        "metricVersion": METRIC_VERSION,
        "overall": {
            "expectedCount": expected,
            "submittedCount": submitted,
            "submitRate": _round(rate),
            "submitRateText": _rate_text(rate),
        },
        "metrics": metrics,
        "daily": daily,
        "growth": growth_items,
    }
