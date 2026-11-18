-- 报数机器人AI · P6 回滚：调度心跳
--
-- 仅删除 `scheduler_heartbeats`（纯运行状态，不含业务数据）。
-- 执行前先停调度容器：docker compose stop scheduler
-- 否则调度进程会继续写已删除的表并报错。

SET NAMES utf8mb4;
USE `jinribao`;

DROP TABLE IF EXISTS `scheduler_heartbeats`;

-- 回滚自检（应为 0）
SELECT 'scheduler_heartbeat_table_exists' AS check_name,
       COUNT(*) AS table_count
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'scheduler_heartbeats';
