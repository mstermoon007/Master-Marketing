"""真实 MySQL 集成测试（P1）。

默认跳过；设置 `TEST_MYSQL_URL` 后运行：

    TEST_MYSQL_URL=mysql://root:test@127.0.0.1:3308/jinribao_it \
      python -m pytest -q tests/test_db_integration.py

测试会 **DROP 并重建 URL 中的数据库**，必须指向一次性库（禁止指向 jinribao）。
本地起库示例见 `server/README.md`「真实 MySQL 集成测试」。

覆盖范围：
1. schema.sql 能在真实 MySQL 8 上完整建表（18 张）；
2. p2–p8 全部迁移脚本可重复执行且最终结构正确；
3. 通知去重在真实唯一键下按团队隔离、同团队仍去重；
4. 订阅设置 upsert 只保留一行；
5. 关键唯一索引的列顺序与契约一致；
6. analysis_tasks 的 workspace_id 列与索引存在。
"""
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

pymysql = pytest.importorskip("pymysql")

from app.services import notify  # noqa: E402

SERVER_DIR = Path(__file__).resolve().parent.parent
SQL_DIR = SERVER_DIR / "sql"
SCHEMA = SQL_DIR / "schema.sql"
MIGRATIONS = (
    SQL_DIR / "migrate_p2_report_tasks.sql",
    SQL_DIR / "migrate_p3_analysis.sql",
    SQL_DIR / "migrate_p4_workspaces.sql",
    SQL_DIR / "migrate_p5_web_tickets.sql",
    SQL_DIR / "migrate_p6_notifications.sql",
    SQL_DIR / "migrate_p6_heartbeat.sql",
    SQL_DIR / "migrate_p7_notify_scope.sql",
    SQL_DIR / "migrate_p8_analysis_workspace.sql",
)

EXPECTED_TABLES = {
    "workspaces", "departments", "workspace_members", "teams", "members",
    "form_templates", "daily_entries", "report_tasks",
    "analysis_metrics", "analysis_rules", "analysis_tasks",
    "analysis_results", "analysis_findings", "audit_logs",
    "web_login_tickets", "notification_settings", "notification_logs",
    "scheduler_heartbeats",
}

TEST_URL = os.environ.get("TEST_MYSQL_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="未设置 TEST_MYSQL_URL，跳过真实 MySQL 集成测试"
)

_DB = ""


def _parse_url(url: str) -> dict:
    parsed = urlparse(url)
    database = unquote(parsed.path.lstrip("/"))
    if not parsed.hostname or not database:
        raise RuntimeError("TEST_MYSQL_URL 格式应为 mysql://user:pass@host:port/dbname")
    if database in ("jinribao", "mysql", "sys", "information_schema", "performance_schema"):
        raise RuntimeError(
            "TEST_MYSQL_URL 指向了不可删除的库 %r；测试会 DROP DATABASE，请使用一次性库名"
            % database
        )
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or "root"),
        "password": unquote(parsed.password or ""),
        "database": database,
    }


def _run_script(conn, path: Path) -> None:
    """执行整份 SQL 文件（多语句 + PREPARE），把库名替换为测试库。"""
    sql = path.read_text("utf-8").replace("`jinribao`", "`%s`" % _DB)
    with conn.cursor() as cur:
        cur.execute(sql)
        while cur.nextset():
            pass


@pytest.fixture(scope="session")
def conn():
    global _DB
    cfg = _parse_url(TEST_URL)
    _DB = cfg["database"]

    admin = pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], charset="utf8mb4", autocommit=True,
    )
    with admin.cursor() as cur:
        cur.execute("DROP DATABASE IF EXISTS `%s`" % _DB)
        cur.execute(
            "CREATE DATABASE `%s` DEFAULT CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_0900_ai_ci" % _DB
        )
    admin.close()

    connection = pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], database=_DB, charset="utf8mb4",
        autocommit=True, cursorclass=pymysql.cursors.DictCursor,
        client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS,
    )
    _run_script(connection, SCHEMA)
    try:
        yield connection
    finally:
        connection.close()


def _index_columns(conn, table: str, index: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COLUMN_NAME FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_NAME = %s "
            "ORDER BY SEQ_IN_INDEX",
            (_DB, table, index),
        )
        return [row["COLUMN_NAME"] for row in cur.fetchall()]


def test_schema_creates_all_tables(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
            (_DB,),
        )
        created = {row["TABLE_NAME"] for row in cur.fetchall()}
    assert EXPECTED_TABLES <= created


def test_migrations_are_idempotent(conn):
    for path in MIGRATIONS:
        _run_script(conn, path)
        _run_script(conn, path)

    assert _index_columns(conn, "notification_logs", "uk_notify_dedupe") == [
        "user_id", "notify_type", "scope_key", "period_key",
    ]


def test_key_unique_indexes_match_contract(conn):
    assert _index_columns(conn, "daily_entries", "uk_entry_team_user_date") == [
        "team_id", "user_id", "entry_date",
    ]
    assert _index_columns(conn, "notification_settings", "uk_notification_setting") == [
        "workspace_id", "user_id", "notify_type",
    ]
    assert _index_columns(conn, "scheduler_heartbeats", "uk_scheduler_job") == ["job_id"]


def test_analysis_tasks_scoped_by_workspace(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'analysis_tasks' "
            "AND COLUMN_NAME = 'workspace_id'",
            (_DB,),
        )
        column = cur.fetchone()
    assert column and column["IS_NULLABLE"] == "YES"
    assert _index_columns(conn, "analysis_tasks", "idx_analysis_ws_time") == [
        "workspace_id", "created_at",
    ]


def test_notify_dedupe_isolated_by_team(conn, monkeypatch):
    """同一用户同一天：两个团队各一条，同团队第二次被唯一键拦下。"""
    for name in ("WX_TMPL_DAILY_REMIND", "WX_TMPL_DUE_REMIND",
                 "WX_TMPL_MISSING_REMIND", "WX_TMPL_ANOMALY_ALERT"):
        monkeypatch.setattr(notify.config, name, "")

    def send(team_id):
        return notify.notify_user(
            conn, "it-user", notify.DAILY_REMIND, "daily:2026-11-18",
            "团队" + team_id, "今日填报提醒", "2026-11-18",
            team_id=team_id, workspace_id="W1",
        )

    first = send("T1")
    duplicate = send("T1")
    other_team = send("T2")

    assert first["status"] == "skipped"  # 模板未配置，只落库
    assert duplicate["status"] == "duplicate"
    assert other_team["status"] == "skipped"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT team_id, scope_key, status FROM notification_logs "
            "WHERE user_id = %s ORDER BY team_id",
            ("it-user",),
        )
        rows = cur.fetchall()

    assert [row["team_id"] for row in rows] == ["T1", "T2"]
    assert [row["scope_key"] for row in rows] == ["T1", "T2"]
    assert {row["status"] for row in rows} == {"skipped"}


def test_notification_settings_upsert_single_row(conn):
    notify.save_setting(conn, "W1", "it-user", notify.DAILY_REMIND, True)
    notify.save_setting(conn, "W1", "it-user", notify.DAILY_REMIND, False)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT enabled FROM notification_settings "
            "WHERE workspace_id = %s AND user_id = %s AND notify_type = %s",
            ("W1", "it-user", notify.DAILY_REMIND),
        )
        rows = cur.fetchall()

    assert len(rows) == 1
    assert int(rows[0]["enabled"]) == 0
    assert notify.settings_enabled(conn, "W1", "it-user", notify.DAILY_REMIND) is False


def test_p8_backfills_existing_analysis_tasks(conn):
    """模拟 P7 结构：删列后写入存量任务，P8 应回填空间归属且可重复执行。"""
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE `analysis_tasks` DROP INDEX `idx_analysis_ws_time`")
        cur.execute("ALTER TABLE `analysis_tasks` DROP COLUMN `workspace_id`")
        cur.execute(
            "INSERT INTO `teams` (`id`, `team_id`, `workspace_id`, `name`, "
            "`owner_uid`, `created_at`) VALUES (%s, %s, %s, %s, %s, %s)",
            ("t" * 24, "T8", "W8", "P8 团队", "owner", "2026-11-18T00:00:00.000Z"),
        )
        cur.execute(
            "INSERT INTO `analysis_tasks` (`id`, `team_id`, `analysis_type`, "
            "`period_start`, `period_end`, `status`, `metric_version`, "
            "`rule_version`, `retry_count`, `created_at`) "
            "VALUES (%s, %s, 'period', %s, %s, 'success', 1, 1, 0, %s)",
            ("a" * 24, "T8", "2026-11-10", "2026-11-11",
             "2026-11-18T00:00:00.000Z"),
        )

    _run_script(conn, SQL_DIR / "migrate_p8_analysis_workspace.sql")
    _run_script(conn, SQL_DIR / "migrate_p8_analysis_workspace.sql")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT workspace_id FROM `analysis_tasks` WHERE id = %s",
            ("a" * 24,),
        )
        row = cur.fetchone()

    assert row["workspace_id"] == "W8"
    assert _index_columns(conn, "analysis_tasks", "idx_analysis_ws_time") == [
        "workspace_id", "created_at",
    ]
