-- 报数机器人AI · P5 迁移：Web 扫码登录票据
--
-- 目标：新增 `web_login_tickets`，支撑管理后台「小程序扫码 + 轮询」登录。
-- 前置：已执行 migrate_p4_workspaces.sql。
--
-- 部署（在项目根或 server/ 目录）：
--   docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao < server/sql/migrate_p5_web_tickets.sql
--   非 Docker：mysql -h <host> -u <user> -p <db> < server/sql/migrate_p5_web_tickets.sql
--
-- 特性：
--   1) 幂等：CREATE TABLE IF NOT EXISTS，重复执行不报错；
--   2) 无存量数据需要回填；
--   3) 过期票据由应用在创建新 ticket 时清理（DELETE 24 小时前），无需定时任务。
--
-- 回滚：migrate_p5_rollback.sql（仅删除该表，不影响业务数据）。

SET NAMES utf8mb4;
USE `jinribao`;

CREATE TABLE IF NOT EXISTS `web_login_tickets` (
  `id`            CHAR(24)     NOT NULL,
  `ticket`        CHAR(32)     NOT NULL COMMENT '32 位 hex 随机票据',
  `user_id`       VARCHAR(128) NULL COMMENT '确认登录的 openid',
  `status`        VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT 'pending|confirmed|consumed|expired',
  `workspace_ids` JSON         NULL COMMENT '确认时可管理的空间 id 快照',
  `client_ip`     VARCHAR(64)  NULL,
  `created_at`    VARCHAR(32)  NOT NULL,
  `expires_at`    VARCHAR(32)  NOT NULL,
  `confirmed_at`  VARCHAR(32)  NULL,
  `consumed_at`   VARCHAR(32)  NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_web_ticket` (`ticket`),
  KEY `idx_web_ticket_status` (`status`, `expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 部署自检（应为 1）
SELECT 'web_login_tickets_exists' AS check_name,
       COUNT(*) AS table_count
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'web_login_tickets';
