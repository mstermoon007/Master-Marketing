-- P3 确定性分析引擎：5 张分析表（幂等，可重复执行）
-- 执行：mysql -u root -p jinribao < sql/migrate_p3_analysis.sql
-- 说明：只新增分析表，不修改任何业务表结构；指标/规则注册数据由服务层
--       ensure_registry() 首次运行时幂等写入，避免 SQL 与代码两份口径。

USE `jinribao`;

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
