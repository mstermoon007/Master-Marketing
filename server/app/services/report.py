"""结构化报告拼接（升级文档 §8.3）。

只使用已计算出的指标、规则发现与质量检查结果拼文本：
- 不生成任何未在数据中出现的描述；
- 数据不足时明确输出"数据不足，暂不生成结论"，不补零、不推测；
- 报告头固定携带周期、快照时间、指标版本、规则版本、执行号，便于追溯。
"""

LEVEL_TEXT = {"critical": "严重", "warning": "预警", "info": "提示"}


def _num(value, digits=2):
    if value is None:
        return "数据不足"
    if isinstance(value, float):
        text = ("%." + str(digits) + "f") % value
        return text.rstrip("0").rstrip(".") if "." in text else text
    return str(value)


def _field_line(item):
    unit = item.get("unit") or ""
    label = item.get("label") or item.get("fieldKey")
    if item.get("value") is None:
        return "- %s%s：数据不足（无有效样本）" % (label, "（%s）" % unit if unit else "")
    return "- %s%s：%s（有效样本 %d）" % (
        label, "（%s）" % unit if unit else "", _num(item.get("value")), item.get("samples") or 0)


def build(team_name, dataset, payload, meta):
    """team_name 仅用于展示；meta 含 snapshotTime/metricVersion/ruleVersion/executionId。"""
    title = team_name or dataset.get("teamId") or ""
    lines = [
        "【分析报告】%s · %s 至 %s" % (title, dataset.get("from"), dataset.get("to")),
        "数据快照：%s · 指标版本 v%s · 规则版本 v%s · 执行号：%s" % (
            meta.get("snapshotTime"), meta.get("metricVersion"),
            meta.get("ruleVersion"), meta.get("executionId"),
        ),
        "",
        "一、提交情况",
    ]

    overall = payload.get("overall") or {}
    if not overall.get("expectedCount"):
        lines.append("数据不足，暂不生成结论。")
    else:
        lines.append("应提交 %d 人次，已提交 %d 人次，提交率 %s。" % (
            overall.get("expectedCount"), overall.get("submittedCount"),
            overall.get("submitRateText"),
        ))

    metric_map = {m.get("code"): m for m in payload.get("metrics") or []}
    lines.extend(["", "二、字段指标"])
    sum_fields = (metric_map.get("FIELD_SUM") or {}).get("fields") or []
    avg_fields = (metric_map.get("FIELD_AVG") or {}).get("fields") or []
    if not sum_fields and not avg_fields:
        lines.append("本期没有配置统计语义的模板字段。")
    else:
        for item in sum_fields:
            lines.append(_field_line(item))
        for item in avg_fields:
            lines.append(_field_line(item))

    lines.extend(["", "三、趋势"])
    growth = payload.get("growth") or []
    usable = [g for g in growth if g.get("state") != "no_baseline"]
    if not usable:
        lines.append("缺少上期基线，暂不计算增长率。")
    else:
        for item in usable:
            suffix = "（周期未结束，仅作参考）" if item.get("state") == "incomplete" else ""
            lines.append("- %s：本期 %s，上期 %s，增长率 %s%s" % (
                item.get("label"), _num(item.get("current")), _num(item.get("previous")),
                ("%.1f%%" % (item["growth"] * 100)) if item.get("growth") is not None else "数据不足",
                suffix,
            ))

    lines.extend(["", "四、异常与提醒"])
    findings = payload.get("findings") or []
    if not findings:
        lines.append("未触发任何规则。")
    else:
        for finding in findings[:200]:
            lines.append("- [%s] %s" % (
                LEVEL_TEXT.get(finding.get("level"), finding.get("level")),
                finding.get("title"),
            ))
        if len(findings) > 200:
            lines.append("- 其余 %d 条见发现列表。" % (len(findings) - 200))

    lines.extend(["", "五、数据质量"])
    checks = (payload.get("quality") or {}).get("checks") or []
    issues = [c for c in checks if c.get("count")]
    if not issues:
        lines.append("未发现缺失、重复、类型或单位问题。")
    else:
        for check in issues:
            lines.append("- %s" % check.get("message"))

    lines.extend(["", "本报告由确定性规则拼接生成，不含模型推断。"])
    return "\n".join(lines)
