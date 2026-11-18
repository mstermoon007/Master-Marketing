# 报数机器人AI · 服务端部署说明

自有服务端（Python 3 + FastAPI + MySQL 8），替代原微信云开发云函数。
对外保持同一套 `action + payload` 契约，小程序端 11 个页面共用同一套 action。

> 项目总览见 [`../README.md`](../README.md)，完整接口/数据表/回归清单见 [`../docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md)。
> 本文件只讲**服务端部署与运维**，接口与字段约定以开发文档为准。

## 目录

| 路径 | 说明 |
|---|---|
| `app/main.py` | FastAPI 应用：`/auth/login`、`/auth/web/*`、`/api`、`/api/export/entries`、`/health` |
| `app/auth.py` | `code2session` + 小程序/Web 双 aud JWT 签发/验签 |
| `app/config.py` | 环境变量 + 启动时密钥校验 |
| `app/db.py` | MySQL 连接、字符串主键、JSON 列、标识符白名单 |
| `app/handlers/` | 47 个在用业务 action（团队/成员/模板/录入/任务/分析/组织/审计/Web） |
| `app/services/` | 应提交口径、指标计算、规则引擎、分析执行、组织权限、微信客户端、Excel 导出（单点实现） |
| `app/init_db.py` | 幂等建表入口 |
| `sql/schema.sql` | 15 张表全量 DDL + 唯一索引（全新安装用） |
| `sql/migrate_p2_report_tasks.sql` | P2 增量迁移：填报任务表（存量库用，幂等） |
| `sql/migrate_p3_analysis.sql` | P3 增量迁移：分析引擎 5 张表（存量库用，幂等，依赖 P2） |
| `sql/migrate_p4_workspaces.sql` | P4 增量迁移：工作空间/部门/空间成员 + 冗余 `workspace_id`（幂等，依赖 P3） |
| `sql/migrate_p4_rollback.sql` | P4 回滚（有损，只回滚结构，先备份） |
| `sql/migrate_p5_web_tickets.sql` | P5 增量迁移：Web 扫码登录票据表（幂等，依赖 P4） |
| `sql/migrate_p5_rollback.sql` | P5 回滚：仅删除 `web_login_tickets`，不影响业务数据 |
| `tests/` | 契约、鉴权与业务流程单元测试（不依赖真实 MySQL） |
| `finish.sh` | 6 项静态验证（项目根执行）；只验证，不修改或删除任何文件 |

## 部署步骤

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # 填入 DB / WX_APPID / WX_SECRET / JWT_SECRET
python -m app.init_db     # 建库建表（全新安装：15 张表，幂等）
python -m pytest -q       # 部署前回归
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

生产建议 `gunicorn -k uvicorn.workers.UvicornWorker` 或 systemd 托管，前面挂 Nginx 终止 TLS。
环境变量清单与含义见开发文档 §10；`.env` 已由 `.gitignore` 排除，不得入库。

### 存量库升级（已在用旧版表结构）

`app.init_db` 只执行 `CREATE TABLE IF NOT EXISTS`，**不会给已有表补新增列**。存量库按顺序执行增量迁移：

```bash
cd server

# P2：填报任务表（依赖 teams / form_templates）
docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao \
  < sql/migrate_p2_report_tasks.sql

# P3：分析引擎 5 张表（依赖 P2 的 report_tasks）
docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao \
  < sql/migrate_p3_analysis.sql

# P4：工作空间 / 部门 / 空间成员，回填 workspace_id（依赖 P3）
docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao \
  < sql/migrate_p4_workspaces.sql

# P5：Web 扫码登录票据表（依赖 P4）
docker exec -i jinribao-mysql mysql -uroot -p"$DB_PASSWORD" jinribao \
  < sql/migrate_p5_web_tickets.sql
```

- 上述增量脚本均幂等：重复执行不报错、不丢数据，可在部署流水线里反复跑。
- 脚本末尾自带部署自检 `SELECT`：
  - P2 返回 `report_tasks` 列数与 `has_scope_json`（应为 `15` / `1`），`uk_task_team_key` 唯一键计数应为 `1`。
  - P3 返回 5 张表列数（`10 / 10 / 15 / 14 / 11`），三个唯一键 `uk_analysis_idem` / `uk_result_task` / `uk_finding_task_code` 计数均应为 `1`。
  - P4 的 `*_null_workspace` 四项应为 `0`；`workspace_count` 应等于 `team_count`；
    `workspace_members_distinct.member_rows` 应等于 `distinct_rows`；`departments_depth_over_3` 应为 `0`。
  - P5 的 `web_login_tickets_exists` 应为 `1`。
- P4 回滚（`migrate_p4_rollback.sql`）**有损**：删除三张组织表与全部 P4 新增列，执行前必须全库备份并先把应用回退到 P3。
- P5 回滚（`migrate_p5_rollback.sql`）只删除 `web_login_tickets`，业务数据不受影响；建议先下线 Web 静态站点。
- 自检数字不符即视为迁移未生效，先排查再启动服务。
- 非 Docker 部署把 `docker exec -i jinribao-mysql mysql ...` 换成 `mysql -h <host> -u <user> -p <db>` 即可，脚本内含 `SET NAMES utf8mb4;`。


## Web 管理后台（P5）

### 构建与部署

```bash
cd web
cp .env.example .env.local      # 生产：VITE_API_BASE=https://api.modouyu.top
npm ci
npm run build                   # 产物在 web/dist/
```

- 静态站点部署到独立子域 `admin.modouyu.top`，Nginx 需配置 SPA 回退：`try_files $uri $uri/ /index.html;`。
- API 服务端设置 `WEB_ORIGIN=https://admin.modouyu.top`；CORS 只放行该来源与本地 `5173` 端口。
- 小程序码跳转页面固定为 `pages/login-confirm/login-confirm`，发布小程序时必须包含该页面。
- 本地联调：`cd web && npm run dev`，Vite 会把 `/api`、`/auth` 代理到 `127.0.0.1:8000`。

### 登录与权限

- `POST /auth/web/ticket` 生成 5 分钟一次性票据并返回小程序码；Web 端 1.5 秒轮询状态。
- 仅空间所有者可确认登录：`confirmWebLogin` 校验 `workspaces.owner_uid`（老数据回退 `teams.owner_uid`）。
- Web 令牌 `aud=web`、默认 12 小时；小程序令牌 `aud=mini`、30 天，二者互不通用。
- Web 令牌只能调用 `handlers.WEB_ACTIONS` 白名单；`saveEntry` / `getMyEntry` / `listMyEntries` / `confirmWebLogin` 一律拒绝。
- 每个 Web 请求仍按数据库实时校验空间 owner/admin，不信任令牌内嵌的空间列表。
- `access_token` 由 `services/wechat.py` 内存缓存，提前 300 秒刷新；微信原始错误码不下发客户端。

## 小程序端必须同步配置

1. `utils/config.js` 的 `RELEASE_BASE` / `DEV_BASE` 换成你的 HTTPS 域名。
2. 微信公众平台 → 开发管理 → 服务器域名 → **request 合法域名** 加入该域名。
   要求：HTTPS、已 ICP 备案、证书有效；不支持 IP 与 localhost。
3. 开发期可在微信开发者工具「详情 → 本地设置」勾选「不校验合法域名」，
   但**真机预览与上线必须完成第 2 步**。

## 安全约定

- `WX_SECRET` / `JWT_SECRET` 只在服务端环境变量，**绝不写入小程序包**。
- 客户端传来的 `uid` / `openid` / `user_id` 一律忽略，身份只取 JWT 的 `sub`。
- 所有 SQL 参数化；写入字段走白名单，防止主键与归属字段被客户端改写。
- 管理端操作全部经 `require_manager` 校验，不依赖前端隐藏按钮；审计 `log` 校验团队归属。
- 模板发布必须走 `publishTemplate`；`createDraft` 强制 draft，`updateTemplateRow` 只允许停用为 archived。发布保留草稿里设定的 `effective_from`，不用前端 today 覆盖。
- **多工作空间（P4）**：一人可属多个空间与团队；`createTeam` / `joinTeam` 不再限制「一人一团队」，切换由 `switchWorkspace` 按团队/空间校验归属。
- **权限统一走 `services/org.py`**：团队 owner/manager > 空间 owner/admin > 部门负责人 > 团队/空间 member/viewer；`require_writer` 拒绝 `viewer` 写入，`require_member` 允许空间管理员与部门负责人读取。
- **部门最多 3 级**：新建与移动均由服务端校验深度与环路；同名仅在同一空间同一上级下冲突。
- **跨空间隔离**：列表查询在 `team_id` 之外追加 `workspace_id`，写入的 `workspace_id` 由服务端按团队反查，不接受客户端传值。
- `removeMember` 为软移除（`status=disabled` + `left_at`），重新加入复用原行，不会撞 `uk_members_team_user`。
- `saveEntry` 校验模板归属，并对 `status=submitted` 按模板 fields 复核必填/类型/范围/选项；草稿不校验必填。
- `getMyMember` 对停用成员直接返回明确业务错误；`getMyEntry` / `listMyEntries` 均经 `require_member` 校验。
- `entry_date` 由服务端独立校验：格式 `YYYY-MM-DD`、最多回溯 31 天、不可为未来（UTC 与本地时区跨日各放宽 1 天）。改窗口需同步小程序 `utils/date.js` 的 `BACKFILL_DAYS`。
- `listTeamEntries` 支持 `page` / `pageSize`（单页上限 1000），`ORDER BY entry_date DESC, id DESC` 保证翻页稳定；小程序 `store.js` 自动拉全，超 50 页会明确报错而非静默截断。
- `getTemplate` 对 `draft` / `archived` 模板要求管理员权限，普通成员凭 id 无法预览未发布模板。
- `publishTemplate` 在事务内 `SELECT ... FOR UPDATE` 锁团队行，冲突时把草稿 `version` 顺延到 `MAX(version)+1`，避免并发发布撞 `uk_tpl_team_id_ver`。
- **Web / 小程序令牌隔离（P5）**：`aud` 区分 `web` 与 `mini`；Web 令牌仅能调用显式白名单 action，小程序令牌不能续期 Web 会话。
- **扫码票据一次性**：`SELECT ... FOR UPDATE` + `confirmed → consumed` 事务消费，重复轮询不会重复发令牌；5 分钟过期，创建新票据时清理 24 小时前历史行。
- **Excel 导出**：`POST /api/export/entries` 复用 `require_manager`，列头与数据页一致；上限 50000 行，超过提示缩小范围。

## 响应契约（速查）

```
POST /auth/login  {"code": "wx.login 返回的 code"}
 -> {"ok": true, "data": {"token": "...", "openid": "..."}}

POST /api  {"action": "listTemplates", "teamId": "T4K7QX"}   # 需 Bearer token
 -> {"ok": true, "data": [...]}   或  {"ok": false, "message": "..."}

POST /auth/web/ticket
 -> {"ok": true, "data": {"ticket": "32位hex", "qrcode": "data:image/png;base64,...", "expiresIn": 300}}

POST /auth/web/ticket/status  {"ticket": "..."}
 -> {"ok": true, "data": {"status": "pending|confirmed|consumed|expired"}}
 -> 确认后：{"ok": true, "data": {"status": "confirmed", "token": "...", "expiresIn": 43200, "workspaces": [...]}}

POST /auth/web/refresh   # Bearer aud=web token
 -> {"ok": true, "data": {"token": "...", "expiresIn": 43200}}

POST /api/export/entries  {"teamId": "...", "startDate": "YYYY-MM-DD", "endDate": "YYYY-MM-DD"}
 -> xlsx 二进制流（Content-Disposition: attachment）
```

`401` 表示登录过期，前端 `utils/http.js` 会清理本地登录态并引导重新登录；Web 端 `api/client.ts` 同样会跳回 `/login`。

## 字段与格式约定（回归关键）

- 主键为 24 位 hex 字符串 `id`，等价于旧云库的 `_id`，前端无需 `normalize`。
- 时间统一 ISO8601 UTC 字符串（`2026-11-09T09:08:02.000Z`），保障 `records.js` 的补录判定。
- `entry_date` / `effective_from` 为 `YYYY-MM-DD`，按字典序比较区间；`entry_date` 限于近 31 天补录窗口。
- `daily_entries` 唯一键 `(team_id, user_id, entry_date)` 保障 `saveEntry` 幂等；补录与当日提交共用该键。
- 补录沿用当前生效模板，历史版本发布时已归档；`source` 以 `backfill` 标记，不影响统计口径。

> 数据库名、logger、JWT issuer 仍使用内部标识 `jinribao`，与展示名称「报数机器人AI」无关，
> 改动会牵动已配置的 `.env`，请勿随项目改名一并修改。
