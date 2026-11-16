"""P3 确定性分析引擎回归：指标口径、规则阈值、幂等与只读边界。

全部为纯函数测试或 monkeypatch 隔离，不依赖真实 MySQL：
    cd server && python3 -m pytest -q
"""
import json
from pathlib import Path

import pytest

from app.services import dataset as dataset_service
from app.services import engine, metrics, report, rules

SERVICES_DIR = Path(__file__).resolve().parent.parent / "app" / "services"

M1 = {"user_id": "u1", "name": "张三", "role": "member", "status": "active"}
M2 = {"user_id": "u2", "name": "李四", "role": "member", "status": "active"}

FIELDS = {
    "visits": {
        "fieldKey": "visits", "label": "到访", "unit": "次", "statType": "sum",
        "type": "integer", "version": 1, "units": ["次"],
    },
    "score": {
        "fieldKey": "score", "label": "评分", "unit": "分", "statType": "avg",
        "type": "decimal", "version": 1, "units": ["分"],
    },
}


def _entry(uid, day, values, status="submitted"):
    return {
        "user_id": uid, "entry_date": day, "status": status,
        "form_data": [{"rowId": "r1", "values": values}],
    }


def _day(day, expected, submitted, source="task"):
    return {
        "date": day, "expected": list(expected),
        "submitted": list(submitted), "source": source,
    }


def _dataset(days, entries=(), fields=None, previous_days=None,
             previous_entries=(), to_day="2026-11-11", today="2026-11-16"):
    fields = FIELDS if fields is None else fields
    return {
        "teamId": "T1",
        "from": "2026-11-10",
        "to": to_day,
        "today": today,
        "members": [M1, M2],
        "templates": [],
        "tasks": [],
        "entries": list(entries),
        "fields": fields,
        "days": days,
        "previous": {
            "from": "2026-11-08",
            "to": "2026-11-09",
            "entries": list(previous_entries),
            "fields": fields,
            "days": previous_days or [],
        },
    }


def _metric(payload, code):
    return next(m for m in payload["metrics"] if m["code"] == code)


# ---------------------------------------------------------------- 指标口径

def test_metric_registry_has_six_codes_and_unique_versions():
    codes = [d["code"] for d in metrics.definitions()]
    assert codes == [
        "SUBMIT_RATE", "SUBMIT_COUNT", "EXPECTED_COUNT",
        "FIELD_SUM", "FIELD_AVG", "PERIOD_GROWTH",
    ]
    assert len(codes) == len(set(codes))


def test_zero_denominator_returns_null_not_exception():
    payload = metrics.compute(_dataset([_day("2026-11-10", [], [])]))
    assert payload["overall"]["expectedCount"] == 0
    assert payload["overall"]["submitRate"] is None
    assert payload["overall"]["submitRateText"] == "数据不足"
    assert payload["daily"][0]["rate"] is None
    assert payload["daily"][0]["rateText"] == "数据不足"


def test_submit_rate_counts_only_expected_scope():
    ds = _dataset([
        _day("2026-11-10", [M1, M2], ["u1"]),
        _day("2026-11-11", [M1], ["u1"]),
    ])
    payload = metrics.compute(ds)
    assert payload["overall"]["expectedCount"] == 3
    assert payload["overall"]["submittedCount"] == 2
    assert payload["overall"]["submitRate"] == round(2 / 3, 4)
    assert _metric(payload, "SUBMIT_COUNT")["valueText"] == "2 人次"


def test_missing_values_are_skipped_and_never_zero_filled():
    ds = _dataset(
        [_day("2026-11-10", [M1, M2], ["u1", "u2"])],
        entries=[
            _entry("u1", "2026-11-10", {"visits": 10}),
            _entry("u2", "2026-11-10", {"visits": ""}),
        ],
    )
    field = _metric(metrics.compute(ds), "FIELD_SUM")["fields"][0]
    assert field["value"] == 10
    assert field["samples"] == 1


def test_no_samples_returns_null_not_zero():
    ds = _dataset([_day("2026-11-10", [M1], [])])
    field = _metric(metrics.compute(ds), "FIELD_SUM")["fields"][0]
    assert field["value"] is None
    assert field["samples"] == 0
    assert field["valueText"] == "数据不足"


def test_field_avg_divides_by_valid_samples_only():
    ds = _dataset(
        [_day("2026-11-10", [M1, M2], ["u1", "u2"])],
        entries=[
            _entry("u1", "2026-11-10", {"score": 10}),
            _entry("u2", "2026-11-10", {"score": 20}),
            _entry("u2", "2026-11-10", {"score": ""}),
        ],
    )
    field = _metric(metrics.compute(ds), "FIELD_AVG")["fields"][0]
    assert field["value"] == 15
    assert field["samples"] == 2


def test_non_numeric_value_is_excluded_and_reported_as_quality_issue():
    ds = _dataset(
        [_day("2026-11-10", [M1, M2], ["u1", "u2"])],
        entries=[
            _entry("u1", "2026-11-10", {"visits": 10}),
            _entry("u2", "2026-11-10", {"visits": "十次"}),
        ],
    )
    quality = dataset_service.build_quality(ds)
    assert quality["typeIssueCount"] == 1
    assert quality["refs"]["type"][0]["fieldKey"] == "visits"
    field = _metric(metrics.compute(ds), "FIELD_SUM")["fields"][0]
    assert field["value"] == 10


def test_growth_compares_previous_equal_period():
    prev = [
        _day("2026-11-08", [M1, M2], ["u1", "u2"]),
        _day("2026-11-09", [M1, M2], ["u1", "u2"]),
    ]
    prev_entries = [
        _entry("u1", "2026-11-08", {"visits": 25}),
        _entry("u2", "2026-11-09", {"visits": 25}),
    ]
    ds = _dataset(
        [_day("2026-11-10", [M1, M2], ["u1", "u2"]),
         _day("2026-11-11", [M1, M2], ["u1", "u2"])],
        entries=[
            _entry("u1", "2026-11-10", {"visits": 50}),
            _entry("u2", "2026-11-11", {"visits": 50}),
        ],
        previous_days=prev,
        previous_entries=prev_entries,
    )
    payload = metrics.compute(ds)
    rate_growth = next(g for g in payload["growth"] if g["fieldKey"] == "SUBMIT_RATE")
    field_growth = next(g for g in payload["growth"] if g["fieldKey"] == "visits")
    assert rate_growth["current"] == 1.0 and rate_growth["previous"] == 1.0
    assert rate_growth["growth"] == 0
    assert field_growth["current"] == 100
    assert field_growth["previous"] == 50
    assert field_growth["growth"] == 1.0


def test_growth_without_baseline_is_not_computed():
    ds = _dataset(
        [_day("2026-11-10", [M1], ["u1"])],
        entries=[_entry("u1", "2026-11-10", {"visits": 10})],
        previous_days=[],
    )
    payload = metrics.compute(ds)
    field_growth = next(g for g in payload["growth"] if g["fieldKey"] == "visits")
    assert field_growth["previous"] is None
    assert field_growth["growth"] is None
    assert field_growth["state"] == "no_baseline"


def test_growth_marks_incomplete_period():
    ds = _dataset(
        [_day("2026-11-10", [M1], ["u1"])],
        entries=[_entry("u1", "2026-11-10", {"visits": 10})],
        to_day="2026-11-30",
        today="2026-11-16",
    )
    payload = metrics.compute(ds)
    field_growth = next(g for g in payload["growth"] if g["fieldKey"] == "visits")
    assert field_growth["state"] == "incomplete"


def test_same_input_produces_identical_output():
    ds = _dataset(
        [_day("2026-11-10", [M1, M2], ["u1"])],
        entries=[_entry("u1", "2026-11-10", {"visits": 10, "score": 4})],
    )
    first = json.dumps(metrics.compute(ds), sort_keys=True, ensure_ascii=False)
    second = json.dumps(metrics.compute(ds), sort_keys=True, ensure_ascii=False)
    assert first == second


# ---------------------------------------------------------------- 规则阈值

def _payload(ds, params=None):
    payload = metrics.compute(ds)
    payload["quality"] = dataset_service.build_quality(ds)
    payload["daily"] = payload["daily"]
    findings = rules.evaluate(ds, payload, params or {})
    return payload, findings


def test_low_submission_rate_rule_triggers_below_threshold_only():
    ds = _dataset([
        _day("2026-11-10", [M1, M2], ["u1"]),   # 50%
        _day("2026-11-11", [M1, M2], ["u1", "u2"]),  # 100%
    ])
    _, findings = _payload(ds)
    low = [f for f in findings if f["ruleCode"] == "SUBMISSION_RATE_LOW_01"]
    assert len(low) == 1
    assert low[0]["detail"]["date"] == "2026-11-10"


def test_low_submission_rate_threshold_is_configurable():
    ds = _dataset([_day("2026-11-10", [M1, M2], ["u1", "u2"])])
    _, findings = _payload(ds, {"SUBMISSION_RATE_LOW_01": {"threshold": 1.01}})
    assert len([f for f in findings if f["ruleCode"] == "SUBMISSION_RATE_LOW_01"]) == 1


def test_metric_drop_rule_respects_threshold_and_skips_no_baseline():
    ds = _dataset(
        [_day("2026-11-10", [M1], ["u1"])],
        entries=[_entry("u1", "2026-11-10", {"visits": 70})],
        previous_days=[_day("2026-11-09", [M1], ["u1"])],
        previous_entries=[_entry("u1", "2026-11-09", {"visits": 100})],
    )
    _, findings = _payload(ds)
    drops = [f for f in findings if f["ruleCode"] == "METRIC_DROP_01"]
    assert len(drops) == 1
    assert drops[0]["detail"]["fieldKey"] == "visits"

    # 恰好等于阈值不触发
    ds_ok = _dataset(
        [_day("2026-11-10", [M1], ["u1"])],
        entries=[_entry("u1", "2026-11-10", {"visits": 80})],
        previous_days=[_day("2026-11-09", [M1], ["u1"])],
        previous_entries=[_entry("u1", "2026-11-09", {"visits": 100})],
    )
    _, findings_ok = _payload(ds_ok)
    assert not [f for f in findings_ok if f["ruleCode"] == "METRIC_DROP_01"]


def test_missing_data_rule_aggregates_per_member():
    ds = _dataset([
        _day("2026-11-10", [M1, M2], ["u1"]),
        _day("2026-11-11", [M1, M2], ["u1"]),
    ])
    _, findings = _payload(ds)
    missing = [f for f in findings if f["ruleCode"] == "MISSING_DATA_01"]
    assert len(missing) == 1
    assert missing[0]["detail"]["userId"] == "u2"
    assert missing[0]["detail"]["missingDays"] == 2
    assert missing[0]["dataRefs"]["dates"] == ["2026-11-10", "2026-11-11"]


def test_draft_entry_is_not_counted_as_submitted():
    ds = _dataset(
        [_day("2026-11-10", [M1], [])],
        entries=[_entry("u1", "2026-11-10", {"visits": 10}, status="draft")],
    )
    payload = metrics.compute(ds)
    assert payload["overall"]["submittedCount"] == 0
    assert _metric(payload, "FIELD_SUM")["fields"][0]["value"] is None


# ---------------------------------------------------------------- 报告

def test_report_states_insufficient_data_without_speculation():
    ds = _dataset([_day("2026-11-10", [], [])])
    payload = metrics.compute(ds)
    payload["quality"] = dataset_service.build_quality(ds)
    payload["findings"] = rules.evaluate(ds, payload, {})
    text = report.build("销售一队", ds, payload, {
        "snapshotTime": "2026-11-16T00:00:00.000Z",
        "metricVersion": 1, "ruleVersion": 1, "executionId": "exec-1",
    })
    assert "数据不足，暂不生成结论" in text
    assert "指标版本 v1" in text
    assert "规则版本 v1" in text
    assert "执行号：exec-1" in text
    assert "不含模型推断" in text


# ---------------------------------------------------------------- 只读与幂等

def test_engine_write_guard_rejects_business_tables():
    for table in ("daily_entries", "form_templates", "members", "teams", "report_tasks"):
        with pytest.raises(RuntimeError, match="禁止写入业务表"):
            engine._insert(None, table, {})
        with pytest.raises(RuntimeError, match="禁止写入业务表"):
            engine._update(None, table, "id", {})


def test_readonly_modules_never_reference_write_or_model_clients():
    for name in ("dataset.py", "metrics.py", "rules.py", "report.py"):
        source = (SERVICES_DIR / name).read_text("utf-8")
        for forbidden in ("db.insert(", "db.update(", "db.remove(", "db.execute("):
            assert forbidden not in source, "%s 不应包含写操作 %s" % (name, forbidden)
        lowered = source.lower()
        for forbidden in ("openai", "anthropic", "deepseek", "requests.post", "httpx"):
            assert forbidden not in lowered, "%s 不应引入模型/网络调用" % name


def test_run_reuses_successful_task_and_does_not_write_again(monkeypatch):
    task = {
        "id": "task-1", "team_id": "T1", "analysis_type": "period",
        "period_start": "2026-11-10", "period_end": "2026-11-11",
        "status": "success", "metric_version": 1, "rule_version": 1,
    }
    monkeypatch.setattr(engine, "ensure_registry", lambda conn: None)
    monkeypatch.setattr(engine, "_runtime", lambda conn: (1, 1, {}))
    monkeypatch.setattr(engine, "_lock_task", lambda *a, **k: task)
    monkeypatch.setattr(engine, "_view", lambda conn, row, reused: {
        "task": {"id": row["id"]}, "reused": reused,
    })

    def boom(*a, **k):
        raise AssertionError("重复执行不应再次写入")

    monkeypatch.setattr(engine, "_insert", boom)
    monkeypatch.setattr(engine, "_update", boom)
    result = engine.run(None, "T1", "2026-11-10", "2026-11-11", "u1")
    assert result == {"task": {"id": "task-1"}, "reused": True}


def test_failed_execution_marks_task_failed_and_reraises(monkeypatch):
    updates = []
    monkeypatch.setattr(engine, "db", type("DB", (), {
        "now_iso": staticmethod(lambda: "2026-11-16T00:00:00.000Z"),
        "gen_id": staticmethod(lambda: "exec-test"),
        "update": staticmethod(lambda conn, table, doc_id, patch: updates.append(
            (table, doc_id, patch))),
    }))
    monkeypatch.setattr(engine.dataset_service, "load_dataset",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    task = {
        "id": "task-2", "team_id": "T1", "analysis_type": "period",
        "period_start": "2026-11-10", "period_end": "2026-11-11",
        "status": "running", "metric_version": 1, "rule_version": 1,
    }
    with pytest.raises(RuntimeError, match="boom"):
        engine._execute(None, task, {})
    assert updates[-1][0] == "analysis_tasks"
    assert updates[-1][2]["status"] == "failed"
    assert "boom" in updates[-1][2]["error_message"]
