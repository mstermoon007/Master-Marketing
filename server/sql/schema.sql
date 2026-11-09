-- 报数机器人AI · MySQL 8 建表脚本
-- 字符集 utf8mb4 / 排序规则 utf8mb4_0900_ai_ci（MySQL 8 默认）
-- 执行：mysql -u root -p < sql/schema.sql

CREATE DATABASE IF NOT EXISTS `jinribao`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE `jinribao`;

-- 团队
CREATE TABLE IF NOT EXISTS `teams` (
  `id`          CHAR(24)     NOT NULL,
  `team_id`     VARCHAR(32)  NOT NULL COMMENT '对外邀请码，如 T4K7QX',
  `name`        VARCHAR(128) NOT NULL,
  `owner_uid`   VARCHAR(128) NOT NULL COMMENT 'openid',
  `config`      JSON         NULL COMMENT '{ memberSeeTeamTotal }',
  `created_at`  VARCHAR(32)  NOT NULL COMMENT 'ISO8601 UTC',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_teams_team_id` (`team_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 成员（一个 openid 在一个团队内唯一）
CREATE TABLE IF NOT EXISTS `members` (
  `id`         CHAR(24)     NOT NULL,
  `team_id`    VARCHAR(32)  NOT NULL,
  `user_id`    VARCHAR(128) NOT NULL COMMENT 'openid',
  `name`       VARCHAR(64)  NOT NULL,
  `role`       VARCHAR(16)  NOT NULL DEFAULT 'member' COMMENT 'owner|manager|member',
  `status`     VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active|disabled',
  `joined_at`  VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_members_team_user` (`team_id`, `user_id`),
  KEY `idx_members_user` (`user_id`),
  KEY `idx_members_team` (`team_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 表单模板（同一 template_id 可有多版本）
CREATE TABLE IF NOT EXISTS `form_templates` (
  `id`             CHAR(24)     NOT NULL,
  `team_id`        VARCHAR(32)  NOT NULL,
  `template_id`    VARCHAR(64)  NOT NULL,
  `version`        INT          NOT NULL DEFAULT 1,
  `name`           VARCHAR(128) NOT NULL,
  `description`    VARCHAR(512) NULL,
  `entry_mode`     VARCHAR(16)  NOT NULL DEFAULT 'single',
  `status`         VARCHAR(16)  NOT NULL DEFAULT 'draft' COMMENT 'draft|published|archived',
  `fields`         JSON         NULL COMMENT '字段定义数组',
  `scope`          JSON         NULL COMMENT '下发范围 {type,memberIds,roles}',
  `effective_from` VARCHAR(10)  NULL COMMENT 'YYYY-MM-DD',
  `created_by`     VARCHAR(128) NULL,
  `created_at`     VARCHAR(32)  NULL,
  `published_by`   VARCHAR(128) NULL,
  `published_at`   VARCHAR(32)  NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_tpl_team_id_ver` (`team_id`, `template_id`, `version`),
  KEY `idx_tpl_team_status` (`team_id`, `status`, `version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 日录入（幂等：同一成员同一天只有一条）
CREATE TABLE IF NOT EXISTS `daily_entries` (
  `id`               CHAR(24)     NOT NULL,
  `team_id`          VARCHAR(32)  NOT NULL,
  `user_id`          VARCHAR(128) NOT NULL COMMENT 'openid',
  `entry_date`       VARCHAR(10)  NOT NULL COMMENT 'YYYY-MM-DD',
  `template_id`      VARCHAR(64)  NULL,
  `template_version` INT          NULL,
  `form_data`        JSON         NULL COMMENT '[{rowId, values}]',
  `status`           VARCHAR(16)  NOT NULL DEFAULT 'draft' COMMENT 'draft|submitted',
  `source`           VARCHAR(32)  NULL,
  `created_at`       VARCHAR(32)  NULL,
  `updated_at`       VARCHAR(32)  NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_entry_team_user_date` (`team_id`, `user_id`, `entry_date`),
  KEY `idx_entry_team_date` (`team_id`, `entry_date`),
  KEY `idx_entry_team_user_date` (`team_id`, `user_id`, `entry_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 审计日志
CREATE TABLE IF NOT EXISTS `audit_logs` (
  `id`          CHAR(24)     NOT NULL,
  `team_id`     VARCHAR(32)  NOT NULL,
  `actor`       VARCHAR(128) NOT NULL COMMENT 'openid',
  `action`      VARCHAR(64)  NOT NULL,
  `target_type` VARCHAR(64)  NULL,
  `target_id`   VARCHAR(128) NULL,
  `detail`      JSON         NULL,
  `created_at`  VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_audit_team_time` (`team_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
