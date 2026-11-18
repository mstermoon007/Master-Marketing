-- 报数机器人AI · P6 增量迁移：调度心跳
--
-- 目标：新增 `scheduler_heartbeats`，让 Web 端能判断独立 scheduler 容器是否存活。
--       每个作业一行，调度进程每 60s 刷新 `updated_at`；超过阈值（3 分钟）视为未运行。
-- 前置：已执行 migrate_p6_notifications.sql。
--
-- 部署（在项目根或 server/ 目录）：
--   docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao < server/sql/migrate_p6_heartbeat.sql
--   非 Docker：mysql -h <host> -u <user> -p <db> < server/sql/migrate_p6_heartbeat.sql
--
-- 特性：
--   1) 幂等：CREATE TABLE IF NOT EXISTS，重复执行不报错；
--   2) 无存量数据需要回填；
--   3) 心跳行由调度进程自动写入，表为空时工作台显示「调度已关闭」。
--
-- 回滚：migrate_p6_heartbeat_rollback.sql（仅删除心跳表，不影响业务数据）。

SET NAMES utf8mb4;
USE `jinribao`;

CREATE TABLE IF NOT EXISTS `scheduler_heartbeats` (
  `id`          CHAR(24)     NOT NULL,
  `job_id`      VARCHAR(64)  NOT NULL COMMENT '作业标识，如 p6_daily_remind',
  `job_name`    VARCHAR(128) NOT NULL,
  `next_run_at` VARCHAR(32)  NULL COMMENT '下次执行时间（ISO8601）',
  `last_run_at` VARCHAR(32)  NULL COMMENT '最近一次执行完成时间',
  `last_status` VARCHAR(16)  NOT NULL DEFAULT 'ok' COMMENT 'ok|failed',
  `last_error`  VARCHAR(512) NULL,
  `updated_at`  VARCHAR(32)  NOT NULL COMMENT '心跳刷新时间；超过阈值视为调度未运行',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_scheduler_job` (`job_id`),
  KEY `idx_scheduler_updated` (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 部署自检（应为 1 / 1）
SELECT 'scheduler_heartbeat_table_exists' AS check_name,
       COUNT(*) AS table_count
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'scheduler_heartbeats';

SELECT 'uk_scheduler_job_exists' AS check_name,
       COUNT(*) AS index_count
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'scheduler_heartbeats'
  AND INDEX_NAME = 'uk_scheduler_job';
