-- 报数机器人AI · P7 回滚：通知去重按租户隔离
--
-- 该回滚为「有损」：旧唯一键 (user_id, notify_type, period_key) 比新键更严格。
-- 若迁移后同一用户同一周期已在多个团队各发过通知，重建旧键会因重复而失败。
-- 执行前先检查：
--   SELECT user_id, notify_type, period_key, COUNT(*) FROM notification_logs
--   GROUP BY user_id, notify_type, period_key HAVING COUNT(*) > 1;
-- 有结果时需先人工清理重复通知记录（或保留新键，不回滚）。

SET NAMES utf8mb4;
USE `jinribao`;

-- 1) 删除新唯一键
SET @has_scope_idx := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
    AND INDEX_NAME = 'uk_notify_dedupe' AND COLUMN_NAME = 'scope_key'
);
SET @ddl := IF(@has_scope_idx > 0,
  'ALTER TABLE `notification_logs` DROP INDEX `uk_notify_dedupe`', 'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2) 恢复旧唯一键（幂等）
SET @old_idx := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
    AND INDEX_NAME = 'uk_notify_dedupe'
);
SET @ddl := IF(@old_idx = 0,
  'ALTER TABLE `notification_logs` ADD UNIQUE KEY `uk_notify_dedupe` (`user_id`, `notify_type`, `period_key`)',
  'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 3) 删除 scope_key 列（幂等）
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
    AND COLUMN_NAME = 'scope_key'
);
SET @ddl := IF(@col_exists > 0,
  'ALTER TABLE `notification_logs` DROP COLUMN `scope_key`', 'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 回滚自检（应为 0 / 1）
SELECT 'scope_key_column_exists' AS check_name, COUNT(*) AS expected_0
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
  AND COLUMN_NAME = 'scope_key';

SELECT 'uk_notify_dedupe_exists' AS check_name, COUNT(*) AS expected_1
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notification_logs'
  AND INDEX_NAME = 'uk_notify_dedupe' AND SEQ_IN_INDEX = 1;
