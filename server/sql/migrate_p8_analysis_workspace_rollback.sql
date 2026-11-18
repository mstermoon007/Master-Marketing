-- 报数机器人AI · P8 回滚：移除 analysis_tasks.workspace_id
--
-- 注意：本回滚**有损**——列存的是任务创建时的空间归属快照，
--       删除后只能靠 JOIN teams 还原「当前」归属，团队迁移过空间的历史会丢失。
--       执行前请备份 analysis_tasks。
--
-- 部署（在 server/ 目录）：
--   docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao \
--     < sql/migrate_p8_analysis_workspace_rollback.sql
--
-- 前置：应用已回退到不读写 workspace_id 的版本（P7 及以前）。

SET NAMES utf8mb4;
USE `jinribao`;

-- 1) 删除索引（幂等）
SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'analysis_tasks'
    AND INDEX_NAME = 'idx_analysis_ws_time'
);
SET @ddl := IF(@idx_exists > 0,
  'ALTER TABLE `analysis_tasks` DROP INDEX `idx_analysis_ws_time`',
  'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2) 删除列（幂等）
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'analysis_tasks'
    AND COLUMN_NAME = 'workspace_id'
);
SET @ddl := IF(@col_exists > 0,
  'ALTER TABLE `analysis_tasks` DROP COLUMN `workspace_id`',
  'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 部署自检（两项均应为 0）
SELECT 'analysis_workspace_column_exists' AS check_name, COUNT(*) AS expected_0
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'analysis_tasks'
  AND COLUMN_NAME = 'workspace_id';

SELECT 'idx_analysis_ws_time_exists' AS check_name, COUNT(*) AS expected_0
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'analysis_tasks'
  AND INDEX_NAME = 'idx_analysis_ws_time';
