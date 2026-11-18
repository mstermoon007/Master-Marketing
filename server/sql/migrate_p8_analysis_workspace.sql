-- 报数机器人AI · P8 增量迁移：分析任务补齐租户字段
--
-- 问题：analysis_tasks 只有 team_id，工作台运行监控统计分析执行情况时
--       必须 JOIN teams 才能按 workspace_id 过滤，既慢又容易漏加过滤条件。
--
-- 方案：新增 workspace_id（服务端按团队反查写入），并加 (workspace_id, created_at) 索引；
--       存量任务按团队归属一次性回填。
--
-- 前置：已执行 migrate_p3_analysis.sql / migrate_p4_workspaces.sql。
--
-- 部署（在 server/ 目录）：
--   docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao \
--     < sql/migrate_p8_analysis_workspace.sql
--
-- 特性：
--   1) 幂等：列/索引用 information_schema 判断后再执行，重复运行无副作用；
--   2) 回填只填空值，不覆盖已有归属（团队后续迁移空间时保留历史归属）；
--   3) 幂等唯一键 uk_analysis_idem 不变，不产生重复任务。
--
-- 回滚：migrate_p8_analysis_workspace_rollback.sql（只删索引与列，不动业务数据）。

SET NAMES utf8mb4;
USE `jinribao`;

-- 1) 加列（幂等）
SET @col_exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'analysis_tasks'
    AND COLUMN_NAME = 'workspace_id'
);
SET @ddl := IF(@col_exists = 0,
  'ALTER TABLE `analysis_tasks` ADD COLUMN `workspace_id` CHAR(24) NULL COMMENT ''冗余归属，服务端写入（P8）'' AFTER `team_id`',
  'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2) 回填存量任务（按团队当前归属）
UPDATE `analysis_tasks` t
JOIN `teams` tm ON tm.`team_id` = t.`team_id`
SET t.`workspace_id` = tm.`workspace_id`
WHERE t.`workspace_id` IS NULL AND tm.`workspace_id` IS NOT NULL;

-- 3) 建索引（幂等）
SET @idx_exists := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'analysis_tasks'
    AND INDEX_NAME = 'idx_analysis_ws_time'
);
SET @ddl := IF(@idx_exists = 0,
  'ALTER TABLE `analysis_tasks` ADD KEY `idx_analysis_ws_time` (`workspace_id`, `created_at`)',
  'DO 0');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 部署自检（前两项应为 1，最后一项应为 0）
SELECT 'analysis_workspace_column_exists' AS check_name, COUNT(*) AS expected_1
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'analysis_tasks'
  AND COLUMN_NAME = 'workspace_id';

SELECT 'idx_analysis_ws_time_exists' AS check_name, COUNT(*) AS expected_1
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'analysis_tasks'
  AND INDEX_NAME = 'idx_analysis_ws_time';

SELECT 'backfill_pending_rows' AS check_name, COUNT(*) AS expected_0
FROM `analysis_tasks` t
JOIN `teams` tm ON tm.`team_id` = t.`team_id`
WHERE t.`workspace_id` IS NULL AND tm.`workspace_id` IS NOT NULL;
