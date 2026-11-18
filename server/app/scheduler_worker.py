"""P6 独立调度进程入口（与 gunicorn Web 进程分离）。

部署约定：
- backend 容器保持 `gunicorn -w 2`，并设置 `SCHEDULER_ENABLED=0`；
- scheduler 容器复用同一镜像，command 为 `python -m app.scheduler_worker`；
- 三类作业复用 `services/notify.py`，调度时间全部来自环境变量。

停止行为：
- 收到 SIGTERM/SIGINT 后停止接受新作业，并等待当前作业结束；
- 作业本身幂等（`notification_logs` 唯一键），重复执行不会重复发送。

启动：
    python -m app.scheduler_worker
"""
import logging
import signal
import sys
import threading

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import config
from .services import notify
from .services.scheduler import (
    DB_WAIT_TIMEOUT_SECONDS,
    add_heartbeat_job,
    parse_hm,
    wait_for_db,
    with_conn,
)

logger = logging.getLogger("jinribao.scheduler")

_JOB_DEFAULTS = {
    "coalesce": True,
    "max_instances": 1,
    "misfire_grace_time": 1800,
}


def _build_scheduler() -> BlockingScheduler:
    """构建阻塞式调度器；作业定义与 services/scheduler.py 保持一致。"""
    daily_hour, daily_minute = parse_hm(config.DAILY_REMIND_TIME, "09:00")
    missing_hour, missing_minute = parse_hm(config.MISSING_REMIND_TIME, "20:00")

    sched = BlockingScheduler(
        timezone=config.SCHEDULER_TZ,
        job_defaults=_JOB_DEFAULTS,
    )
    sched.add_job(
        with_conn(notify.run_daily_reminders, job_id="p6_daily_remind"),
        CronTrigger(hour=daily_hour, minute=daily_minute),
        id="p6_daily_remind",
        name="每日填报提醒",
        replace_existing=True,
    )
    sched.add_job(
        with_conn(notify.run_missing_reminders, job_id="p6_missing_remind"),
        CronTrigger(hour=missing_hour, minute=missing_minute),
        id="p6_missing_remind",
        name="当日未提交提醒",
        replace_existing=True,
    )
    sched.add_job(
        with_conn(notify.run_due_reminders, job_id="p6_due_remind"),
        IntervalTrigger(minutes=5),
        id="p6_due_remind",
        name="截止前提醒",
        replace_existing=True,
    )
    add_heartbeat_job(sched)
    return sched


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not config.SCHEDULER_ENABLED:
        logger.warning("SCHEDULER_ENABLED=0，独立调度进程不启动")
        return 0
    if not config.WX_APPID or not config.WX_SECRET:
        logger.warning(
            "WX_APPID/WX_SECRET 未配置，通知将无法发送"
            "（模板未配置时仍会记录 skipped）"
        )

    if not wait_for_db():
        logger.error(
            "数据库 %s 秒内仍不可用，调度进程退出（由容器重启策略重试）",
            DB_WAIT_TIMEOUT_SECONDS,
        )
        return 1

    sched = _build_scheduler()
    stopping = threading.Event()

    def _handle_signal(signum, _frame):
        if stopping.is_set():
            return
        stopping.set()
        logger.info("收到信号 %s，停止调度并等待当前作业结束", signum)
        try:
            sched.shutdown(wait=True)
        except Exception:
            logger.exception("调度器停止异常")

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(
        "独立调度进程启动：daily=%s missing=%s tz=%s",
        config.DAILY_REMIND_TIME,
        config.MISSING_REMIND_TIME,
        config.SCHEDULER_TZ,
    )
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("独立调度进程退出")
    finally:
        if sched.running:
            sched.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
