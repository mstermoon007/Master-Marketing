-- 报数机器人AI · MySQL 8 建表脚本
-- 字符集 utf8mb4 / 排序规则 utf8mb4_0900_ai_ci（MySQL 8 默认）
-- 执行：mysql -u root -p < sql/schema.sql

CREATE DATABASE IF NOT EXISTS `jinribao`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE `jinribao`;

-- 工作空间（P4）：组织根节点，一个空间可含多个部门与团队
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

-- 部门（P4）：树形，服务端限制最多 3 级；parent_key 让根部门的唯一键生效
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

-- 空间成员（P4）：一人可在多个空间；owner/admin/member/viewer
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

-- 团队
CREATE TABLE IF NOT EXISTS `teams` (
  `id`            CHAR(24)     NOT NULL,
  `team_id`       VARCHAR(32)  NOT NULL COMMENT '对外邀请码，如 T4K7QX',
  `workspace_id`  CHAR(24)     NULL COMMENT '所属工作空间（P4）',
  `department_id` CHAR(24)     NULL COMMENT '所属部门（P4）',
  `name`          VARCHAR(128) NOT NULL,
  `owner_uid`     VARCHAR(128) NOT NULL COMMENT 'openid',
  `config`        JSON         NULL COMMENT '{ memberSeeTeamTotal }',
  `created_at`    VARCHAR(32)  NOT NULL COMMENT 'ISO8601 UTC',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_teams_team_id` (`team_id`),
  KEY `idx_teams_workspace` (`workspace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 成员（一个 openid 在一个团队内唯一；一人可加入多个团队/工作空间）
CREATE TABLE IF NOT EXISTS `members` (
  `id`            CHAR(24)     NOT NULL,
  `team_id`       VARCHAR(32)  NOT NULL,
  `user_id`       VARCHAR(128) NOT NULL COMMENT 'openid',
  `name`          VARCHAR(64)  NOT NULL,
  `role`          VARCHAR(16)  NOT NULL DEFAULT 'member' COMMENT 'owner|manager|member|viewer',
  `status`        VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active|disabled',
  `department_id` CHAR(24)     NULL COMMENT '团队内所属部门（P4）',
  `left_at`       VARCHAR(32)  NULL COMMENT '离开时间；非空后可重新加入并复用该行',
  `joined_at`     VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_members_team_user` (`team_id`, `user_id`),
  KEY `idx_members_user` (`user_id`),
  KEY `idx_members_team` (`team_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 表单模板（同一 template_id 可有多版本）
CREATE TABLE IF NOT EXISTS `form_templates` (
  `id`             CHAR(24)     NOT NULL,
  `team_id`        VARCHAR(32)  NOT NULL,
  `workspace_id`   CHAR(24)     NULL COMMENT '冗余归属，服务端写入（P4）',
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
  KEY `idx_tpl_team_status` (`team_id`, `status`, `version`),
  KEY `idx_tpl_workspace` (`workspace_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 日录入（幂等：同一成员同一天只有一条）
CREATE TABLE IF NOT EXISTS `daily_entries` (
  `id`               CHAR(24)     NOT NULL,
  `team_id`          VARCHAR(32)  NOT NULL,
  `workspace_id`     CHAR(24)     NULL COMMENT '冗余归属，服务端写入（P4）',
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
  KEY `idx_entry_workspace_date` (`workspace_id`, `entry_date`),
  KEY `idx_entry_team_user_date` (`team_id`, `user_id`, `entry_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 填报任务（P2）：任务是被考核的下发单元，scope 为创建时的快照。
CREATE TABLE IF NOT EXISTS `report_tasks` (
  `id`               CHAR(24)     NOT NULL,
  `team_id`          VARCHAR(32)  NOT NULL,
  `workspace_id`     CHAR(24)     NULL COMMENT '冗余归属，服务端写入（P4）',
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
  KEY `idx_task_team_status` (`team_id`, `status`, `start_date`),
  KEY `idx_task_workspace_status` (`workspace_id`, `status`)
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

-- 审计日志（P4：空间级审计无 team_id）
CREATE TABLE IF NOT EXISTS `audit_logs` (
  `id`           CHAR(24)     NOT NULL,
  `team_id`      VARCHAR(32)  NULL,
  `workspace_id` CHAR(24)     NULL,
  `actor`        VARCHAR(128) NOT NULL COMMENT 'openid',
  `action`       VARCHAR(64)  NOT NULL,
  `target_type`  VARCHAR(64)  NULL,
  `target_id`    VARCHAR(128) NULL,
  `detail`       JSON         NULL,
  `created_at`   VARCHAR(32)  NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_audit_team_time` (`team_id`, `created_at`),
  KEY `idx_audit_workspace_time` (`workspace_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Web 扫码登录票据（P5）：一次性、5 分钟过期，轮询成功即消费
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
