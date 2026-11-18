-- 报数机器人AI · P6 迁移：订阅设置与通知投递记录
--
-- 目标：新增 `notification_settings` / `notification_logs`，支撑微信订阅消息
--       （填报提醒 / 截止提醒 / 未提交提醒 / 异常预警）与去重。
-- 前置：已执行 migrate_p5_web_tickets.sql。
--
-- 部署（在项目根或 server/ 目录）：
--   docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao < server/sql/migrate_p6_notifications.sql
--   非 Docker：mysql -h <host> -u <user> -p <db> < server/sql/migrate_p6_notifications.sql
--
-- 特性：
--   1) 幂等：CREATE TABLE IF NOT EXISTS，重复执行不报错；
--   2) 无存量数据需要回填；
--   3) `uk_notify_dedupe` 是通知去重的唯一依据，调度器并发时由数据库兜底。
--
-- 回滚：migrate_p6_rollback.sql（仅删除两张通知表，不影响业务数据）。

SET NAMES utf8mb4;
USE `jinribao`;

CREATE TABLE IF NOT EXISTS `notification_settings` (
  `id`           CHAR(24)     NOT NULL,
  `workspace_id` CHAR(24)     NOT NULL DEFAULT '' COMMENT '所属工作空间；空串兼容未归属旧数据',
  `user_id`      VARCHAR(128) NOT NULL COMMENT 'openid',
  `notify_type`  VARCHAR(32)  NOT NULL COMMENT 'daily_remind|due_remind|missing_remind|anomaly_alert',
  `enabled`      TINYINT(1)   NOT NULL DEFAULT 1,
  `updated_at`   VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_notification_setting` (`workspace_id`, `user_id`, `notify_type`),
  KEY `idx_notification_setting_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `notification_logs` (
  `id`            CHAR(24)     NOT NULL,
  `workspace_id`  CHAR(24)     NULL,
  `team_id`       VARCHAR(32)  NULL,
  `user_id`       VARCHAR(128) NOT NULL COMMENT '接收人 openid',
  `notify_type`   VARCHAR(32)  NOT NULL,
  `period_key`    VARCHAR(64)  NOT NULL COMMENT '去重周期，如 daily:2026-11-18',
  `template_id`   VARCHAR(64)  NULL,
  `status`        VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT 'pending|sent|skipped|failed',
  `error_message` VARCHAR(512) NULL,
  `payload`       JSON         NULL COMMENT '模板数据与上下文快照',
  `created_at`    VARCHAR(32)  NOT NULL,
  `sent_at`       VARCHAR(32)  NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_notify_dedupe` (`user_id`, `notify_type`, `period_key`),
  KEY `idx_notify_ws_time` (`workspace_id`, `created_at`),
  KEY `idx_notify_team_time` (`team_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 部署自检（应为 2 / 1 / 1）
SELECT 'notification_tables_exists' AS check_name,
       COUNT(*) AS table_count
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('notification_settings', 'notification_logs');

SELECT 'uk_notify_dedupe_exists' AS check_name,
       COUNT(*) AS index_count
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
  AND INDEX_NAME = 'uk_notify_dedupe';

SELECT 'uk_notification_setting_exists' AS check_name,
       COUNT(*) AS index_count
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_settings'
  AND INDEX_NAME = 'uk_notification_setting';
