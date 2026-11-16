-- P2 增量迁移：新增填报任务表（幂等，可重复执行）
--
-- 生产执行（示例）：
--   docker exec -i jinribao-mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" jinribao \
--     < server/sql/migrate_p2_report_tasks.sql
--
-- 说明：当前租户边界仍是 team_id；P4 引入工作空间后再补 workspace_id 与回填。

USE `jinribao`;

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
