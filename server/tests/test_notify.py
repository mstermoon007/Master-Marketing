"""P6 消息通知：去重抢键、dry-run、微信错误码、订阅设置与运行监控。"""
import pytest

from app.handlers import BusinessError
from app.handlers import notify as notify_handler
from app.services import notify

# ---------------------------------------------------------------- 投递去重与状态

def test_notify_claims_dedupe_key(monkeypatch):
    """同一 (user, type, period) 抢不到唯一键即视为已处理，不重复调用微信。"""
    monkeypatch.setattr(notify.db, "execute", lambda *a, **k: 0)
    calls = []
    monkeypatch.setattr(notify.wechat, "send_subscribe_message",
                        lambda *a, **k: calls.append(a) or {"errcode": 0})

    result = notify.notify_user(
        None, "u1", notify.DAILY_REMIND, "daily:2026-11-18",
        "销售团队", "今日填报提醒", "2026-11-18",
    )
    assert result["status"] == "duplicate"
    assert calls == []


def test_dedupe_scope_separates_teams(monkeypatch):
    """同一用户在不同团队的通知互不吞并：scope_key 取团队 id。"""
    captured = []
    monkeypatch.setattr(notify.db, "execute",
                        lambda conn, sql, args=None: captured.append(args) or 1)
    monkeypatch.setattr(notify.db, "update", lambda *a, **k: 1)
    monkeypatch.setattr(notify, "template_id", lambda notify_type: "")

    for team_id in ("T1", "T2"):
        notify.notify_user(
            None, "u1", notify.DAILY_REMIND, "daily:2026-11-18",
            "团队" + team_id, "今日填报提醒", "2026-11-18",
            team_id=team_id, workspace_id="W1",
        )

    assert [args[3] for args in captured] == ["T1", "T2"]


def test_dedupe_scope_falls_back_to_workspace(monkeypatch):
    """无团队维度的通知（如异常预警跨团队）退回空间 id 作为作用域。"""
    captured = []
    monkeypatch.setattr(notify.db, "execute",
                        lambda conn, sql, args=None: captured.append(args) or 1)
    monkeypatch.setattr(notify.db, "update", lambda *a, **k: 1)
    monkeypatch.setattr(notify, "template_id", lambda notify_type: "")

    notify.notify_user(
        None, "u1", notify.ANOMALY_ALERT, "anomaly:task-1",
        "空间", "异常预警", "2026-11-18", workspace_id="W1",
    )

    assert captured[0][3] == "W1"


def test_no_template_records_skipped_without_calling_wechat(monkeypatch):
    updates = []
    monkeypatch.setattr(notify.db, "execute", lambda *a, **k: 1)
    monkeypatch.setattr(notify.db, "update",
                        lambda conn, table, doc_id, patch: updates.append(patch))
    monkeypatch.setattr(notify, "template_id", lambda notify_type: "")
    calls = []
    monkeypatch.setattr(notify.wechat, "send_subscribe_message",
                        lambda *a, **k: calls.append(a))

    result = notify.notify_user(
        None, "u1", notify.DAILY_REMIND, "daily:2026-11-18",
        "销售团队", "今日填报提醒", "2026-11-18",
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "no_template"
    assert updates[-1]["status"] == "skipped"
    assert "未配置" in updates[-1]["error_message"]
    assert calls == []


def _patch_send(monkeypatch, errcode):
    updates = []
    monkeypatch.setattr(notify.db, "execute", lambda *a, **k: 1)
    monkeypatch.setattr(notify.db, "update",
                        lambda conn, table, doc_id, patch: updates.append(patch))
    monkeypatch.setattr(notify, "template_id", lambda notify_type: "tmpl-1")
    monkeypatch.setattr(notify, "settings_enabled", lambda *a, **k: True)
    monkeypatch.setattr(notify.wechat, "send_subscribe_message",
                        lambda *a, **k: {"errcode": errcode, "errmsg": "x"})
    return updates


def test_wechat_43101_is_skipped_not_failed(monkeypatch):
    updates = _patch_send(monkeypatch, 43101)
    result = notify.notify_user(
        None, "u1", notify.DAILY_REMIND, "daily:2026-11-18",
        "销售团队", "今日填报提醒", "2026-11-18",
    )
    assert result["status"] == "skipped"
    assert updates[-1]["status"] == "skipped"
    assert "未订阅" in updates[-1]["error_message"]


def test_wechat_success_marks_sent(monkeypatch):
    updates = _patch_send(monkeypatch, 0)
    result = notify.notify_user(
        None, "u1", notify.DAILY_REMIND, "daily:2026-11-18",
        "销售团队", "今日填报提醒", "2026-11-18",
    )
    assert result["status"] == "sent"
    assert updates[-1]["status"] == "sent"
    assert updates[-1]["sent_at"]


def test_wechat_other_errcode_marks_failed(monkeypatch):
    updates = _patch_send(monkeypatch, 40003)
    result = notify.notify_user(
        None, "u1", notify.DAILY_REMIND, "daily:2026-11-18",
        "销售团队", "今日填报提醒", "2026-11-18",
    )
    assert result["status"] == "failed"
    assert updates[-1]["status"] == "failed"
    assert "40003" in updates[-1]["error_message"]


def test_unsubscribed_user_is_skipped(monkeypatch):
    updates = _patch_send(monkeypatch, 0)
    monkeypatch.setattr(notify, "settings_enabled", lambda *a, **k: False)
    result = notify.notify_user(
        None, "u1", notify.MISSING_REMIND, "missing:2026-11-18",
        "销售团队", "今日尚未提交", "2026-11-18",
    )
    assert result["status"] == "skipped"
    assert updates[-1]["status"] == "skipped"


# ---------------------------------------------------------------- 订阅设置

def test_save_setting_uses_upsert(monkeypatch):
    captured = {}
    monkeypatch.setattr(notify.db, "now_iso", lambda: "2026-11-18T00:00:00.000Z")
    monkeypatch.setattr(notify.db, "gen_id", lambda: "id-1")

    def fake_execute(conn, sql, args=None):
        captured["sql"] = sql
        captured["args"] = args
        return 1

    monkeypatch.setattr(notify.db, "execute", fake_execute)
    notify.save_setting(None, "W1", "u1", notify.DAILY_REMIND, True)
    assert "ON DUPLICATE KEY UPDATE" in captured["sql"]
    assert captured["args"] == ("id-1", "W1", "u1", "daily_remind", 1,
                                "2026-11-18T00:00:00.000Z")


def test_save_settings_normalizes_dict_and_granted(monkeypatch):
    saved = []
    monkeypatch.setattr(notify_handler, "_workspace_id", lambda *a, **k: "W1")
    monkeypatch.setattr(notify_handler.notify, "save_setting",
                        lambda conn, ws, uid, name, enabled: saved.append((name, enabled)))
    monkeypatch.setattr(notify_handler.notify, "list_settings", lambda *a, **k: [])
    monkeypatch.setattr(notify_handler, "audit", lambda *a, **k: None)

    notify_handler.save_notification_settings(None, "u1", {
        "settings": {"daily_remind": True, "unknown_type": True},
        "granted": ["due_remind"],
    })
    assert saved == [("daily_remind", True), ("due_remind", True)]


def test_save_settings_rejects_empty_payload(monkeypatch):
    monkeypatch.setattr(notify_handler, "_workspace_id", lambda *a, **k: "W1")
    with pytest.raises(BusinessError, match="没有可保存"):
        notify_handler.save_notification_settings(None, "u1", {"settings": {}})


# ---------------------------------------------------------------- 运行监控与权限

def test_runtime_monitor_aggregates(monkeypatch):
    monkeypatch.setattr(notify_handler, "_workspace_id", lambda *a, **k: "W1")
    monkeypatch.setattr(notify_handler, "require_workspace_role",
                        lambda *a, **k: ({}, {}))
    monkeypatch.setattr(notify_handler.scheduler, "status", lambda *a, **k: {
        "enabled": True, "running": True, "timezone": "Asia/Shanghai",
        "dailyRemindTime": "09:00", "missingRemindTime": "20:00",
        "remindBeforeMinutes": 30, "jobs": [],
    })

    analysis_queries = []

    def fake_query(conn, sql, args=None):
        if "FROM `analysis_tasks`" in sql:
            analysis_queries.append((sql, args))
            return [
                {"status": "success", "started_at": "2026-11-18T01:00:00.000Z",
                 "finished_at": "2026-11-18T01:00:02.000Z"},
                {"status": "failed", "started_at": None, "finished_at": None},
                {"status": "running", "started_at": None, "finished_at": None},
            ]
        return [
            {"notify_type": "daily_remind", "status": "sent", "c": 3},
            {"notify_type": "daily_remind", "status": "skipped", "c": 1},
            {"notify_type": "missing_remind", "status": "failed", "c": 2},
        ]

    monkeypatch.setattr(notify_handler.db, "query", fake_query)

    result = notify_handler.get_runtime_monitor(None, "u1", {"workspaceId": "W1"})
    assert result["analysis"]["total"] == 3
    assert result["analysis"]["success"] == 1
    assert result["analysis"]["failed"] == 1
    assert result["analysis"]["running"] == 1
    assert result["analysis"]["successRate"] == round(1 / 3, 4)
    assert result["analysis"]["avgDurationMs"] == 2000
    assert result["notifications"]["sent"] == 3
    assert result["notifications"]["skipped"] == 1
    assert result["notifications"]["failed"] == 2
    assert result["scheduler"]["running"] is True
    assert len(analysis_queries) == 1
    sql, args = analysis_queries[0]
    assert "JOIN" not in sql and "workspace_id = %s" in sql
    assert args[0] == "W1"


def test_logs_force_workspace_scope(monkeypatch):
    monkeypatch.setattr(notify_handler, "_workspace_id", lambda *a, **k: "W1")
    monkeypatch.setattr(notify_handler, "require_workspace_role",
                        lambda *a, **k: ({}, {}))
    captured = {}

    def fake_query(conn, sql, args=None):
        captured["sql"] = sql
        captured["args"] = args
        return []

    monkeypatch.setattr(notify_handler.db, "one", lambda *a, **k: {"c": 0})
    monkeypatch.setattr(notify_handler.db, "query", fake_query)

    result = notify_handler.list_notification_logs(None, "u1", {
        "workspaceId": "W1", "notifyType": "daily_remind",
        "status": "failed", "page": 1, "pageSize": 20,
    })
    assert "workspace_id = %s" in captured["sql"]
    assert captured["args"][0] == "W1"
    assert captured["args"][-2:] == (20, 20)
    assert result["total"] == 0


def test_logs_require_workspace_manager(monkeypatch):
    monkeypatch.setattr(notify_handler, "_workspace_id", lambda *a, **k: "W1")

    def deny(*a, **k):
        raise BusinessError("需要工作空间管理员权限")

    monkeypatch.setattr(notify_handler, "require_workspace_role", deny)
    with pytest.raises(BusinessError):
        notify_handler.list_notification_logs(None, "u1", {"workspaceId": "W1"})


# ---------------------------------------------------------------- 定时提醒与异常预警

def test_daily_reminder_only_notifies_unsubmitted(monkeypatch):
    monkeypatch.setattr(notify, "_teams", lambda conn: [
        {"team_id": "T1", "workspace_id": "W1", "name": "销售团队"},
    ])
    monkeypatch.setattr(notify.expected, "resolve_expected", lambda *a, **k: {
        "source": "task",
        "members": [{"user_id": "u1"}, {"user_id": "u2"}],
    })
    monkeypatch.setattr(notify, "_submitted_uids", lambda *a, **k: {"u1"})
    calls = []
    monkeypatch.setattr(notify, "notify_user",
                        lambda *a, **k: calls.append((a, k)) or {"status": "sent"})

    stats = notify.run_daily_reminders(None, "2026-11-18")
    assert stats["sent"] == 1
    assert calls[0][0][1] == "u2"
    assert calls[0][0][2] == notify.DAILY_REMIND


def test_anomaly_notification_only_for_warning_or_critical(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "_manager_uids", lambda *a, **k: ["m1", "m2"])
    monkeypatch.setattr(notify, "notify_user",
                        lambda *a, **k: calls.append((a, k)) or {"status": "sent"})

    info = notify.notify_anomalies(None, "T1", "task-1",
                                   [{"level": "info", "title": "提示"}],
                                   team_name="销售团队", workspace_id="W1")
    assert info["sent"] == 0 and calls == []

    result = notify.notify_anomalies(
        None, "T1", "task-1",
        [{"level": "warning", "title": "提交率下降"}, {"level": "info"}],
        team_name="销售团队", workspace_id="W1",
    )
    assert result["sent"] == 2
    assert calls[0][0][3] == "anomaly:task-1"


# ---------------------------------------------------------------- 调度心跳

def _fresh_iso(seconds_ago=0):
    from datetime import datetime, timedelta, timezone
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def test_status_falls_back_to_fresh_heartbeat(monkeypatch):
    """Web 进程不跑调度时，用独立容器的最近心跳判断「运行中」。"""
    from app.services import scheduler as sched

    monkeypatch.setattr(sched.config, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(sched, "_scheduler", None)
    monkeypatch.setattr(sched.db, "query", lambda *a, **k: [
        {"job_id": "p6_daily_remind", "job_name": "每日填报提醒",
         "next_run_at": "2026-11-19T09:00:00+08:00",
         "updated_at": _fresh_iso(10)},
        {"job_id": "p6_due_remind", "job_name": "截止前提醒",
         "next_run_at": "2026-11-18T10:05:00+08:00",
         "updated_at": _fresh_iso(20)},
    ])

    result = sched.status(object())
    assert result["running"] is True
    assert result["enabled"] is True
    assert result["source"] == "heartbeat"
    assert result["stale"] is False
    assert [job["id"] for job in result["jobs"]] == ["p6_daily_remind", "p6_due_remind"]


def test_status_marks_stale_heartbeat(monkeypatch):
    """心跳超过阈值未刷新视为调度未运行，但仍保留最后时间供排查。"""
    from app.services import scheduler as sched

    monkeypatch.setattr(sched.config, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(sched, "_scheduler", None)
    stale_at = _fresh_iso(sched.HEARTBEAT_STALE_SECONDS + 60)
    monkeypatch.setattr(sched.db, "query", lambda *a, **k: [
        {"job_id": "p6_daily_remind", "job_name": "每日填报提醒",
         "next_run_at": None, "updated_at": stale_at},
    ])

    result = sched.status(object())
    assert result["running"] is False
    assert result["enabled"] is False
    assert result["stale"] is True
    assert result["lastHeartbeatAt"] == stale_at


def test_status_without_heartbeat_stays_closed(monkeypatch):
    from app.services import scheduler as sched

    monkeypatch.setattr(sched.config, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(sched, "_scheduler", None)
    monkeypatch.setattr(sched.db, "query", lambda *a, **k: [])

    result = sched.status(object())
    assert result["running"] is False
    assert result["enabled"] is False
    assert result["stale"] is False
    assert result["lastHeartbeatAt"] is None
    assert result["jobs"] == []


def test_wait_for_db_retries_until_available(monkeypatch):
    """MySQL 初始化期短暂拒连时，调度进程应重试而不是直接启动。"""
    import contextlib

    from app.services import scheduler as sched

    attempts = []

    @contextlib.contextmanager
    def fake_connection():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("Connection refused")
        yield object()

    monkeypatch.setattr(sched.db, "connection", fake_connection)
    monkeypatch.setattr(sched.db, "one", lambda *a, **k: {"1": 1})
    monkeypatch.setattr(sched.time, "sleep", lambda *_: None)

    assert sched.wait_for_db(timeout=5, interval=0) is True
    assert len(attempts) == 3


def test_wait_for_db_gives_up_after_timeout(monkeypatch):
    """超时仍不可用返回 False，由调用方退出进程交给重启策略。"""
    from app.services import scheduler as sched

    class _Clock:
        now = 0.0

        def __call__(self):
            return self.now

    clock = _Clock()

    def fake_sleep(seconds):
        clock.now += seconds

    def refused():
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(sched.db, "connection", refused)
    monkeypatch.setattr(sched.time, "monotonic", clock)
    monkeypatch.setattr(sched.time, "sleep", fake_sleep)

    assert sched.wait_for_db(timeout=5, interval=2) is False


def test_with_conn_records_failure_on_separate_connection(monkeypatch):
    """作业抛错时主事务回滚，失败心跳必须另开连接写入。"""
    import contextlib

    from app.services import scheduler as sched

    @contextlib.contextmanager
    def fake_connection():
        yield object()

    recorded = []
    monkeypatch.setattr(sched.db, "connection", fake_connection)
    monkeypatch.setattr(sched, "_record_failure",
                        lambda job_id, message: recorded.append((job_id, message)))

    def boom(conn):
        raise ValueError("db down")

    assert sched.with_conn(boom, job_id="p6_due_remind")() is None
    assert recorded and recorded[0][0] == "p6_due_remind"
    assert "db down" in recorded[0][1]


def test_write_heartbeat_is_upsert(monkeypatch):
    """心跳按 job_id 收敛，重复刷新不会插入新行。"""
    from app.services import scheduler as sched

    captured = {}
    monkeypatch.setattr(sched.db, "now_iso", lambda: "2026-11-18T00:00:00.000Z")
    monkeypatch.setattr(sched.db, "gen_id", lambda: "id-1")

    def fake_execute(conn, sql, args=None):
        captured["sql"] = sql
        captured["args"] = args
        return 1

    monkeypatch.setattr(sched.db, "execute", fake_execute)
    sched.write_heartbeat(None, [("p6_daily_remind", "每日填报提醒", None)])

    assert "ON DUPLICATE KEY UPDATE" in captured["sql"]
    assert captured["args"] == ("id-1", "p6_daily_remind", "每日填报提醒",
                                None, "2026-11-18T00:00:00.000Z")


# ---------------------------------------------------------------- 模板单一配置源

def test_subscribe_templates_only_include_configured(monkeypatch):
    """小程序授权用的模板 ID 只来自服务端 WX_TMPL_*，空值不返回。"""
    monkeypatch.setattr(notify.config, "WX_TMPL_DAILY_REMIND", "tpl-daily")
    monkeypatch.setattr(notify.config, "WX_TMPL_DUE_REMIND", "  ")
    monkeypatch.setattr(notify.config, "WX_TMPL_MISSING_REMIND", "")
    monkeypatch.setattr(notify.config, "WX_TMPL_ANOMALY_ALERT", "tpl-anomaly")

    assert notify.subscribe_templates() == {
        "daily_remind": "tpl-daily",
        "anomaly_alert": "tpl-anomaly",
    }


def test_get_subscribe_templates_handler(monkeypatch):
    from app.handlers import notify as notify_handler

    monkeypatch.setattr(notify_handler.notify, "subscribe_templates",
                        lambda: {"due_remind": "tpl-due"})
    result = notify_handler.get_subscribe_templates(None, "u1", {})

    assert result["templates"] == {"due_remind": "tpl-due"}
    assert set(result["status"]) == set(notify.NOTIFY_TYPES)
