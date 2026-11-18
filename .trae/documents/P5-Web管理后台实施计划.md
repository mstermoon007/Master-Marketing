# P5 Web 管理后台实施计划

> 依据 `docs/UPGRADE_PLAN.md` §3.3 / §6.1 / §7 P5，结合 P4 已交付的组织模型。
> 已确认：Web 工程放当前仓库 `web/`；仅空间 owner 可扫码登录；独立子域部署。

## 1. 目标与边界

**目标**：为空间所有者/管理员提供复杂配置与批量管理能力，小程序继续只做移动填报。

**范围**
- 扫码登录（小程序码 + 轮询，一次性 ticket）
- 工作台（提交概览、任务进度、异常提示）
- 组织管理（空间、部门、团队、成员、角色）
- 模板中心（列表、编辑、发布、版本）
- 填报任务（创建、列表、关闭）
- 数据中心（按团队/日期/模板筛选，分页）
- 报表中心（分析结果查看）+ Excel 导出
- 操作审计

**不做**
- 富文本/图表主题定制、异步导出队列、消息通知（P6）
- Web 端填报、修改日报、移动端适配
- 新的权限体系（完全复用 P4 `services/org.py`）

## 2. 架构与登录时序

```text
Web(admin.modouyu.top)                API(api.modouyu.top)                小程序
  │ POST /auth/web/ticket                  │                                │
  │───────────────────────────────────────>│ 生成 ticket(5min, 一次性)      │
  │<────── {ticket, qrcode, expiresIn} ────│ wxacode.getUnlimited(scene)    │
  │ 展示小程序码，1.5s 轮询                  │                                │
  │ POST /auth/web/ticket/status {ticket}   │                                │
  │───────────────────────────────────────>│                                │
  │                                        │<── 扫码进入 pages/login-confirm │
  │                                        │    confirmWebLogin{ticket}      │
  │                                        │    校验 space owner → confirmed │
  │<──── {status, token(aud=web), spaces} ──│                                │
```

- ticket：32 位随机 hex，`status` 为 `pending / confirmed / consumed / expired`，5 分钟过期，轮询成功即消费。
- Web token：`aud=web`，12 小时；小程序 token 无 `aud` 或 `aud=mini`，30 天。二者互不通用。
- `confirmWebLogin` 仅接受小程序 token；校验 `workspaces.owner_uid = uid`（老数据回退 `teams.owner_uid = uid`）。
- 每个 Web 请求仍按数据库实时校验 owner 身份，不信任 token 内嵌的空间列表。
- 小程序码依赖 `access_token`，新增带内存缓存的微信客户端（提前 5 分钟刷新）。

## 3. 数据模型

新增 `web_login_tickets`（schema.sql + `migrate_p5_web_tickets.sql`）：

```sql
CREATE TABLE IF NOT EXISTS `web_login_tickets` (
  `id` CHAR(24) NOT NULL,
  `ticket` CHAR(32) NOT NULL,
  `user_id` VARCHAR(128) NULL,
  `status` VARCHAR(16) NOT NULL DEFAULT 'pending',
  `workspace_ids` JSON NULL,
  `client_ip` VARCHAR(64) NULL,
  `created_at` VARCHAR(32) NOT NULL,
  `expires_at` VARCHAR(32) NOT NULL,
  `confirmed_at` VARCHAR(32) NULL,
  `consumed_at` VARCHAR(32) NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_web_ticket` (`ticket`),
  KEY `idx_web_ticket_status` (`status`, `expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- `db.JSON_COLUMNS` 增加 `web_login_tickets: ["workspace_ids"]`。
- 清理：每次创建 ticket 时顺手删除 24 小时前的过期行（同事务内 DELETE）。
- 回滚：`migrate_p5_rollback.sql` 仅 `DROP TABLE IF EXISTS web_login_tickets`（无业务数据损失）。

## 4. 服务端改动

### 4.1 认证（`app/auth.py`、`app/main.py`、`app/config.py`）

- `issue_token(..., audience="mini")` 写入 `aud`，保持小程序调用兼容。
- 新增 `issue_web_token(openid)`：`aud="web"`，TTL 取 `WEB_TOKEN_TTL_HOURS`（默认 12）。
- 新增 `extract_claims(auth_header)` 返回完整 claims；`extract_uid` 保留。
- `/api`：`aud=web` 时只允许 `WEB_ACTIONS` 白名单；`aud=mini` 时拒绝 `WEB_ONLY_ACTIONS`（如 `getWorkspaceOverview`、`listAuditLogs` 可两端共用，`confirmWebLogin` 仅小程序）。
- 新增公开端点：
  - `POST /auth/web/ticket` → `{ticket, qrcode, expiresIn}`
  - `POST /auth/web/ticket/status` → `{status, token?, workspaces?}`
  - `POST /auth/web/refresh`（Bearer web token）→ `{token}`
- CORS 收紧为 `WEB_ORIGIN`（默认 `https://admin.modouyu.top`），环境变量缺失时仅允许本地调试源。

### 4.2 微信小程序码（新增 `app/services/wechat.py`）

- `get_access_token()`：`cgi-bin/token`，内存缓存，提前 300 秒刷新，失败不清空旧值。
- `get_unlimited_qrcode(scene, page)`：`wxa/getwxacodeunlimit`，`check_path=false`，返回 PNG bytes → base64 data URL。
- 超时/微信错误统一转为 `BusinessError("小程序码生成失败，请稍后重试")`，不泄露原始错误码。

### 4.3 新增 action（3 个，44 → 47）

| action | 说明 | 权限 |
|---|---|---|
| `confirmWebLogin` | 小程序确认扫码登录，返回可管理的空间 | 小程序 token；空间 owner |
| `getWorkspaceOverview` | 工作台汇总：今日应提交/已提交/提交率、未提交人数、活跃任务、近 7 天趋势、最近异常数 | 空间 owner/admin |
| `listAuditLogs` | 审计分页查询（workspace_id + 时间范围 + actor/action 过滤） | 空间 owner/admin |

- 工作台指标必须调用 `services/dataset.load_dataset` + `services/metrics.compute`，不得另写口径（红线 7）。
- `listAuditLogs` 按 `workspace_id` 强制过滤，`LIMIT/OFFSET` 参数化。

### 4.4 Web 白名单

`server/app/handlers/__init__.py` 增加 `WEB_ACTIONS`（显式集合）：
- 只读：`listMyWorkspaces`、`switchWorkspace`、`listWorkspaceMembers`、`listDepartments`、`listTemplates`、`getTemplate`、`listReportTasks`、`getReportTask`、`getReportTaskStatus`、`listTeamEntries`、`listAnalysisTasks`、`getAnalysisTask`、`listAnalysisFindings`、`getAnalysisOverview`、`getWorkspaceOverview`、`listAuditLogs`
- 管理：`createTeam`、`updateTeamConfig`、`updateMember`、`removeMember`、`createWorkspace`、`updateWorkspace`、`updateWorkspaceMember`、`createDepartment`、`updateDepartment`、`createDraft`、`updateTemplateRow`、`deleteTemplateRow`、`nextVersion`、`publishTemplate`、`createReportTask`、`closeReportTask`
- 明确排除：`getMyMember`、`getMyEntry`、`saveEntry`、`listMyEntries`、`log`、`confirmWebLogin`
- 拒绝时统一返回「Web 端无权调用该操作」。

### 4.5 Excel 导出

- 新增 `openpyxl>=3.1,<4.0` 依赖。
- `POST /api/export/entries`：Bearer（小程序或 Web 均可），body `{teamId, startDate, endDate, templateId?}`。
- 权限与 `listTeamEntries` 完全一致（`require_manager`），导出列与页面一致，含表头、字段中文名、提交状态。
- `openpyxl` `write_only` 模式，每 1000 行写一批，最多 50000 行，超出提示缩小范围。
- 返回 `StreamingResponse`，文件名 `entries_{teamId}_{start}_{end}.xlsx`。

## 5. 小程序改动

- 新增页面 `pages/login-confirm/login-confirm` 并注册：
  - 解析 `scene`（ticket），展示「网页端请求登录」与空间名；
  - 按钮「确认登录」→ `store.confirmWebLogin(ticket)`；
  - 结果提示后关闭/回首页。
- `utils/store.js` 增加 `confirmWebLogin(ticket)`。
- 不改变现有填报、团队切换逻辑。

## 6. Web 工程（`web/`）

```text
web/
  package.json  vite.config.ts  tsconfig.json  index.html  .env.example
  src/
    main.ts  App.vue
    api/client.ts        # fetch 封装、Bearer、401 跳登录
    api/types.ts         # 与 server 契约对应的 TS 类型
    stores/auth.ts       # token、workspaces、当前空间
    stores/workspace.ts   # 部门/团队/成员缓存
    router/index.ts      # 路由守卫：无 token → /login
    layouts/AdminLayout.vue
    views/LoginView.vue  DashboardView.vue
    views/OrgView.vue    TemplatesView.vue  TasksView.vue
    views/DataView.vue   AnalysisView.vue   AuditView.vue
    components/ExportButton.vue  PageHeader.vue
```

- 技术栈：Vue 3 + Vite + TypeScript + Element Plus + Pinia + Vue Router。
- 登录页：二维码展示 + 状态文案 + 过期自动刷新（重新申请 ticket）。
- 组织页：左侧空间/部门树，右侧团队与成员；P4 的 9 个 action 全部复用。
- 模板/任务/数据/分析/审计页：表格 + 筛选 + 分页；写操作二次确认。
- 导出按钮：请求二进制流，`Blob` 下载，失败展示后端 message。
- 不引入图表库；工作台用 Element Plus 进度条、统计卡与表格。

## 7. 权限矩阵（Web）

| 能力 | 空间 owner | 空间 admin | 部门负责人 | 团队负责人 | 成员/viewer |
|---|---|---|---|---|---|
| 扫码登录 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 工作台/审计 | ✅ | ✅（授权范围） | ❌ | ❌ | ❌ |
| 空间配置 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 部门/成员/角色 | ✅ | ✅（不含空间 owner） | 只读本部门 | 只读本团队 | ❌ |
| 模板/任务 | ✅ | ✅ | ✅ 本部门 | ✅ 本团队 | ❌ |
| 数据/导出 | ✅ | ✅ | ✅ 本部门 | ✅ 本团队 | ❌ |
| 分析结果 | ✅ | ✅ | ✅ 本部门 | ❌ | ❌ |

> 最终以服务端 `require_*` + `org.effective_role` 判定为准；前端只做展示裁剪。

## 8. 任务拆解

| 编号 | 任务 | 产物 |
|---|---|---|
| p5-1 | 数据层：`web_login_tickets` + schema/迁移/回滚 + JSON 白名单 | SQL、`db.py` |
| p5-2 | 认证：`aud` 隔离、Web token、ticket 生命周期、`extract_claims` | `auth.py`、`main.py`、`config.py` |
| p5-3 | 微信客户端：access_token 缓存 + 无限制小程序码 | `services/wechat.py` |
| p5-4 | 3 个 action：确认登录、工作台、审计；`WEB_ACTIONS` 白名单 | handlers、`__init__.py` |
| p5-5 | Excel 导出端点 + `openpyxl` 依赖 | `main.py`、`services/export.py` |
| p5-6 | 小程序确认登录页 + store 封装 | `pages/login-confirm/*`、`utils/store.js` |
| p5-7 | Web 脚手架：Vite/TS/Element Plus/Pinia/Router、登录页、布局、守卫 | `web/` |
| p5-8 | Web 业务页：工作台、组织、模板、任务 | `web/src/views/*` |
| p5-9 | Web 业务页：数据、分析、审计、导出 | `web/src/views/*` |
| p5-10 | 测试、文档、部署与全套验证 | tests、README、Nginx 说明 |

## 9. 测试与验收

**服务端**
- `tests/test_web_auth.py`：ticket 创建/确认/消费/过期、重复消费、非 owner 拒绝、web/mini token 互斥、白名单拒绝、refresh。
- `tests/test_web_actions.py`：工作台复用 `metrics.compute`、审计强制 workspace 过滤、导出权限与列头、5 万行上限。
- `test_contract.py`：action 总数 47；JSON 表 15 张；迁移脚本断言。
- `python3 -m pytest -q`、`bash server/finish.sh` 全绿。

**Web**
- `cd web && npm ci && npm run type-check && npm run build` 通过。
- 手工：扫码登录 → 工作台 → 组织/模板/任务/数据/分析/审计 → 导出；Web token 调 `saveEntry` 被拒。

**验收**
- 仅空间 owner 可登录；admin 按授权范围可管理；
- 一人多空间可切换；小程序与 Web 数据一致；
- 导出权限与在线查询一致；Web token 12 小时且不能调用填报类 action。

## 10. 风险与应对

| 风险 | 应对 |
|---|---|
| 小程序码接口配额/失败 | 缓存 access_token；失败明确提示并允许重新生成 ticket |
| 轮询压力 | 1.5 秒间隔、5 分钟自动停止；ticket 唯一键 + 过期清理 |
| Web token 越权 | `aud` 隔离 + 显式白名单 + 每请求实时 owner 校验 |
| 导出大表 | 流式写、50000 行上限、按团队+日期索引 |
| 部署跨域 | 独立子域 + `WEB_ORIGIN` 白名单，不使用 `*` |

## 11. 上线顺序

1. 备份数据库 → 执行 `migrate_p5_web_tickets.sql`（幂等）。
2. 部署 API（新增环境变量 `WEB_ORIGIN`、`WEB_TOKEN_TTL_HOURS`），验证 `/health` 与旧 action。
3. 发布小程序（确认登录页）；旧版本小程序不受影响。
4. 构建 `web/dist` 并部署到 `admin.modouyu.top`。
5. 按 §9 验收；异常时下线 Web 静态站点即可回退，数据库表可保留。
