-- 报数机器人AI · P4 迁移：组织与多工作空间
--
-- 目标：引入「工作空间 → 部门 → 团队」，给既有表补冗余 workspace_id，支持一人多空间。
-- 前置：已执行 migrate_p2_report_tasks.sql、migrate_p3_analysis.sql。
--
-- 部署（在项目根或 server/ 目录）：
--   docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao < server/sql/migrate_p4_workspaces.sql
--   非 Docker：mysql -h <host> -u <user> -p <db> < server/sql/migrate_p4_workspaces.sql
--
-- 特性：
--   1) 幂等：加列/加索引均先查 information_schema，重复执行不报错；
--   2) 存量映射：每个团队生成一个独立工作空间，workspace_code = 'W' + team_id，
--      workspaces.id = SHA2('ws:'+team_id) 前 24 位，现有可见范围不变；
--   3) 回填：teams 及其子表（模板/录入/任务/审计）的 workspace_id；
--   4) 空间成员由 members 去重生成，角色按 owner > admin > member > viewer 取高，不降级；
--   5) 末尾自检 SELECT：失败项应均为 0。
--
-- 回滚：migrate_p4_rollback.sql（有损，先备份）。
-- 注意：DDL 会短暂锁表，建议低峰执行；执行前务必完成全库备份。

SET NAMES utf8mb4;
USE `jinribao`;

-- ---------------------------------------------------------------------------
-- 1. 新建表
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `workspaces` (
  `id`             CHAR(24)     NOT NULL,
  `workspace_code` VARCHAR(32)  NOT NULL COMMENT '对外稳定编码，迁移时 W+team_id',
  `name`           VARCHAR(128) NOT NULL,
  `owner_uid`      VARCHAR(128) NOT NULL COMMENT 'openid',
  `config`         JSON         NULL COMMENT '{ memberSeeTeamTotal }',
  `created_at`     VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_workspaces_code` (`workspace_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `departments` (
  `id`           CHAR(24)     NOT NULL,
  `workspace_id` CHAR(24)     NOT NULL,
  `parent_id`    CHAR(24)     NULL,
  `parent_key`   CHAR(24)     GENERATED ALWAYS AS (IFNULL(`parent_id`, '')) STORED NOT NULL,
  `name`         VARCHAR(128) NOT NULL,
  `depth`        TINYINT      NOT NULL DEFAULT 1 COMMENT '1..3',
  `leader_uid`   VARCHAR(128) NULL COMMENT '部门负责人 openid',
  `status`       VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active|archived',
  `created_at`   VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dept_ws_parent_name` (`workspace_id`, `parent_key`, `name`),
  KEY `idx_dept_ws_parent` (`workspace_id`, `parent_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `workspace_members` (
  `id`           CHAR(24)     NOT NULL,
  `workspace_id` CHAR(24)     NOT NULL,
  `user_id`      VARCHAR(128) NOT NULL COMMENT 'openid',
  `name`         VARCHAR(64)  NOT NULL,
  `role`         VARCHAR(16)  NOT NULL DEFAULT 'member' COMMENT 'owner|admin|member|viewer',
  `status`       VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active|disabled',
  `joined_at`    VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ws_member` (`workspace_id`, `user_id`),
  KEY `idx_ws_member_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------------
-- 2. 现有表加列（幂等：先查 information_schema）
-- ---------------------------------------------------------------------------
-- teams.workspace_id
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'teams' AND COLUMN_NAME = 'workspace_id') = 0,
  'ALTER TABLE `teams` ADD COLUMN `workspace_id` CHAR(24) NULL COMMENT ''所属工作空间（P4）'' AFTER `team_id`',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- teams.department_id
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'teams' AND COLUMN_NAME = 'department_id') = 0,
  'ALTER TABLE `teams` ADD COLUMN `department_id` CHAR(24) NULL COMMENT ''所属部门（P4）'' AFTER `workspace_id`',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- members.department_id
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'members' AND COLUMN_NAME = 'department_id') = 0,
  'ALTER TABLE `members` ADD COLUMN `department_id` CHAR(24) NULL COMMENT ''团队内所属部门（P4）'' AFTER `status`',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- members.left_at
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'members' AND COLUMN_NAME = 'left_at') = 0,
  'ALTER TABLE `members` ADD COLUMN `left_at` VARCHAR(32) NULL COMMENT ''离开时间；非空后可重新加入并复用该行'' AFTER `department_id`',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- form_templates.workspace_id
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'form_templates' AND COLUMN_NAME = 'workspace_id') = 0,
  'ALTER TABLE `form_templates` ADD COLUMN `workspace_id` CHAR(24) NULL COMMENT ''冗余归属，服务端写入（P4）'' AFTER `team_id`',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- daily_entries.workspace_id
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'daily_entries' AND COLUMN_NAME = 'workspace_id') = 0,
  'ALTER TABLE `daily_entries` ADD COLUMN `workspace_id` CHAR(24) NULL COMMENT ''冗余归属，服务端写入（P4）'' AFTER `team_id`',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- report_tasks.workspace_id
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_tasks' AND COLUMN_NAME = 'workspace_id') = 0,
  'ALTER TABLE `report_tasks` ADD COLUMN `workspace_id` CHAR(24) NULL COMMENT ''冗余归属，服务端写入（P4）'' AFTER `team_id`',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- audit_logs.workspace_id
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_logs' AND COLUMN_NAME = 'workspace_id') = 0,
  'ALTER TABLE `audit_logs` ADD COLUMN `workspace_id` CHAR(24) NULL AFTER `team_id`',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- audit_logs.team_id 允许为空（空间级审计没有团队）
SET @ddl = IF((SELECT IS_NULLABLE FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_logs' AND COLUMN_NAME = 'team_id') = 'NO',
  'ALTER TABLE `audit_logs` MODIFY COLUMN `team_id` VARCHAR(32) NULL',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------------
-- 3. 索引（幂等）
-- ---------------------------------------------------------------------------
SET @ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'teams' AND INDEX_NAME = 'idx_teams_workspace') = 0,
  'ALTER TABLE `teams` ADD KEY `idx_teams_workspace` (`workspace_id`)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'form_templates' AND INDEX_NAME = 'idx_tpl_workspace') = 0,
  'ALTER TABLE `form_templates` ADD KEY `idx_tpl_workspace` (`workspace_id`, `status`)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'daily_entries' AND INDEX_NAME = 'idx_entry_workspace_date') = 0,
  'ALTER TABLE `daily_entries` ADD KEY `idx_entry_workspace_date` (`workspace_id`, `entry_date`)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'report_tasks' AND INDEX_NAME = 'idx_task_workspace_status') = 0,
  'ALTER TABLE `report_tasks` ADD KEY `idx_task_workspace_status` (`workspace_id`, `status`)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_logs' AND INDEX_NAME = 'idx_audit_workspace_time') = 0,
  'ALTER TABLE `audit_logs` ADD KEY `idx_audit_workspace_time` (`workspace_id`, `created_at`)', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------------
-- 4. 存量映射：每个团队一个工作空间（1:1）
-- ---------------------------------------------------------------------------
INSERT INTO `workspaces` (`id`, `workspace_code`, `name`, `owner_uid`, `config`, `created_at`)
SELECT SUBSTR(SHA2(CONCAT('ws:', t.`team_id`), 256), 1, 24),
       CONCAT('W', t.`team_id`),
       CONCAT(t.`name`, ' 工作空间'),
       t.`owner_uid`,
       t.`config`,
       t.`created_at`
FROM `teams` t
WHERE NOT EXISTS (
  SELECT 1 FROM `workspaces` w WHERE w.`workspace_code` = CONCAT('W', t.`team_id`)
);

UPDATE `teams` t
JOIN `workspaces` w ON w.`workspace_code` = CONCAT('W', t.`team_id`)
SET t.`workspace_id` = w.`id`
WHERE t.`workspace_id` IS NULL OR t.`workspace_id` = '';

-- 空间成员：由现有团队成员去重生成，角色映射 owner->owner / manager->admin / 其它->member
INSERT INTO `workspace_members` (`id`, `workspace_id`, `user_id`, `name`, `role`, `status`, `joined_at`)
SELECT SUBSTR(SHA2(CONCAT('wm:', m.`team_id`, ':', m.`user_id`), 256), 1, 24),
       t.`workspace_id`,
       m.`user_id`,
       m.`name`,
       CASE m.`role` WHEN 'owner' THEN 'owner' WHEN 'manager' THEN 'admin' ELSE 'member' END,
       CASE WHEN m.`status` = 'active' THEN 'active' ELSE 'disabled' END,
       m.`joined_at`
FROM `members` m
JOIN `teams` t ON t.`team_id` = m.`team_id`
WHERE t.`workspace_id` IS NOT NULL
ON DUPLICATE KEY UPDATE
  `workspace_members`.`role` = CASE
    WHEN FIELD(VALUES(`role`), 'owner', 'admin', 'member', 'viewer')
       < FIELD(`workspace_members`.`role`, 'owner', 'admin', 'member', 'viewer')
    THEN VALUES(`role`) ELSE `workspace_members`.`role` END,
  `workspace_members`.`status` = CASE
    WHEN `workspace_members`.`status` = 'active' OR VALUES(`status`) = 'active'
    THEN 'active' ELSE 'disabled' END,
  `workspace_members`.`name` = VALUES(`name`);

-- 子表回填
UPDATE `form_templates` f
JOIN `teams` t ON t.`team_id` = f.`team_id`
SET f.`workspace_id` = t.`workspace_id`
WHERE t.`workspace_id` IS NOT NULL AND (f.`workspace_id` IS NULL OR f.`workspace_id` = '');

UPDATE `daily_entries` e
JOIN `teams` t ON t.`team_id` = e.`team_id`
SET e.`workspace_id` = t.`workspace_id`
WHERE t.`workspace_id` IS NOT NULL AND (e.`workspace_id` IS NULL OR e.`workspace_id` = '');

UPDATE `report_tasks` r
JOIN `teams` t ON t.`team_id` = r.`team_id`
SET r.`workspace_id` = t.`workspace_id`
WHERE t.`workspace_id` IS NOT NULL AND (r.`workspace_id` IS NULL OR r.`workspace_id` = '');

UPDATE `audit_logs` a
JOIN `teams` t ON t.`team_id` = a.`team_id`
SET a.`workspace_id` = t.`workspace_id`
WHERE t.`workspace_id` IS NOT NULL AND (a.`workspace_id` IS NULL OR a.`workspace_id` = '');

-- ---------------------------------------------------------------------------
-- 5. 部署自检（所有 bad_* / null_* 应为 0；空间数应等于团队数）
-- ---------------------------------------------------------------------------
SELECT 'teams_without_workspace' AS check_name, COUNT(*) AS bad_rows
FROM `teams` WHERE `workspace_id` IS NULL OR `workspace_id` = '';

SELECT 'workspace_count' AS check_name, COUNT(*) AS total FROM `workspaces`;
SELECT 'team_count' AS check_name, COUNT(*) AS total FROM `teams`;

SELECT 'form_templates_null_workspace' AS check_name, COUNT(*) AS bad_rows
FROM `form_templates` WHERE `workspace_id` IS NULL OR `workspace_id` = '';
SELECT 'daily_entries_null_workspace' AS check_name, COUNT(*) AS bad_rows
FROM `daily_entries` WHERE `workspace_id` IS NULL OR `workspace_id` = '';
SELECT 'report_tasks_null_workspace' AS check_name, COUNT(*) AS bad_rows
FROM `report_tasks` WHERE `workspace_id` IS NULL OR `workspace_id` = '';
SELECT 'audit_logs_null_workspace' AS check_name, COUNT(*) AS bad_rows
FROM `audit_logs` WHERE `team_id` IS NOT NULL AND (`workspace_id` IS NULL OR `workspace_id` = '');

SELECT 'workspace_members_distinct' AS check_name,
       COUNT(*) AS member_rows,
       COUNT(DISTINCT CONCAT(`workspace_id`, ':', `user_id`)) AS distinct_rows
FROM `workspace_members`;

SELECT 'departments_depth_over_3' AS check_name, COUNT(*) AS bad_rows
FROM `departments` WHERE `depth` > 3;
