-- 报数机器人AI · P6 回滚：删除订阅设置与通知记录
--
-- 影响：仅删除 `notification_settings` / `notification_logs` 两张 P6 新表；
--       团队、模板、录入、分析等业务数据不受影响。
-- 前置：先把应用回退到 P5（不再启动调度器），避免运行中写已删除的表。
--
-- 部署：
--   docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao < server/sql/migrate_p6_rollback.sql

SET NAMES utf8mb4;
USE `jinribao`;

DROP TABLE IF EXISTS `notification_logs`;
DROP TABLE IF EXISTS `notification_settings`;

-- 部署自检（应为 0）
SELECT 'notification_tables_after_rollback' AS check_name,
       COUNT(*) AS table_count
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('notification_settings', 'notification_logs');
