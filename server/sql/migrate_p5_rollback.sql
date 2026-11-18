-- 报数机器人AI · P5 回滚：移除 Web 扫码登录票据
--
-- 说明：
--   - 仅删除 `web_login_tickets`，不触碰任何业务数据；
--   - 回滚后 Web 管理后台无法扫码登录，小程序填报不受影响；
--   - 建议先下线 Web 静态站点，再执行本脚本。
--
-- 用法：
--   docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao < server/sql/migrate_p5_rollback.sql

SET NAMES utf8mb4;
USE `jinribao`;

DROP TABLE IF EXISTS `web_login_tickets`;

SELECT 'rollback_done' AS check_name, 1 AS done;
