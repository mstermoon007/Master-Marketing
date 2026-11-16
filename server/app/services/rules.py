"""规则判断引擎（升级文档 §8.2）。

首批 3 条规则，阈值全部来自 analysis_rules.params，代码内只保留默认值兜底：
- SUBMISSION_RATE_LOW_01：当日提交率低于阈值；
- METRIC_DROP_01：本期指标低于上期 × 阈值；
- MISSING_DATA_01：周期内应提交但无记录（按成员聚合）。

本模块纯函数、无数据库访问；每条发现都带 rule_code 与 data_refs，可回溯。
"""

RULE_VERSION = 1

RULE_DEFINITIONS = (
    {
        "code": "SUBMISSION_RATE_LOW_01", "name": "当日提交率偏低", "level": "warning",
        "condition": "当日提交率 < 阈值（默认 80%）",
        "description": "提醒团队负责人跟进未提交成员；分母为 0 的日期不触发。",
        "params": {"threshold": 0.8},
    },
    {
        "code": "METRIC_DROP_01", "name": "指标环比明显下降", "level": "warning",
        "condition": "本期指标 < 上期 × 阈值（默认 80%）",
        "description": "上期为 0 或缺失时不判断，避免把无基线当作下跌。",
        "params": {"threshold": 0.8},
    },
    {
        "code": "MISSING_DATA_01", "name": "应提交但无记录", "level": "info",
        "condition": "周期内应提交但无提交记录",
        "description": "按成员聚合缺失日期；草稿不计为已提交。",
        "params": {},
    },
)

_LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}


def definitions():
    return [
        dict(d, params=dict(d.get("params") or {}), version=RULE_VERSION)
        for d in RULE_DEFINITIONS
    ]


def _params(params_by_code, code):
    merged = dict(next(d for d in RULE_DEFINITIONS if d["code"] == code).get("params") or {})
    supplied = (params_by_code or {}).get(code) or {}
    if isinstance(supplied, dict):
        merged.update(supplied)
    return merged


def _threshold(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.8


def _submission_rate_low(payload, params_by_code, rule_version):
    threshold = _threshold(_params(params_by_code, "SUBMISSION_RATE_LOW_01").get("threshold"))
    findings = []
    for day in payload.get("daily") or []:
        rate = day.get("rate")
        if day.get("expectedCount", 0) <= 0 or rate is None or rate >= threshold:
            continue
        findings.append({
            "ruleCode": "SUBMISSION_RATE_LOW_01",
            "ruleVersion": rule_version,
            "level": "warning",
            "findingCode": "SUBMISSION_RATE_LOW_01:" + str(day.get("date")),
            "title": "%s 提交率 %.1f%%，低于阈值 %.0f%%" % (
                day.get("date"), rate * 100, threshold * 100),
            "detail": {
                "date": day.get("date"),
                "expectedCount": day.get("expectedCount"),
                "submittedCount": day.get("submittedCount"),
                "rate": rate,
                "threshold": threshold,
            },
            "dataRefs": {"date": day.get("date")},
        })
    return findings


def _metric_drop(payload, params_by_code, rule_version):
    threshold = _threshold(_params(params_by_code, "METRIC_DROP_01").get("threshold"))
    findings = []
    for item in payload.get("growth") or []:
        current = item.get("current")
        previous = item.get("previous")
        if item.get("state") != "ok" or current is None or previous is None or previous <= 0:
            continue
        if current >= previous * threshold:
            continue
        findings.append({
            "ruleCode": "METRIC_DROP_01",
            "ruleVersion": rule_version,
            "level": "warning",
            "findingCode": "METRIC_DROP_01:" + str(item.get("fieldKey")),
            "title": "%s 环比下降 %.1f%%，低于上期的 %.0f%%" % (
                item.get("label"), item.get("growth", 0) * 100, threshold * 100),
            "detail": {
                "fieldKey": item.get("fieldKey"),
                "label": item.get("label"),
                "current": current,
                "previous": previous,
                "growth": item.get("growth"),
                "threshold": threshold,
            },
            "dataRefs": {"fieldKey": item.get("fieldKey")},
        })
    return findings


def _missing_data(dataset, rule_version):
    missing = {}
    for day in dataset.get("days") or []:
        submitted = set(day.get("submitted") or [])
        for member in day.get("expected") or []:
            uid = member.get("user_id")
            if uid in submitted:
                continue
            item = missing.setdefault(uid, {
                "userId": uid, "name": member.get("name") or "", "dates": [],
            })
            item["dates"].append(day.get("date"))

    findings = []
    for uid in sorted(missing, key=lambda u: (missing[u]["name"], u)):
        item = missing[uid]
        dates = sorted(item["dates"])
        findings.append({
            "ruleCode": "MISSING_DATA_01",
            "ruleVersion": rule_version,
            "level": "info",
            "findingCode": "MISSING_DATA_01:" + str(uid),
            "title": "%s 有 %d 天应提交但无记录" % (item["name"] or uid, len(dates)),
            "detail": {
                "userId": uid,
                "name": item["name"],
                "missingDays": len(dates),
            },
            "dataRefs": {"dates": dates[:60], "truncated": len(dates) > 60},
        })
    return findings


def evaluate(dataset, payload, params_by_code=None, rule_version=RULE_VERSION):
    """执行全部启用规则，返回确定性排序的发现列表。"""
    findings = []
    findings.extend(_submission_rate_low(payload, params_by_code, rule_version))
    findings.extend(_metric_drop(payload, params_by_code, rule_version))
    findings.extend(_missing_data(dataset, rule_version))
    findings.sort(key=lambda f: (
        _LEVEL_ORDER.get(f.get("level"), 9), str(f.get("findingCode")),
    ))
    return findings
