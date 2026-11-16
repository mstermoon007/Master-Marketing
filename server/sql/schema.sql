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

-- 填报任务（P2）：任务是被考核的下发单元，scope 为创建时的快照。
-- 当前阶段仍以 team_id 为租户边界；P4 引入工作空间后再补 workspace_id。
CREATE TABLE IF NOT EXISTS `report_tasks` (
  `id`               CHAR(24)     NOT NULL,
  `team_id`          VARCHAR(32)  NOT NULL,
  `task_key`         VARCHAR(64)  NOT NULL COMMENT '团队内稳定标识',
  `title`            VARCHAR(128) NOT NULL,
  `template_id`      VARCHAR(64)  NOT NULL,
  `template_version` INT          NULL,
  `scope`            JSON         NULL COMMENT '任务下发范围快照 {type,memberIds,roles}',
  `start_date`       VARCHAR(10)  NOT NULL COMMENT 'YYYY-MM-DD',
  `end_date`         VARCHAR(10)  NULL COMMENT 'YYYY-MM-DD，空表示长期',
  `due_time`         VARCHAR(8)   NULL COMMENT 'HH:MM，当日截止时间',
  `workdays_only`    TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1=仅工作日应提交',
  `status`           VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active|closed',
  `created_by`       VARCHAR(128) NULL,
  `created_at`       VARCHAR(32)  NOT NULL,
  `closed_at`        VARCHAR(32)  NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_team_key` (`team_id`, `task_key`),
  KEY `idx_task_team_status` (`team_id`, `status`, `start_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 分析指标注册表（P3）：metric_code + version 唯一，口径由服务层单点实现
CREATE TABLE IF NOT EXISTS `analysis_metrics` (
  `id`          CHAR(24)     NOT NULL,
  `metric_code` VARCHAR(64)  NOT NULL,
  `version`     INT          NOT NULL DEFAULT 1,
  `name`        VARCHAR(64)  NOT NULL,
  `category`    VARCHAR(32)  NOT NULL DEFAULT 'core',
  `unit`        VARCHAR(16)  NULL,
  `formula`     VARCHAR(255) NULL,
  `description` VARCHAR(512) NULL,
  `status`      VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active|inactive',
  `created_at`  VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_metric_code_ver` (`metric_code`, `version`),
  KEY `idx_metric_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 分析规则定义（P3）：阈值放 params，不硬编码
CREATE TABLE IF NOT EXISTS `analysis_rules` (
  `id`             CHAR(24)     NOT NULL,
  `rule_code`      VARCHAR(64)  NOT NULL,
  `version`        INT          NOT NULL DEFAULT 1,
  `name`           VARCHAR(128) NOT NULL,
  `level`          VARCHAR(16)  NOT NULL DEFAULT 'warning' COMMENT 'info|warning|critical',
  `condition_text` VARCHAR(512) NULL,
  `description`    VARCHAR(512) NULL,
  `params`         JSON         NULL COMMENT '{ threshold }',
  `status`         VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active|inactive',
  `created_at`     VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_rule_code_ver` (`rule_code`, `version`),
  KEY `idx_rule_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 分析任务（P3）：幂等唯一键见升级文档 §3.4，重复触发不产生第二条结果
CREATE TABLE IF NOT EXISTS `analysis_tasks` (
  `id`             CHAR(24)     NOT NULL,
  `team_id`        VARCHAR(32)  NOT NULL,
  `analysis_type`  VARCHAR(32)  NOT NULL DEFAULT 'period' COMMENT 'period',
  `period_start`   VARCHAR(10)  NOT NULL COMMENT 'YYYY-MM-DD',
  `period_end`     VARCHAR(10)  NOT NULL COMMENT 'YYYY-MM-DD',
  `scope`          JSON         NULL COMMENT '本次实际计算范围快照',
  `status`         VARCHAR(16)  NOT NULL DEFAULT 'running' COMMENT 'running|success|failed',
  `metric_version` INT          NOT NULL DEFAULT 1,
  `rule_version`   INT          NOT NULL DEFAULT 1,
  `request_by`     VARCHAR(128) NULL,
  `error_message`  VARCHAR(512) NULL,
  `retry_count`    INT          NOT NULL DEFAULT 0,
  `created_at`     VARCHAR(32)  NOT NULL,
  `started_at`     VARCHAR(32)  NULL,
  `finished_at`    VARCHAR(32)  NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_analysis_idem` (`team_id`, `analysis_type`, `period_start`, `period_end`, `rule_version`),
  KEY `idx_analysis_team_time` (`team_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 分析结果（P3）：每个任务一条，含快照时间/指标版本/规则版本/执行号，可追溯
CREATE TABLE IF NOT EXISTS `analysis_results` (
  `id`                 CHAR(24)     NOT NULL,
  `task_id`            CHAR(24)     NOT NULL,
  `team_id`            VARCHAR(32)  NOT NULL,
  `analysis_type`      VARCHAR(32)  NOT NULL DEFAULT 'period',
  `period_start`       VARCHAR(10)  NOT NULL,
  `period_end`         VARCHAR(10)  NOT NULL,
  `data_snapshot_time` VARCHAR(32)  NOT NULL,
  `metric_version`     INT          NOT NULL DEFAULT 1,
  `rule_version`       INT          NOT NULL DEFAULT 1,
  `execution_id`       VARCHAR(64)  NOT NULL,
  `summary`            JSON         NULL COMMENT '指标/日报表/质量检查',
  `data_quality`       JSON         NULL COMMENT '缺失/重复/类型/单位',
  `report_text`        MEDIUMTEXT   NULL COMMENT '结构化拼接报告，无模型生成',
  `created_at`         VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_result_task` (`task_id`),
  KEY `idx_result_team_time` (`team_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 分析发现/异常明细（P3）：每条可回溯到规则与具体数据行
CREATE TABLE IF NOT EXISTS `analysis_findings` (
  `id`            CHAR(24)     NOT NULL,
  `task_id`       CHAR(24)     NOT NULL,
  `result_id`     CHAR(24)     NULL,
  `rule_code`     VARCHAR(64)  NOT NULL,
  `rule_version`  INT          NOT NULL DEFAULT 1,
  `level`         VARCHAR(16)  NOT NULL DEFAULT 'info',
  `finding_code`  VARCHAR(128) NOT NULL,
  `title`         VARCHAR(255) NOT NULL,
  `detail`        JSON         NULL,
  `data_refs`     JSON         NULL,
  `created_at`    VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_finding_task_code` (`task_id`, `finding_code`),
  KEY `idx_finding_task` (`task_id`)
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
