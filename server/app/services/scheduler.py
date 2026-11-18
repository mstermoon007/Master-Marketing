"""应用内定时调度（P6）：填报提醒 / 截止提醒 / 未提交提醒。

设计（UPGRADE_PLAN §3.4）：
- 生产由独立 `scheduler` 容器运行 `app/scheduler_worker.py`，Web 进程
  `SCHEDULER_ENABLED=0` 不启动调度，避免 gunicorn 多 worker 重复触发；
- 本地开发/单进程部署可由 `start()` 在当前进程内启动；
- 两种跑法共用本模块的作业定义、`with_conn` 与心跳写入，口径不会分叉；
- 重复触发由 `notification_logs.uk_notify_dedupe` 唯一键收敛；
- 调度器异常只记录日志，绝不影响 Web / 小程序主流程。

心跳：每个作业在 `scheduler_heartbeats` 有一行，调度进程每 60s 刷新
`updated_at` / `next_run_at`；Web 端 `status(conn)` 读该表判断调度是否存活，
超过 `HEARTBEAT_STALE_SECONDS` 未刷新即视为未运行。

异常预警不走定时器：由 handlers.analysis.run_analysis 在分析成功后按发现触发。
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from .. import config, db
from . import notify

logger = logging.getLogger("jinribao.scheduler")

__all__ = ["parse_hm", "wait_for_db", "with_conn", "add_heartbeat_job",
           "start", "shutdown", "status"]

HEARTBEAT_JOB_ID = "p6_heartbeat"
HEARTBEAT_JOB_NAME = "调度心跳"
HEARTBEAT_INTERVAL_SECONDS = 60
HEARTBEAT_STALE_SECONDS = 180
DB_WAIT_TIMEOUT_SECONDS = 30
DB_WAIT_INTERVAL_SECONDS = 2

try:  # 依赖未安装时降级为「仅不启动调度」，主流程保持可用
    from apscheduler.schedulers.background import BackgroundScheduler
except ModuleNotFoundError:  # pragma: no cover - 部署环境会安装 requirements
    BackgroundScheduler = None  # type: ignore

_scheduler: Optional["BackgroundScheduler"] = None


def parse_hm(value: str, default: str):
    """解析 "HH:MM"；非法值回退默认值。供应用内调度与独立调度进程共用。"""
    try:
        hour_text, minute_text = str(value or "").split(":")
        hour, minute = int(hour_text), int(minute_text)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (TypeError, ValueError):
        pass
    hour_text, minute_text = default.split(":")
    return int(hour_text), int(minute_text)


def wait_for_db(timeout: float = DB_WAIT_TIMEOUT_SECONDS,
                interval: float = DB_WAIT_INTERVAL_SECONDS) -> bool:
    """启动前等待 MySQL 真正可查询。

    compose 的 `mysqladmin ping` 在初始化阶段的临时实例上也能通过，但该实例
    不监听 TCP，依赖它的进程会撞上 `Connection refused`。调度进程先做一次
    真实查询，避免首个心跳失败并打出整段 traceback。
    """
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            with db.connection() as conn:
                db.one(conn, "SELECT 1")
            if attempt > 1:
                logger.info("数据库已就绪（第 %s 次尝试）", attempt)
            return True
        except Exception as exc:
            logger.warning("数据库暂不可用（第 %s 次尝试）：%s", attempt, exc)
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)


# ---------------------------------------------------------------------------
# 心跳
# ---------------------------------------------------------------------------
def _iso_seconds_ago(value):
    """心跳时间距今秒数；解析失败返回 None（当作异常数据忽略）。"""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds()


def write_heartbeat(conn, statuses) -> None:
    """刷新各作业下次执行时间；`statuses` 为 [(job_id, job_name, next_run_iso)]。"""
    now = db.now_iso()
    for job_id, job_name, next_run in statuses:
        db.execute(
            conn,
            "INSERT INTO `scheduler_heartbeats` "
            "(`id`, `job_id`, `job_name`, `next_run_at`, `last_run_at`, "
            "`last_status`, `last_error`, `updated_at`) "
            "VALUES (%s, %s, %s, %s, NULL, 'ok', NULL, %s) "
            "ON DUPLICATE KEY UPDATE `job_name` = VALUES(`job_name`), "
            "`next_run_at` = VALUES(`next_run_at`), `updated_at` = VALUES(`updated_at`)",
            (db.gen_id(), job_id, job_name, next_run, now),
        )


def record_run(conn, job_id: str, status: str, error=None) -> None:
    """记录作业执行结果；不覆盖心跳字段，避免影响存活判断。"""
    now = db.now_iso()
    db.execute(
        conn,
        "INSERT INTO `scheduler_heartbeats` "
        "(`id`, `job_id`, `job_name`, `next_run_at`, `last_run_at`, "
        "`last_status`, `last_error`, `updated_at`) "
        "VALUES (%s, %s, %s, NULL, %s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE `last_run_at` = VALUES(`last_run_at`), "
        "`last_status` = VALUES(`last_status`), `last_error` = VALUES(`last_error`)",
        (db.gen_id(), job_id, job_id, now, status, (error or None), now),
    )


def _record_failure(job_id: str, message: str) -> None:
    """失败记录必须独立事务：作业本身已回滚，同连接写入会一起丢失。"""
    try:
        with db.connection() as conn:
            record_run(conn, job_id, "failed", message)
    except Exception:
        logger.exception("调度心跳写入失败：%s", job_id)


def _job_states(scheduler) -> list:
    states = []
    for job in scheduler.get_jobs():
        next_run = getattr(job, "next_run_time", None)
        states.append((job.id, job.name,
                       next_run.isoformat() if next_run else None))
    return states


def add_heartbeat_job(scheduler) -> None:
    """注册心跳作业：启动即写一次，之后每 60s 刷新。"""
    def beat(conn):
        write_heartbeat(conn, _job_states(scheduler))

    scheduler.add_job(
        with_conn(beat, job_id=HEARTBEAT_JOB_ID),
        "interval",
        seconds=HEARTBEAT_INTERVAL_SECONDS,
        id=HEARTBEAT_JOB_ID,
        name=HEARTBEAT_JOB_NAME,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(),
    )


def with_conn(func, job_id=None):
    """定时作业统一获取连接；异常在这里吞掉并记录，避免作业被 APScheduler 摘除。

    传入 `job_id` 时顺带写心跳执行结果，失败记录走独立事务。
    供应用内调度与独立调度进程（app/scheduler_worker.py）共用。
    """
    def run():
        try:
            with db.connection() as conn:
                result = func(conn)
                if job_id:
                    record_run(conn, job_id, "ok")
            if result:
                logger.info("scheduler job %s: %s", func.__name__, result)
            return result
        except Exception as exc:
            logger.exception("scheduler job failed: %s", func.__name__)
            if job_id:
                _record_failure(job_id, str(exc)[:400])
            return None
    return run


def start() -> bool:
    """按配置启动调度器；重复调用无副作用。"""
    global _scheduler
    if not config.SCHEDULER_ENABLED:
        logger.info("scheduler disabled by SCHEDULER_ENABLED=0")
        return False
    if BackgroundScheduler is None:
        logger.warning("APScheduler 未安装，跳过定时提醒（pip install -r requirements.txt）")
        return False
    if _scheduler and _scheduler.running:
        return True

    _scheduler = BackgroundScheduler(timezone=config.SCHEDULER_TZ)
    daily_h, daily_m = parse_hm(config.DAILY_REMIND_TIME, "09:00")
    missing_h, missing_m = parse_hm(config.MISSING_REMIND_TIME, "20:00")

    _scheduler.add_job(
        with_conn(notify.run_daily_reminders, job_id="p6_daily_remind"), "cron",
        hour=daily_h, minute=daily_m, id="p6_daily_remind",
        name="每日填报提醒", replace_existing=True, coalesce=True, max_instances=1,
        misfire_grace_time=1800,
    )
    _scheduler.add_job(
        with_conn(notify.run_missing_reminders, job_id="p6_missing_remind"), "cron",
        hour=missing_h, minute=missing_m, id="p6_missing_remind",
        name="当日未提交提醒", replace_existing=True, coalesce=True, max_instances=1,
        misfire_grace_time=1800,
    )
    _scheduler.add_job(
        with_conn(notify.run_due_reminders, job_id="p6_due_remind"), "interval",
        minutes=5, id="p6_due_remind", name="截止前提醒",
        replace_existing=True, coalesce=True, max_instances=1,
    )
    add_heartbeat_job(_scheduler)
    _scheduler.start()
    logger.info("scheduler started: daily=%02d:%02d missing=%02d:%02d tz=%s",
                daily_h, daily_m, missing_h, missing_m, config.SCHEDULER_TZ)
    return True


def shutdown() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler stopped")
    _scheduler = None


def status(conn=None) -> dict:
    """工作台运行监控用：优先取进程内调度，进程内未启动时读心跳表。

    Web 进程（SCHEDULER_ENABLED=0）通过心跳判断独立调度容器是否存活。
    """
    local_running = bool(_scheduler is not None and getattr(_scheduler, "running", False))
    jobs = []
    source = "none"

    if local_running and _scheduler is not None:
        for job in _scheduler.get_jobs():
            next_run = getattr(job, "next_run_time", None)
            jobs.append({
                "id": job.id,
                "name": job.name,
                "nextRun": next_run.isoformat() if next_run else None,
            })
        source = "process"

    beat_fresh = False
    last_beat = None
    if conn is not None:
        try:
            rows = db.query(
                conn,
                "SELECT `job_id`, `job_name`, `next_run_at`, `updated_at` "
                "FROM `scheduler_heartbeats` ORDER BY `job_id` ASC",
            )
        except Exception:
            logger.exception("读取调度心跳失败")
            rows = []
        ages = [age for age in (_iso_seconds_ago(r.get("updated_at")) for r in rows)
                if age is not None]
        if rows:
            last_beat = max((r.get("updated_at") or "" for r in rows), default=None)
            beat_fresh = bool(ages) and min(ages) <= HEARTBEAT_STALE_SECONDS
            if not local_running:
                jobs = [{
                    "id": r.get("job_id"),
                    "name": r.get("job_name"),
                    "nextRun": r.get("next_run_at"),
                } for r in rows]
                source = "heartbeat"

    return {
        "enabled": bool(config.SCHEDULER_ENABLED) or beat_fresh,
        "running": local_running or beat_fresh,
        "source": source,
        "stale": bool(jobs) and not local_running and not beat_fresh,
        "lastHeartbeatAt": last_beat,
        "timezone": config.SCHEDULER_TZ,
        "dailyRemindTime": config.DAILY_REMIND_TIME,
        "missingRemindTime": config.MISSING_REMIND_TIME,
        "remindBeforeMinutes": config.REMIND_BEFORE_MINUTES,
        "jobs": jobs,
    }
