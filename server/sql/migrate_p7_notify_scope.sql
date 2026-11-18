-- 报数机器人AI · P7 增量迁移：通知去重按租户隔离
--
-- 问题：原唯一键 (user_id, notify_type, period_key) 不含团队/空间维度。
--       同一 openid 属于多个团队时，两个团队共用 `daily:2026-11-18` 这类周期键，
--       先执行的团队抢到唯一键，其余团队的通知被当作重复静默丢弃。
--
-- 方案：新增 `scope_key`（团队 id 优先，无团队时取空间 id），
--       唯一键改为 (user_id, notify_type, scope_key, period_key)。
--       `scope_key` 为 NOT NULL DEFAULT ''，避免 NULL 在唯一索引中互不相等导致去重失效。
--
-- 前置：已执行 migrate_p6_notifications.sql / migrate_p6_heartbeat.sql。
--
-- 部署（在 server/ 目录）：
--   docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao \
--     < sql/migrate_p7_notify_scope.sql
--
-- 特性：
--   1) 幂等：列/索引用 information_schema 判断后再执行，重复运行无副作用；
--   2) 存量记录按 team_id → workspace_id → '' 的顺序回填 scope_key；
--   3) 回填后新唯一键是旧键的超集，不会产生冲突，无数据丢失。
--
-- 回滚：migrate_p7_notify_scope_rollback.sql。

SET NAMES utf8mb4;
USE `jinribao`;

-- 1) 加列（幂等）
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
    AND COLUMN_NAME = 'scope_key'
);
SET @ddl := IF(@col_exists = 0,
  'ALTER TABLE `notification_logs` ADD COLUMN `scope_key` VARCHAR(64) NOT NULL DEFAULT '''' COMMENT ''去重作用域：团队 id 优先，其次空间 id'' AFTER `team_id`',
  'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2) 回填存量记录
UPDATE `notification_logs`
SET `scope_key` = COALESCE(NULLIF(`team_id`, ''), NULLIF(`workspace_id`, ''), '')
WHERE `scope_key` = '';

-- 3) 旧唯一键（不含 scope_key）存在则删除
SET @old_idx := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
    AND INDEX_NAME = 'uk_notify_dedupe'
);
SET @has_scope_idx := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
    AND INDEX_NAME = 'uk_notify_dedupe' AND COLUMN_NAME = 'scope_key'
);
SET @ddl := IF(@old_idx > 0 AND @has_scope_idx = 0,
  'ALTER TABLE `notification_logs` DROP INDEX `uk_notify_dedupe`', 'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4) 建新唯一键（幂等）
SET @has_scope_idx := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
    AND INDEX_NAME = 'uk_notify_dedupe' AND COLUMN_NAME = 'scope_key'
);
SET @ddl := IF(@has_scope_idx = 0,
  'ALTER TABLE `notification_logs` ADD UNIQUE KEY `uk_notify_dedupe` (`user_id`, `notify_type`, `scope_key`, `period_key`)',
  'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 部署自检（三项均应为 1）
SELECT 'scope_key_column_exists' AS check_name, COUNT(*) AS expected_1
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
  AND COLUMN_NAME = 'scope_key';

SELECT 'uk_notify_dedupe_has_scope' AS check_name, COUNT(*) AS expected_1
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
  AND INDEX_NAME = 'uk_notify_dedupe' AND COLUMN_NAME = 'scope_key';

SELECT 'backfill_pending_rows' AS check_name, COUNT(*) AS expected_0
FROM `notification_logs`
WHERE `scope_key` = '' AND (COALESCE(`team_id`, '') <> '' OR COALESCE(`workspace_id`, '') <> '');
