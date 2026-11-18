-- 报数机器人AI · P4 回滚：移除组织与多工作空间结构
--
-- ！！有损操作 ！！
--   - 会删除 workspaces / departments / workspace_members 三张表及其全部数据；
--   - 会删除 teams / members / form_templates / daily_entries / report_tasks / audit_logs 的 P4 新增列；
--   - P4 之后产生的跨空间关系、部门归属、只读角色语义将无法恢复。
-- 执行前必须先做全库备份，并确认应用已回退到 P3 版本。
--
-- 用法：
--   docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao < server/sql/migrate_p4_rollback.sql

SET NAMES utf8mb4;
USE `jinribao`;

-- 索引
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'teams' AND INDEX_NAME = 'idx_teams_workspace') > 0,
  'ALTER TABLE `teams` DROP INDEX `idx_teams_workspace`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'form_templates' AND INDEX_NAME = 'idx_tpl_workspace') > 0,
  'ALTER TABLE `form_templates` DROP INDEX `idx_tpl_workspace`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'daily_entries' AND INDEX_NAME = 'idx_entry_workspace_date') > 0,
  'ALTER TABLE `daily_entries` DROP INDEX `idx_entry_workspace_date`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_tasks' AND INDEX_NAME = 'idx_task_workspace_status') > 0,
  'ALTER TABLE `report_tasks` DROP INDEX `idx_task_workspace_status`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_logs' AND INDEX_NAME = 'idx_audit_workspace_time') > 0,
  'ALTER TABLE `audit_logs` DROP INDEX `idx_audit_workspace_time`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 列（倒序：先删依赖索引已移除的列）
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'teams' AND COLUMN_NAME = 'department_id') > 0,
  'ALTER TABLE `teams` DROP COLUMN `department_id`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'teams' AND COLUMN_NAME = 'workspace_id') > 0,
  'ALTER TABLE `teams` DROP COLUMN `workspace_id`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'members' AND COLUMN_NAME = 'left_at') > 0,
  'ALTER TABLE `members` DROP COLUMN `left_at`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'members' AND COLUMN_NAME = 'department_id') > 0,
  'ALTER TABLE `members` DROP COLUMN `department_id`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'form_templates' AND COLUMN_NAME = 'workspace_id') > 0,
  'ALTER TABLE `form_templates` DROP COLUMN `workspace_id`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'daily_entries' AND COLUMN_NAME = 'workspace_id') > 0,
  'ALTER TABLE `daily_entries` DROP COLUMN `workspace_id`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_tasks' AND COLUMN_NAME = 'workspace_id') > 0,
  'ALTER TABLE `report_tasks` DROP COLUMN `workspace_id`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_logs' AND COLUMN_NAME = 'workspace_id') > 0,
  'ALTER TABLE `audit_logs` DROP COLUMN `workspace_id`', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- audit_logs.team_id 恢复 NOT NULL（若存在空间级空团队日志会失败，先清理）
SET @ddl = IF((SELECT IS_NULLABLE FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_logs' AND COLUMN_NAME = 'team_id') = 'YES',
  'ALTER TABLE `audit_logs` MODIFY COLUMN `team_id` VARCHAR(32) NOT NULL',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 表
DROP TABLE IF EXISTS `workspace_members`;
DROP TABLE IF EXISTS `departments`;
DROP TABLE IF EXISTS `workspaces`;

SELECT 'rollback_done' AS check_name, 1 AS done;
