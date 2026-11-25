# 报数机器人AI · 开发文档

> 版本：2.1（自有服务器架构）｜更新日期：2026-11-18
> 适用代码：小程序前端根目录 + `server/` 服务端工程。本文是唯一开发依据；`CODEBUDDY.md` 已改写为自有服务端开发约定（强制约束仍有效）；`rules/`、`codebuddy-plugin/` 为旧 CloudBase 脚手架残留，**已物理删除**（见 §14）。

---

## 0. 文档职责与阶段口径

### 0.1 文档职责（避免重复维护）

| 文档 | 唯一职责 | 不写什么 |
|---|---|---|
| `README.md` | 项目总览、快速开始、上线清单 | 不复述接口与表结构，只链接本文 |
| **`docs/DEVELOPMENT.md`（本文）** | **唯一事实源**：架构、接口契约、数据表、安全/回归清单、阶段口径 | 不写部署命令细节（见 `server/README.md`） |
| `server/README.md` | 服务端部署与运维：环境变量、迁移执行、容器、Web 构建 | 不重复接口契约 |
| `CODEBUDDY.md` | IDE 强制约束：禁止云开发、权限与口径红线 | 不写流程细节 |
| `docs/UPGRADE_PLAN.md` | 历史规划存档（已冻结） | 不作为当前实现依据 |
| `.trae/documents/` | P4/P5 实施计划存档 | 同上 |

**冲突处理**：文档间数字或命令不一致时，以本文与代码/脚本的实际行为为准，并在同一轮修改中同步其余文档。

### 0.2 阶段编号口径

产品演进使用 **P** 编号，工程质量轮次使用 **G** 编号，二者不混用：

| 编号 | 主题 | 状态 |
|---|---|---|
| P0 | 系统审计与基线 | 已交付（历史） |
| P1 | 填报体验升级 | 已交付 |
| P2 | 模板字段规范与填报任务 | 已交付 |
| P3 | 确定性分析引擎 | 已交付 |
| P4 | 组织与多工作空间 | 已交付 |
| P5 | Web 管理后台 | 已交付 |
| P6 | 消息通知与调度 | 已交付 |
| P7 | 通知去重按租户隔离 | 已交付 |
| P8 | 分析任务空间归属 | 已交付 |
| G0 | 去重隔离与订阅授权 | 已交付 |
| G1 | 工程护栏（action 元数据 / 模板单一来源 / DB 集成 / 租户字段） | 已交付 |
| G2 | 质量加固（静态检查 / 前端测试 / 安全 / 细节治理 / 启动竞态） | 已交付 |

> 历史变更记录中的「工程护栏（P1）」「静态检查（P2）」等写法已统一改为 G1/G2；新增文档不得再用 P 编号表示工程质量任务。

### 0.3 命令与端口口径

- 服务端命令默认在 `server/.venv` 激活后执行，统一写 `python -m ...`；只有创建虚拟环境用 `python3 -m venv`。未激活 venv 的独立脚本块允许 `python3 -m ...`，但同一文档内不混写。
- 两种运行方式，端口不同：

| 方式 | 后端地址 | MySQL 宿主机端口 | 小程序 `DEV_BASE` |
|---|---|---|---|
| 本机直跑（`uvicorn`） | `127.0.0.1:8000` | 本机 MySQL `3306` | `http://127.0.0.1:8000` |
| Docker Compose | `127.0.0.1:8001` | `127.0.0.1:3307` | `http://127.0.0.1:8001` |

- 验证脚本统一称「`finish.sh` 8 项验证」，不写「8 项静态检查」（其中含单测与 Web 测试）。

---

## 1. 项目标识

| 项 | 值 | 说明 |
|---|---|---|
| 项目名称 | **报数机器人AI** | 小程序标题、登录页、开发者工具配置、应用卡、文档、API title 全部统一 |
| 小程序 AppID | `wx6359d33c631cec4d` | `project.config.json` |
| 架构 | 微信小程序 + FastAPI + MySQL 8 | 自有服务器，无云函数 / 无云开发 |
| 数据库名 | `jinribao` | 内部技术标识，沿用旧值以免牵动已配置的 `.env`；不对外展示 |
| logger / JWT issuer | `jinribao` / `jinribao-selfhosted` | 同上，属内部标识 |

**统一规则**：新增任何展示文案、标题、文档时一律使用「报数机器人AI」；内部标识（DB 名、logger、issuer、Storage key）保持稳定，不随展示名改动。

---

## 2. 架构与数据流

```
页面（pages/*）  ──调用──▶  utils/store.js  ──callApi──▶  utils/http.js
                                  │                            │
                           action + payload            wx.request POST
                                                      Authorization: Bearer
                                                            │
                                                            ▼
                                              server/app/main.py  /api
                                                            │
                                         auth.extract_uid(验签) → uid(openid)
                                                            │
                                         handlers.dispatch → HANDLERS[action]
                                                            │
                                         require_member / require_manager
                                                            │
                                                            ▼
                                     MySQL 8（server/app/db.py → PyMySQL）
```

关键抽象：`store.js` 把业务收敛为 `callApi(action, payload) -> data | throw`。**只要这个契约不变，页面层无需感知后端实现**。

登录链路另走 `/auth/login`（无需 token）：

```
wx.login → code → POST /auth/login → 服务端 jscode2session(AppID+AppSecret)
        → openid → 签发 JWT → 本地存 token → 之后所有 /api 带 Bearer
```

---

## 3. 目录结构

### 小程序（项目根）

| 路径 | 职责 | 改动约束 |
|---|---|---|
| `app.js` / `app.json` / `app.wxss` | 全局入口、页面注册、全局导航标题、主题变量 | 新增页面须注册 `app.json` |
| `pages/` | 13 个页面：index / records / profile / team + login-confirm + admin 下 8 页（含 tasks） | 只做 UI 与交互 |
| `components/dynamic-form/` | 动态表单组件（按模板 fields 渲染） | 字段契约见 §6 |
| `utils/store.js` | 52 个业务 action + `getActiveTemplate` / `getEffectiveTemplates` / `inScope` + `listTeamEntries` 自动翻页 | **对外签名冻结** |
| `utils/http.js` | `wx.request`、Bearer、401 拦截、token 存储（含内存兜底） | 传输层唯一入口 |
| `utils/session.js` | 登录、上下文 `loadContext()`、团队/空间切换、退出、401 钩子 | 本地只存 token、openid 与当前 team_id |
| `utils/config.js` | `RELEASE_BASE` / `DEV_BASE` / 超时 | 上线前必改 |
| `utils/date.js` / `stats.js` / `validator.js` | 日期（含 `BACKFILL_DAYS` 补录窗口）、统计聚合、表单校验（纯前端） | 无网络调用；改 `BACKFILL_DAYS` 必须同步服务端 |
| `project.config.json` | 开发者工具配置、`packOptions.ignore` 打包排除 | 后端/文档目录必须排除 |

### 服务端（`server/`）

| 路径 | 职责 |
|---|---|
| `app/main.py` | FastAPI：`/auth/login`、`/auth/web/*`、`/api`、`/api/export/entries`、`/health` |
| `app/auth.py` | `code2session`、小程序/Web 双 aud JWT 签发/验签、`extract_claims` |
| `app/config.py` | 环境变量集中读取 + 启动时密钥校验 |
| `app/db.py` | 连接、24 位 hex 主键、JSON 列序列化、标识符白名单 |
| `app/handlers/` | `common.py` + 10 个业务模块 + `registry.py`（52 个 action 元数据与派生白名单）+ `__init__.py` 门面（52 个 action + `WEB_ACTIONS` 白名单） |
| `app/services/expected.py` | 应提交口径唯一实现（任务优先，无任务回退模板范围） |
| `app/services/org.py` | 组织与权限唯一实现（空间/部门/有效角色/读写判定） |
| `app/services/wechat.py` | access_token 内存缓存 + 无限制小程序码（P5）+ 订阅消息发送（P6） |
| `app/services/notify.py` | 四类通知、订阅设置、`INSERT IGNORE` 去重与投递状态（P6） |
| `app/services/scheduler.py` | 调度作业定义与 `parse_hm` / `with_conn` 公共工具（P6）；应用内启动入口 |
| `app/scheduler_worker.py` | 独立调度进程入口 `python -m app.scheduler_worker`，阻塞式调度 + 优雅停止（P6） |
| `app/services/export.py` | 团队日报 Excel 导出（openpyxl write_only，上限 5 万行） |
| `app/init_db.py` | 按 `sql/schema.sql` 幂等建表 |
| `sql/schema.sql` | 18 张表 DDL + 唯一索引；增量迁移见 `sql/migrate_p2_report_tasks.sql`、`migrate_p3_analysis.sql`、`migrate_p4_workspaces.sql`、`migrate_p5_web_tickets.sql`、`migrate_p6_notifications.sql`、`migrate_p6_heartbeat.sql`、`migrate_p7_notify_scope.sql`、`migrate_p8_analysis_workspace.sql` |
| `tests/test_contract.py` / `test_baseline.py` / `test_org.py` / `test_web_auth.py` / `test_web_actions.py` / `test_notify.py` | action 对账、基线回归、P4 隔离、P5 扫码登录与导出、P6 通知去重与监控 |
| `web/` | Vue 3 管理后台（Vite + TS + Element Plus + Pinia），与 API 同域部署 |
| `.env.example` | 环境变量模板（**真实 `.env` 不入库**） |

---

## 4. 接口契约

### 4.1 端点

| 端点 | 方法 | 鉴权 | 请求 | 响应 |
|---|---|---|---|---|
| `/auth/login` | POST | 无 | `{"code": "<wx.login code>"}` | `{"ok":true,"data":{"token","openid"}}`（团队上下文由 `getMyMember`/`getTeam` 取，登录端点不返回 `hasTeam`） |
| `/auth/web/ticket` | POST | 无 | — | `{"ok":true,"data":{"ticket","qrcode","expiresIn":300}}`；失败时 `ok:false` + 安全文案 |
| `/auth/web/ticket/status` | POST | 无 | `{"ticket":"32位hex"}` | `{"ok":true,"data":{"status":"pending/confirmed/consumed/expired"}}`；确认后一次性返回 `token`（aud=web）与 `workspaces` |
| `/auth/web/refresh` | POST | Bearer `aud=web` | — | `{"ok":true,"data":{"token","expiresIn"}}` |
| `/api` | POST | `Authorization: Bearer <JWT>` | `{"action":"...", ...payload}` | `{"ok":true,"data":...}` 或 `{"ok":false,"message":"..."}` |
| `/api/export/entries` | POST | Bearer（小程序或 Web） | `{"teamId","startDate","endDate","templateId?"}` | xlsx 二进制流（`Content-Disposition: attachment`） |
| `/health` | GET | 无 | — | `{"ok":true,"service":"jinribao","version":"2.0.0"}` |

**错误语义**：`401` = 登录过期（前端 `http.js` / `web/src/api/client.ts` 清 token 并回登录态）；业务错误用 HTTP 200 + `ok:false` + `message`；Web 令牌调用非白名单 action 返回「Web 端无权调用该操作」；服务异常用 HTTP 500 + 通用文案，不回传堆栈。

### 4.2 52 个业务 action

action 元数据集中在 `app/handlers/registry.py`：每个 action 声明所属模块、Web 端是否可用、是否写操作与用途摘要；`HANDLERS`、`WEB_ACTIONS`、`MINI_ONLY_ACTIONS` 均由元数据派生，导入时校验两向一一对应（已注册未声明、已声明未实现都会启动即报错）。下表与元数据表必须同步。

权限列说明：**登录** = 只需有效 JWT；**成员** = `require_member`（含空间管理员/部门负责人）；**写成员** = `require_writer`（拒绝 viewer）；**管理员** = `require_manager`；**空间管理员** = 空间 owner/admin；**本人** = 按 JWT 身份过滤本人数据。

| 分组 | action | 前端函数 | 说明 | 权限 |
|---|---|---|---|---|
| 团队 | `createTeam` | `store.createTeam(name, memberName, workspaceId?, departmentId?)` | 创建团队并成为 owner；不传空间则自动建独立空间，一人可多团队 | 登录 |
| 团队 | `findTeam` | `store.findTeamByCode(code)` | 按邀请码查团队 | 登录 |
| 团队 | `joinTeam` | `store.joinTeam(teamId, memberName)` | 加入团队，自动补空间成员；退出后重加入复用原行 | 登录 |
| 团队 | `getTeam` | `store.getTeam(teamId)` | 团队详情 | 成员 |
| 团队 | `updateTeamConfig` | `store.updateTeamConfig(teamId, config)` | 团队配置 / 调整所属部门 | 管理员 / 空间管理员 |
| 成员 | `getMyMember` | `store.getMyMember(teamId?)` | 我的成员资料（可指定团队）；附加 workspace 与 effective_role | 登录 |
| 成员 | `listMembers` | `store.listMembers(teamId)` | 成员列表（过滤已退出） | 管理员 / 空间管理员 |
| 成员 | `updateMember` | `store.updateMember(id, patch)` | 改姓名/角色/状态/部门；空间管理员不得改团队 owner | 管理员 / 空间管理员 |
| 成员 | `removeMember` | `store.removeMember(id)` | 软移除（`status=disabled` + `left_at`） | 管理员 / 空间管理员 |
| 模板 | `listTemplates` | `store.listTemplates(teamId)` | 全部模板（含草稿） | 成员 |
| 模板 | `getTemplate` | `store.getTemplate(id)` | 模板详情；**草稿/归档仅管理员**，已发布对成员开放 | 成员 / 管理员 |
| 模板 | `listPublishedTemplates` | `store.listPublishedTemplates(teamId)` | 已发布模板 | 成员 |
| 模板 | `createDraft` | `store.createDraft(payload)` | 新建草稿（**服务端强制 `status=draft`**） | 管理员 |
| 模板 | `updateTemplateRow` | `store.updateTemplateRow(id, patch)` | 编辑 / 停用为 archived | 管理员 |
| 模板 | `deleteTemplateRow` | `store.deleteTemplateRow(id)` | 删除草稿 | 管理员 |
| 模板 | `nextVersion` | `store.nextVersion(teamId, templateId)` | 取下一版本号 | 管理员 |
| 模板 | `publishTemplate` | `store.publishTemplate(id)` | 发布：团队行加锁 + 冲突时顺延版本号 + 归档旧版 + 冻结快照 + 写审计；保留草稿设定的 `effective_from` | 管理员 |
| 录入 | `getMyEntry` | `store.getMyEntry(teamId, date)` | 指定日期录入（含补录） | 本人 |
| 录入 | `saveEntry` | `store.saveEntry(payload)` | 幂等 upsert（唯一键见 §6）；`entry_date` 服务端校验 31 天补录窗口 | 成员 |
| 录入 | `listMyEntries` | `store.listMyEntries(teamId, limit)` | 我的历史录入 | 本人 |
| 录入 | `listTeamEntries` | `store.listTeamEntries(teamId, from, to)` | 团队区间录入；服务端 `page`/`pageSize` 分页，`store.js` 自动翻页拉全 | 管理员 |
| 任务 | `createReportTask` | `store.createReportTask(payload)` | 基于已发布模板创建任务，快照 scope/version | 管理员 |
| 任务 | `listReportTasks` | `store.listReportTasks(teamId, status)` | 任务列表（可按 active/closed 过滤） | 管理员 |
| 任务 | `getReportTask` | `store.getReportTask(id)` | 任务详情 | 管理员 |
| 任务 | `getReportTaskStatus` | `store.getReportTaskStatus({teamId, taskId?, date?, from?, to?})` | 应提交口径 + 任务状态机 + 未提交名单；单日/区间通用 | 管理员 |
| 任务 | `closeReportTask` | `store.closeReportTask(id)` | 关闭任务（幂等） | 管理员 |
| 分析 | `listAnalysisMetrics` | `store.listAnalysisMetrics(teamId)` | 指标注册表（6 个）| 管理员 |
| 分析 | `listAnalysisRules` | `store.listAnalysisRules(teamId)` | 规则定义（3 条，含阈值）| 管理员 |
| 分析 | `runAnalysis` | `store.runAnalysis({teamId, from, to})` | 幂等执行：指标 + 规则 + 报告落库 | 管理员 |
| 分析 | `retryAnalysisTask` | `store.retryAnalysisTask(id)` | 失败/中断任务原任务重试，不产生新报告 | 管理员 |
| 分析 | `listAnalysisTasks` | `store.listAnalysisTasks(teamId, limit)` | 分析任务列表 | 管理员 |
| 分析 | `getAnalysisTask` | `store.getAnalysisTask(id)` | 任务 + 结果 + 发现明细 | 管理员 |
| 分析 | `listAnalysisFindings` | `store.listAnalysisFindings(taskId)` | 指定任务的规则发现 | 管理员 |
| 分析 | `getAnalysisOverview` | `store.getAnalysisOverview(teamId)` | 最近结果 + 任务 + 注册表（分析页首屏）| 管理员 |
| 审计 | `log` | `store.logAction(teamId, action, ...)` | 上报审计，失败不阻断主流程 | 成员 |
| 空间 | `listMyWorkspaces` | `store.listMyWorkspaces()` | 我的空间 + 各自可见团队 | 登录 |
| 空间 | `switchWorkspace` | `store.switchWorkspace({teamId?, workspaceId?})` | 切换上下文：返回 workspace/Role/team/member/teams/departments | 登录 |
| 空间 | `createWorkspace` | `store.createWorkspace(name, memberName, teamName?)` | 建空间并成为 owner，可同时建首个团队 | 登录 |
| 空间 | `updateWorkspace` | `store.updateWorkspace(workspaceId, patch)` | 改名称 / config | 空间管理员 |
| 空间 | `listWorkspaceMembers` | `store.listWorkspaceMembers(workspaceId)` | 空间成员列表（含部门） | 空间管理员 |
| 空间 | `updateWorkspaceMember` | `store.updateWorkspaceMember(workspaceId, id, patch)` | 改空间角色 / 部门 / 状态 | 空间管理员 |
| 部门 | `listDepartments` | `store.listDepartments(workspaceId)` | 部门树（≤3 级） | 成员 |
| 部门 | `createDepartment` | `store.createDepartment(workspaceId, name, parentId?, leaderUid?)` | 新建部门 | 空间管理员 |
| 部门 | `updateDepartment` | `store.updateDepartment(workspaceId, id, patch)` | 改名 / 换上级 / 负责人 / 停用；移动校验深度与环路 | 空间管理员 |
| Web | `confirmWebLogin` | `store.confirmWebLogin(ticket)` | 小程序确认扫码登录；空间 owner/admin 或团队 owner/manager，票据一次性 | 小程序 token + 管理权限 |
| Web | `getWorkspaceOverview` | `callApi('getWorkspaceOverview', {workspaceId})` | 工作台汇总：今日应提交/已提交/提交率、未提交、活跃任务、7 天趋势、近 7 天异常 | 团队 owner/manager 或空间 owner/admin |
| Web | `listAuditLogs` | `callApi('listAuditLogs', {...})` | 审计分页；`workspace_id` 强制过滤，`LIMIT/OFFSET` 参数化 | 团队 owner/manager 或空间 owner/admin |
| 通知 | `getSubscribeTemplates` | `store.getSubscribeTemplates()` | 返回服务端已配置的模板 ID，小程序订阅授权唯一来源 | 登录 |
| 通知 | `getNotificationSettings` | `store.getNotificationSettings(teamId?)` | 本人在当前空间的四类订阅开关与模板配置状态 | 登录 / 本人 |
| 通知 | `saveNotificationSettings` | `store.saveNotificationSettings(teamId, settings)` | 记录小程序授权结果；服务端只写本人，不接收客户端 user_id | 登录 / 本人 |
| 通知 | `listNotificationLogs` | `callApi('listNotificationLogs', {...})` | 通知投递分页（sent/skipped/failed 与原因） | 空间 owner/admin |
| 监控 | `getRuntimeMonitor` | `callApi('getRuntimeMonitor', {workspaceId, windowDays})` | 近 N 天分析成功率/平均耗时、通知汇总、调度器状态 | 空间 owner/admin |

> **纯前端判定**（不产生独立网络请求，不在 `HANDLERS` 注册表中）：
> `getEffectiveTemplates()` 取全部已生效的 published 模板（按生效日 → 版本降序）；
> `getActiveTemplate()` 从中取第一个命中成员 `inScope` 的（成员端一天一条记录）；
> 管理端「应提交名单」不再由客户端计算，统一调用服务端 `getReportTaskStatus`。
> `listTeamEntries` 虽是一个 action，但 `store.js` 会按 1000 条/页循环调用直到拉全（上限 50 页，超限抛错）。
> 已删除的 `listEntriesByUser` 前端零调用，后端亦未迁移；新增 action 必须前后端成对注册并更新 `tests/test_contract.py` 的期望集合。
> **有效角色优先级**（`services/org.py` 单点实现）：团队 owner/manager > 空间 owner/admin > 部门负责人（按 `manager` 计）> 团队/空间 member/viewer。`require_writer` 拒绝 viewer；空间管理员即使不是团队成员也可读写其空间内团队，但**不能修改/移除团队 owner**。
> **跨空间隔离**：请求携带的 `teamId` 必须属于当前用户可访问的空间；列表查询在 `team_id` 外追加 `workspace_id`，写入的 `workspace_id` 由服务端按团队反查。

---

## 5. 登录与鉴权

| 环节 | 实现 | 位置 |
|---|---|---|
| 取 code | `wx.login` | `utils/session.js` `login()` |
| 换 openid | 服务端 `jscode2session` GET 微信接口 | `server/app/auth.py` `code2session()` |
| 签发 | HS256 JWT，`sub=openid`、`iss`、`iat`、`exp`（默认 30 天） | `auth.issue_token()` |
| 本地存储 | `auth_token` / `auth_openid`（Storage 失败时内存兜底） | `utils/http.js` / `session.js` |
| 每次请求 | `Authorization: Bearer <token>` | `utils/http.js` `request()` |
| 验签注入 | 小程序 `extract_uid()` / Web `extract_claims()` → `dispatch(conn, uid, event)` | `server/app/main.py` |
| 过期处理 | 401 → 清 token → `signOut()` → 页面回登录态 | `http.js` + `session.js` + `web/src/api/client.ts` |

**AppSecret 与 `JWT_SECRET` 只允许出现在服务端环境变量，绝不进小程序包。**

### Web 扫码登录（P5）

1. Web 调 `/auth/web/ticket`，服务端生成 32 位 hex 一次性 ticket（5 分钟）并调用 `wxa/getwxacodeunlimit` 返回 PNG data URL。
2. 小程序扫码进入 `pages/login-confirm/login-confirm`，展示「网页端请求登录」；用户点「确认登录」调用 `confirmWebLogin`。
3. 服务端校验空间 owner/admin 或团队 owner/manager 权限，把 ticket 置为 `confirmed` 并记录可管理的空间快照。
4. Web 每 1.5 秒轮询 `/auth/web/ticket/status`；看到 `confirmed` 时在同一事务内把 ticket 置为 `consumed` 并签发 `aud=web` 令牌（默认 12 小时）。
5. 之后每个 `/api` 请求仍按数据库实时校验团队 owner/manager 或空间 owner/admin，**不信任令牌内嵌的空间列表**。

- 小程序令牌 `aud=mini`（30 天）与 Web 令牌 `aud=web`（12 小时）互不通用；P5 之前签发、没有 `aud` 的旧令牌按 `mini` 处理。
- Web 令牌只能调用 `server/app/handlers/__init__.py` 的 `WEB_ACTIONS` 白名单；`saveEntry` / `getMyEntry` / `listMyEntries` / `log` / `confirmWebLogin` 一律拒绝。
- CORS 只放行 `WEB_ORIGIN`（默认 `https://api.modouyu.top`）与本地 `5173`，不使用 `*`。

### 消息通知与调度（P6）

- **四类通知**：`daily_remind`（每日填报）、`due_remind`（截止前 N 分钟）、`missing_remind`（当日未提交）、`anomaly_alert`（分析 warning/critical）。
- **模板 ID 可配置**：`WX_TMPL_*` 环境变量为空时只写 `notification_logs`（`status=skipped`），不调用微信；配置后自动生效，无需改代码。
- **订阅授权**：小程序在「提交」点击的同步链路里调用 `wx.requestSubscribeMessage`（异步请求之后再调用会被微信判定为非法触发），只对已配置模板的类型弹窗；微信单次最多 3 个模板，超过不做拆分会导致整次失败，因此按优先级分批、每次点击只弹一组并按团队轮换（`notify_batch_<teamId>` 记录游标），连续提交即可覆盖全部类型；拒绝、取消或低版本基础库均不阻断提交。授权结果写入 `notification_settings`。
- **去重**：`notification_logs` 唯一键 `uk_notify_dedupe(user_id, notify_type, scope_key, period_key)`，`INSERT IGNORE` 抢键；`scope_key` 取团队 id（无团队时取空间 id），同一用户在不同团队各发各的，不会互相吞通知；手工重跑或迁移期双跑时同一用户同一团队同一周期仍只发送一次。
- **调度**：由独立 `scheduler` 容器执行（`python -m app.scheduler_worker`，`SCHEDULER_ENABLED=1`），Web 进程固定 `SCHEDULER_ENABLED=0`，避免 gunicorn 多 worker 重复触发。每日提醒与未提交提醒用 cron，截止提醒每 5 分钟扫描（`due_time - REMIND_BEFORE_MINUTES` 至 `due_time` 之间）。启停：`docker compose up -d scheduler` / `docker compose stop scheduler`，日志 `docker compose logs -f scheduler`。
- **异常预警**：分析成功后扫描 findings，仅 warning/critical 触发，发给团队 owner/manager 与空间 owner/admin；通知失败只记日志，不影响分析结果。
- **心跳**：调度进程每 60s 刷新 `scheduler_heartbeats`（每作业一行，含 `next_run_at` 与执行结果）；Web 端 `getRuntimeMonitor` 在进程内调度未启动时读该表，`updated_at` 超过 180s 未刷新即判定「心跳超时」。心跳表为空时显示「已关闭」。
- **运行监控**：`getRuntimeMonitor` 统计近 N 天分析成功率/平均耗时、通知 sent/skipped/failed 与调度器下次执行时间，Web 工作台内嵌展示。

---

## 6. 数据模型

`server/sql/schema.sql`，MySQL 8 / utf8mb4。主键均为 24 位 hex 字符串 `id`（等价旧云库 `_id`），前端无需 `normalize`。

| 表 | 关键字段 | 约束 / 索引 |
|---|---|---|
| `workspaces` | `workspace_code`（`W`+团队码 / `W`+随机）、`name`、`owner_uid`、`config` JSON | `uk_workspaces_code` 唯一 |
| `departments` | `workspace_id`、`name`、`parent_id`、`parent_key`(生成列)、`depth`、`leader_uid`、`status` | `uk_dept_ws_parent_name(workspace_id,parent_key,name)` 唯一；`idx_dept_ws_parent`；`depth ≤ 3` |
| `workspace_members` | `workspace_id`、`user_id`、`name`、`role`(owner/admin/member/viewer)、`department_id`、`status`、`joined_at` | `uk_ws_member(workspace_id,user_id)` 唯一；`idx_ws_member_user` |
| `teams` | `team_id`(邀请码)、`workspace_id`、`department_id`、`name`、`owner_uid`、`config` JSON | `uk_teams_team_id` 唯一；`idx_teams_workspace` |
| `members` | `team_id`、`user_id`(openid)、`name`、`role`(owner/manager/member/viewer)、`department_id`、`status`、`left_at` | `uk_members_team_user(team_id,user_id)` 唯一 |
| `form_templates` | `team_id`、`workspace_id`、`template_id`、`version`、`fields` JSON、`scope` JSON、`effective_from`、`status`(draft/published/archived) | `uk_tpl_team_id_ver(team_id,template_id,version)` 唯一；`idx_tpl_workspace` |
| `daily_entries` | `team_id`、`workspace_id`、`user_id`、`entry_date`、`form_data` JSON、`status`(draft/submitted)、`template_version` | `uk_entry_team_user_date` 唯一（**saveEntry 幂等**）；`idx_entry_workspace_date` |
| `report_tasks` | `team_id`、`workspace_id`、`task_key`、`title`、`template_id`/`template_version`、`scope` JSON、`start_date`/`end_date`、`due_time`、`workdays_only`、`status`(active/closed) | `uk_task_team_key(team_id,task_key)` 唯一；`idx_task_workspace_status` |
| `analysis_metrics` | `metric_code`、`version`、`name`、`formula`、`description`、`status` | `uk_metric_code_ver(metric_code,version)` 唯一 |
| `analysis_rules` | `rule_code`、`version`、`level`、`condition_text`、`params` JSON（阈值）| `uk_rule_code_ver(rule_code,version)` 唯一 |
| `analysis_tasks` | `team_id`、`workspace_id`（服务端写入，P8）、`analysis_type`、`period_start`/`period_end`、`scope` JSON、`status`(running/success/failed)、`metric_version`、`rule_version`、`retry_count` | `uk_analysis_idem(team_id,analysis_type,period_start,period_end,rule_version)` 唯一（**幂等键**）；`idx_analysis_ws_time(workspace_id,created_at)` |
| `analysis_results` | `task_id`、`data_snapshot_time`、`metric_version`、`rule_version`、`execution_id`、`summary` JSON、`data_quality` JSON、`report_text` | `uk_result_task(task_id)` 唯一 |
| `analysis_findings` | `task_id`、`result_id`、`rule_code`、`level`、`finding_code`、`detail` JSON、`data_refs` JSON | `uk_finding_task_code(task_id,finding_code)` 唯一 |
| `audit_logs` | `workspace_id`、`team_id`(可空)、`actor`、`action`、`target_type`、`target_id`、`detail` JSON | `idx_audit_workspace_time` |
| `web_login_tickets` | `ticket`(32 位 hex)、`user_id`、`status`(pending/confirmed/consumed/expired)、`workspace_ids` JSON、`client_ip`、`created_at`/`expires_at`/`confirmed_at`/`consumed_at` | `uk_web_ticket(ticket)` 唯一；`idx_web_ticket_status(status,expires_at)` |
| `notification_settings` | `workspace_id`、`user_id`、`notify_type`、`enabled`、`updated_at` | `uk_notification_setting(workspace_id,user_id,notify_type)` 唯一 |
| `notification_logs` | `workspace_id`、`team_id`、`scope_key`（团队 id 优先，其次空间 id）、`user_id`、`notify_type`、`period_key`、`template_id`、`status`(pending/sent/skipped/failed)、`error_message`、`payload` JSON、`created_at`/`sent_at` | `uk_notify_dedupe(user_id,notify_type,scope_key,period_key)` 唯一；`idx_notify_ws_time(workspace_id,created_at)` |
| `scheduler_heartbeats` | `job_id`、`job_name`、`next_run_at`、`last_run_at`、`last_status`(ok/failed)、`last_error`、`updated_at` | `uk_scheduler_job(job_id)` 唯一；`idx_scheduler_updated(updated_at)`；`updated_at` 超过 180s 未刷新视为调度未运行 |

**字段/时间契约（回归关键）**

- 时间统一 ISO8601 UTC 字符串（`2026-11-09T09:08:02.000Z`），与旧云函数 `new Date().toISOString()` 一致，保障 `records.js` 的「补录」判定。
- `entry_date` / `effective_from` 为 `YYYY-MM-DD` 字符串，字典序即区间序。
- JSON 列（`config` / `fields` / `scope` / `form_data` / `detail` / `workspace_ids`）由 `db.py` 自动序列化，读取时自动反序列化；新增 JSON 列必须同步 `db.JSON_COLUMNS`。
- 字段新增 `statType`(none/sum/count/avg)、`unit`、`analysisCategory`；`aggregate` 由 `statType` 派生，二者不得出现不一致。
- 写入字段走白名单：客户端不能改写 `id`、`team_id`、`template_id`、`version`、`user_id`、`created_by` 等归属字段。

**填报任务与应提交口径（P2）**

- 模板回答「填什么」；任务回答「谁、哪天、什么时候前填」。
- 当日有覆盖该日期的 `active` 任务时：应提交 = 任务 `scope` 并集；`workdays_only=1` 的任务在周末不产生应提交人（不回退模板口径）。
- 当日没有任务时：回退到「所有已生效模板 `scope` 并集」；两种情况都只统计 `status='active'` 成员。
- 成员状态：`pending` 待提交 / `submitted` 已提交 / `late` 已逾期 / `backfilled` 已补录 / `closed` 已关闭；补录按提交时间换算东八区日期后与 `entry_date` 比较。
- 唯一实现：`server/app/services/expected.py` 的 `compute_expected_submitters`，handler 与小程序端不得另写一套统计口径。

**确定性分析引擎（P3）**

指标只允许在 `server/app/services/metrics.py` 实现一份，看板/报表/分析/导出后续必须复用：

| code | 名称 | 口径 | 空值行为 |
|---|---|---|---|
| `SUBMIT_RATE` | 提交率 | 应提交范围内已提交人次 / 应提交人次 | 分母为 0 → `null`，展示「数据不足」 |
| `SUBMIT_COUNT` | 已提交人数 | 每日应提交范围内 `status='submitted'` 去重人数，周期内累加为人次 | 无记录 → 0 |
| `EXPECTED_COUNT` | 应提交人数 | 每日 `expected_for_day` 结果累加成人次 | 无模板/任务 → 0 |
| `FIELD_SUM` | 数值字段合计 | 模板 `statType='sum'` 求和；`count` 字段输出计数 | 无有效样本 → `null`，不补零 |
| `FIELD_AVG` | 数值字段均值 | 字段求和 / 有效样本数 | 样本 0 → `null` |
| `PERIOD_GROWTH` | 周期增长率 | (本期 - 上期等长周期) / 上期 | 上期为 0/缺失 → `null`；周期未结束 → `incomplete` |

规则同样只有一份（`server/app/services/rules.py`），阈值存 `analysis_rules.params`：

| code | 级别 | 条件 |
|---|---|---|
| `SUBMISSION_RATE_LOW_01` | warning | 当日提交率 < 阈值（默认 0.8），分母为 0 的日期不触发 |
| `METRIC_DROP_01` | warning | 本期指标 < 上期 × 阈值（默认 0.8），上期为 0/缺失不判断 |
| `MISSING_DATA_01` | info | 周期内应提交但无记录，按成员聚合缺失日期（草稿不算提交） |

执行与追溯：
- 幂等键 `uk_analysis_idem(team_id, analysis_type, period_start, period_end, rule_version)`；重复触发返回既有结果，不产生第二条任务/报告。
- 结果固定记录 `data_snapshot_time`、`metric_version`、`rule_version`、`execution_id`，可从任务回放到具体指标与规则版本。
- 执行器写操作白名单仅 `analysis_*`；`services/dataset.py` 只有 SELECT，禁止引用 `db.insert/update/remove/execute`。
- 报告为确定性拼接，不含模型推断；无数据时明确输出「数据不足，暂不生成结论」，不补零。

样例报告（格式示例，非线上数据）：

```text
【分析报告】销售一队 · 2026-11-10 至 2026-11-16
数据快照：2026-11-16T10:00:00.000Z · 指标版本 v1 · 规则版本 v1 · 执行号：<24位hex>

一、提交情况
应提交 105 人次，已提交 90 人次，提交率 85.7%。

二、字段指标
- 到访（次）：1234（有效样本 90）

三、趋势
- 提交率：本期 0.86，上期 0.92，增长率 -6.5%

四、异常与提醒
- [预警] 2026-11-12 提交率 66.7%，低于阈值 80%
- [提示] 张三 有 3 天应提交但无记录

五、数据质量
- 应提交但无提交记录 15 人次

本报告由确定性规则拼接生成，不含模型推断。
```

**组织与多工作空间（P4）**

- 层级：`workspaces` → `teams`（可挂 `departments`）→ `members`；`workspace_members` 记录空间级角色，一人可同时属于多个空间。
- 存量迁移：每个团队生成独立空间 `workspace_code='W'+team_id`、名称「团队名 工作空间」；`workspace_members` 由 `members` 去重生成（角色取最高），表单/录入/任务/审计按 `teams.workspace_id` 回填。
- 部门唯一键用生成列 `parent_key = IFNULL(parent_id,'')`，使「同空间同上级同名称」唯一；`depth` 由服务端维护，最大 3 级，移动时递归更新后代。
- 成员退出为软移除：`status='disabled'` + `left_at`；`joinTeam` 遇到 `left_at` 非空的原行会重新激活，不新增行。
- 有效角色与读写判定只在 `server/app/services/org.py` 实现；handler 只接收 `common.team_access()` 组装的访问上下文，禁止自行拼角色。
- 回滚脚本 `sql/migrate_p4_rollback.sql` 有损，仅回滚结构；执行前必须备份并先把应用回退到 P3。

---

## 7. 前端分层约定

1. 页面只调用 `store.js` 与 `session.js`，**禁止直接 `wx.request` / 直接拼 URL**。
2. `store.js` 每个函数只做 `callApi(action, payload)`；跨请求组合逻辑（如 `getActiveTemplate`）也放在这一层。
3. 身份相关：页面可用 `ctx.uid` 做展示，但**不得把 uid 当作权限依据**；权限判定用 `session.isManager(member)`（内部看 `effective_role`），最终以服务端校验为准。
4. `loadContext()` 有缓存（`globalData.loaded`）；创建/加入团队后调用 `session.switchTeam(teamId)`，切换空间用 `session.switchSpace(workspaceId)`，二者会刷新缓存并写入本地 `active_team_id`。
5. 登录竞态：多个页面 `onShow` 可能并发调用 `loadContext()`，不要在页面里自行触发重复登录。
6. **补录链路**：首页 `entryDate` 默认今天，左右箭头 / `<picker mode="date">` 可切到近 31 天；`records` 页的「补录昨日」或点击记录日期，通过 Storage key `backfill_date` 把目标日期传给首页 `onShow`（index 是 tabBar 页，不能 URL 传参）。首页每次 `onShow` 默认回今天，只有读到合法 `backfill_date` 才切日期。补录沿用**当前生效模板**（旧版本发布时已归档），`source` 标记为 `backfill`。

---

## 8. 服务端分层约定

1. `main.py` 只做路由、验签、响应包装；业务逻辑一律在 `handlers/`。
2. 每个 handler 签名 `(conn, uid, payload)`；`uid` 来自 JWT，**不得从 payload 读取身份**。
3. 写操作先 `require_member` / `require_manager`，再校参数，最后落库；涉及团队归属必须先校验。
4. SQL 全部参数化；动态表名/列名经 `db._check_ident()` 白名单校验。
5. 抛 `BusinessError("用户可读文案")` 表示业务失败；其他异常由 `main.py` 统一记日志并返回通用错误。
6. 新增 action：在对应模块实现并加入 `HANDLERS` → 在 `app/handlers/registry.py` 的 `_ROWS` 增加一行元数据（模块 / Web 可用 / 是否写操作 / 摘要）→ `store.js` 加包装函数 → 更新单测期望集合。
7. 组织与权限：涉及团队归属的 handler 必须走 `common.require_member/require_manager/require_writer` 或 `common.team_access()`，**不得直接读 `members.role` 判权**；跨空间列表必须显式追加 `workspace_id`；写入的 `workspace_id` 由服务端按团队反查，忽略客户端传值。

---

## 9. 安全约定与回归风险

| # | 风险 | 约束 / 检查方式 |
|---|---|---|
| R1 | **身份伪造（高危）** | 身份只取 JWT `sub`；客户端 `uid` / `openid` / `user_id` 一律忽略；`saveEntry` 强制覆盖 `user_id` |
| R2 | 真机联调硬约束 | `request` 合法域名必须 HTTPS + ICP 备案；IP/localhost 真机不可用；AppSecret 只在服务端 |
| R3 | 字段契约 | 保留 24 位 hex `id`，否则页面 `.id` 全断 |
| R4 | 时区 | 服务端 UTC ISO 字符串，前端 `today()` 本地日期，格式不可变 |
| R5 | 幂等 | `daily_entries(team_id,user_id,entry_date)` 唯一索引必须存在 |
| R6 | 登录竞态 | 登录态以 token 为准；401 由 `session.js` 统一清理并 `switchTab` 回登录页；页面不重复触发登录 |
| R7 | **多工作空间** | 一人可属多空间；当前团队以本地 `active_team_id` 为提示，切换必须经服务端 `switchWorkspace` 校验归属；`find_member_by_uid` 按 `joined_at ASC, id ASC` 取确定性结果 |
| R8 | 服务端提交复核 | `saveEntry` 校验模板归属，并对 `submitted` 按模板 fields 复核必填/类型/范围/选项；前端模板新鲜度校验失败时提交必须阻断（草稿可离线暂存） |
| R9 | 停用成员 | `getMyMember` 对 `status != active` 直接报「已被停用」，前端保留登录态以显示退出入口 |
| R10 | **补录窗口** | 前端 `date.js BACKFILL_DAYS=31` 与服务端 `entries.py BACKFILL_DAYS=31` 必须一致；服务端 UTC、前端本地时区，服务端上下各放宽 1 天避免凌晨误拒。两处任一改动都要同步 |
| R11 | 大数据静默截断 | `list_team_entries` 分页 SQL 的 `ORDER BY entry_date DESC, id DESC` 必须保留（同日多条翻页不重不漏）；前端 50 页上限触发时抛业务错误，不得降级为部分数据 |
| R12 | 应提交口径 | 管理端 `dashboard` / `reports` 必须调用服务端 `getReportTaskStatus`；口径实现只在 `app/services/expected.py`：有任务按任务 scope 并集，无任务回退全部已生效模板范围并集 |
| R13 | 并发发布与预览 | `publishTemplate` 先 `SELECT ... FOR UPDATE` 锁团队行，再按冲突顺延 `version`（`uk_tpl_team_id_ver` 不再撞键）；草稿/归档 `getTemplate` 只放行管理员 |
| R14 | **跨空间越权（高危）** | 所有读写先 `team_access`：团队成员、空间 owner/admin、部门负责人之一才可读；写额外拒绝 viewer；空间管理员不得修改/移除团队 owner；列表在 `team_id` 外追加 `workspace_id` |
| R15 | **部门层级** | `depth ≤ 3`；移动部门先判环路（新上级不在本部门子树内）再判深度；唯一键 `(workspace_id,parent_key,name)`，`parent_key` 为生成列 |

另：模板状态只能经 `publishTemplate` 变成 `published`；`createDraft` 强制 draft；`updateTemplateRow` 只允许把状态改为 `archived`（停用），且允许停用已发布模板。停用**不会**回退到上一版本（旧版本发布时已归档），管理端弹窗按实际剩余的已生效模板数量提示。审计 `log` 需校验团队归属，防止跨团队写入。

---

## 10. 本地开发流程

### 环境变量（`server/.env`，参考 `.env.example`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3306` | MySQL 地址 |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `jinribao` / 空 / `jinribao` | 库名沿用内部标识 |
| `WX_APPID` / `WX_SECRET` | 空 | 服务端专用，启动时强制校验非空 |
| `JWT_SECRET` | 空 | 随机长串，启动时强制校验非空且 **≥32 字符** |
| `JWT_TTL_DAYS` | `30` | 小程序 token 有效期 |
| `WEB_ORIGIN` | `https://api.modouyu.top` | Web 管理后台来源，CORS 白名单 |
| `WEB_TOKEN_TTL_HOURS` | `12` | Web token 有效期（`aud=web`） |
| `WX_HTTP_TIMEOUT` | `5` | 微信接口超时（秒） |
| `WX_TMPL_DAILY_REMIND` / `WX_TMPL_DUE_REMIND` / `WX_TMPL_MISSING_REMIND` / `WX_TMPL_ANOMALY_ALERT` | 空 | 四类订阅消息模板 ID，**唯一配置源**（小程序通过 `getSubscribeTemplates` 拉取）；留空只记录 skipped，不调微信 |
| `SCHEDULER_ENABLED` | `0` / `1` | 调度开关；compose 中 backend 固定 `0`、scheduler 容器固定 `1`，手工运行时按需设置 |
| `SCHEDULER_TZ` | `Asia/Shanghai` | 调度时区 |
| `DAILY_REMIND_TIME` / `MISSING_REMIND_TIME` | `09:00` / `20:00` | 每日填报 / 未提交提醒时间（HH:MM） |
| `REMIND_BEFORE_MINUTES` | `30` | 截止提醒提前量（分钟） |
| `PORT` | `8000` | 服务端口 |

### 步骤

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 填真实值
python -m app.init_db       # 幂等建库建表
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
python -m pytest -q         # 契约与鉴权单测（不依赖真实 MySQL）
```

前端：改 `utils/config.js` 的域名 → 微信开发者工具导入项目根 → 详情/本地设置勾选「不校验合法域名」（仅开发期）。

Web 后台（可选）：

```bash
cd web
npm ci
npm run dev                 # http://localhost:5173，/api 与 /auth 代理到 127.0.0.1:8001
npm run build               # 类型检查 + 产物 web/dist/
```

---

## 11. 上线清单

- [ ] `server/.env` 配齐 DB / `WX_APPID` / `WX_SECRET` / `JWT_SECRET` / `WEB_ORIGIN`，`.env` 不入库
- [ ] `python -m app.init_db` 成功，18 张表与唯一索引齐全（全新安装）
- [ ] 存量环境按顺序执行 `server/sql/migrate_p2_report_tasks.sql` → `migrate_p3_analysis.sql` → `migrate_p4_workspaces.sql` → `migrate_p5_web_tickets.sql` → `migrate_p6_notifications.sql` → `migrate_p6_heartbeat.sql` → `migrate_p7_notify_scope.sql` → `migrate_p8_analysis_workspace.sql`（均幂等，脚本末尾自检数字需符合 README 说明）
- [ ] P4 迁移后核对：`teams_without_workspace=0`、四张子表 `*_null_workspace=0`、`workspace_count=team_count`、`departments_depth_over_3=0`
- [ ] P5 迁移后核对 `web_login_tickets_exists=1`
- [ ] P6 迁移后核对 `notification_tables_exists=2`、`uk_notify_dedupe_exists=3`、`uk_notification_setting_exists=3`
- [ ] P7 迁移后核对 `scope_key_column_exists=1`、`uk_notify_dedupe_has_scope=1`、`backfill_pending_rows=0`
- [ ] P8 迁移后核对 `analysis_workspace_column_exists=1`、`idx_analysis_ws_time_exists=1`、`backfill_pending_rows=0`
- [ ] 微信公众平台申请四类订阅消息模板并填入服务端 `WX_TMPL_*`；小程序无需再填模板 ID，首页会通过 `getSubscribeTemplates` 自动拉取，小程序后台仍需把模板加入本小程序
- [ ] `utils/config.js` 的 `RELEASE_BASE` / `DEV_BASE` 指向已备案 HTTPS 域名
- [ ] 微信公众平台配置 **request 合法域名**
- [ ] 小程序已发布包含 `pages/login-confirm/login-confirm` 的版本
- [ ] `web/.env.local` 配 `VITE_API_BASE=https://api.modouyu.top`（同源可留空），`npm run build` 通过，`web/dist` 部署到 `/var/www/jinribao-admin`（`api.modouyu.top` 的 Nginx SPA 回退）
- [ ] Nginx 终止 TLS + gunicorn/systemd 托管，`/health` 可访问
- [ ] `python -m pytest -q` 通过；`bash server/finish.sh` 的验证项全部通过
- [ ] 按 [§16 真机联调清单](#16-真机联调清单未实测项的可执行步骤) 逐项走通 T0–T20

---

## 12. 回归检查清单

| 检查项 | 方法 | 期望 |
|---|---|---|
| action 对账 | `cd server && python -m pytest -q tests/test_contract.py`（即 finish.sh 验证 3 的单测） | 52 个，名称严格一一对应 |
| 云开发残留 | 检索 `wx.cloud` / `cloud-config` / `cloudbaserc` | 活跃 JS 中 0 命中 |
| 名称一致性 | 检索历史项目名字面（模式见 `server/finish.sh` 验证 5） | 活跃代码中 0 命中 |
| Python 语法 | `python -m compileall -q server/app server/tests` | 全通过 |
| Python 静态检查 | `cd server && python -m ruff check app tests && python3 -m mypy app`（即 finish.sh 验证 7） | 0 error；未安装 dev 依赖时该步跳过 |
| 前端/小程序语法 | `find app.js utils pages components -name '*.js' -exec node --check {} \;`（即 finish.sh 验证 4） | 22 个文件全通过 |
| Web 单元测试 | `cd web && npm test`（即 finish.sh 验证 8） | 3 个文件 22 项通过：`client` 请求/401/导出、`date` 本地日期与跨月跨年、`auth` 登录态 |
| 安全响应头与限制 | `curl -sI .../health`；连续 21 次 `/auth/login`；发送 >1MB 请求体 | 响应含 `nosniff` / `DENY` / `no-store`（HTTPS 含 HSTS）；第 21 次返回 429 且带 CORS 头；超限返回 413 |
| 单测 | `cd server && python -m pytest -q` | 全通过 |
| DB 集成测试（可选） | 起一次性 MySQL 后 `TEST_MYSQL_URL=mysql://root:test@127.0.0.1:3308/jinribao_it python -m pytest -q tests/test_db_integration.py`（命令见 `server/README.md`） | 7 项通过：schema 18 表、p2–p8 迁移各跑两次仍成功、关键唯一索引列顺序、通知去重按团队隔离、订阅设置只留一行、分析任务空间列与索引；未设置变量时自动跳过 |
| 小程序语法 | 关键 JS 逐文件 `node --check` | 全通过 |
| 字段/时间/幂等 | 见 §6 | 格式不变、唯一索引存在 |
| 业务单测 | `cd server && python -m pytest -q` | 含发布生效日、多空间、停用成员、提交字段复核、补录窗口、分页 SQL、预览权限、版本号并发等流程用例 |
| 组织隔离 | `cd server && python -m pytest -q tests/test_org.py` | 跨空间读写拒绝、空间管理员非团队成员、owner 保护、viewer 读写、一人两空间、部门 ≤3 级/环路、left_at 重加入 |
| Web 扫码登录 | `cd server && python -m pytest -q tests/test_web_auth.py` | ticket 一次性/过期、web-mini 令牌互斥、白名单、refresh、微信错误不外泄 |
| Web 业务动作与导出 | `cd server && python -m pytest -q tests/test_web_actions.py` | 工作台复用 metrics、审计强制 workspace 过滤、导出列头/权限/5 万行上限 |
| Web 构建 | `cd web && npm run build` | 类型检查与构建通过 |
| 跳转方式 | 检索 `navigateTo.*pages/index/index` | 0 命中（index 是 tabBar 页，必须用 `switchTab`） |
| 占位域名 | 检索 `example.com` 在 `utils/config.js` | 上线前已替换；未替换时前端会明确报错 |
| 补录窗口一致 | 对比 `utils/date.js` 与 `entries.py` 的 `BACKFILL_DAYS` | 两侧同为 31 |
| 应提交口径 | 检索 `inAnyScope` / `getActiveTemplate(..., true)` / `ignoreScope` | 0 命中；管理端只用 `getReportTaskStatus` |
| 死字段 | 检索 `hasTeam` / `myTeams` / `ignoreScope` | 仅历史注释可命中，代码 0 命中 |

> `server/finish.sh` 为**纯验证脚本**：一次跑完 8 项验证（依赖预检 / compileall / pytest / `node --check` / 残留与名称一致性 / 首次启动配置自检 / `ruff` + `mypy` / Web `vitest`），任一失败项汇总为 `FAIL=1` 退出码；只验证，不修改或删除任何文件，`--verify-only` 为兼容旧用法的等价参数。`ruff`/`mypy` 或 `web/node_modules` 缺失时对应项提示跳过，不判失败。
> 最近一次验证（`bash server/finish.sh`）：8/8 通过；服务端 `200 passed, 7 skipped`，Web `vitest` `22 passed`，`ruff` + `mypy` 全通过。
> 契约对账口径：前端 52 个 action ↔ 后端 52 个 `HANDLERS`；云开发引用、旧名称与死字段在活跃代码中均为 0 命中。

---

## 13. 代码规范

- 小程序端 CommonJS（`require` / `module.exports`），ES6 async/await，不使用 npm 构建。
- 服务端 Python 3，类型注解，模块级 docstring；配置只从 `app/config.py` 读取。
- 命名：展示文案用中文「报数机器人AI」；action 用驼峰；数据库列用 snake_case；日期变量 `entry_date` / `effective_from`。
- 注释说明「为什么」而非「做什么」；禁止在前端注释或代码中出现密钥。
- 改动 `store.js` 签名、`HANDLERS` 集合、`schema.sql` 字段时，必须同步 §4 / §6 与单测。

---

## 14. 无效文件清理结果

项目早期由 CloudBase 脚手架生成，这些文件与当前自有服务端架构方向相反。**本轮已物理删除**，`git ls-files` 中不再包含任何云开发路径（`utils/cloud.js`、`utils/cloud-config.js`、`cloudbaserc.json`、`cloudfunctions/**`、`.cloudbase/**`、`rules/`、`codebuddy-plugin/`）。

| 类别 | 路径 | 处理结果 |
|---|---|---|
| 云开发调用层 | `utils/cloud.js`、`utils/cloud-config.js` | 已删除 |
| 云环境/云函数 | `cloudbaserc.json`、`cloudfunctions/**`、`.cloudbase/container/debug.json` | 已删除 |
| 过时规则目录 | `rules/`、`codebuddy-plugin/` | 已删除（整目录） |
| **保留并改写** | `CODEBUDDY.md` | 已从 CloudBase 规则改写为**自有服务端开发约定**（§0 强制约束），是防止后续开发跑偏的关键入口，**务必保留** |

`project.config.json` → `packOptions.ignore` 仍保留 `server` / `docs` / `README.md` / `CODEBUDDY.md` 等排除项（这些是源码与文档，不属于小程序包内容）。

`bash server/finish.sh` 只做验证（含云开发引用 / 旧名称 / 死字段检索、单测与 Web 测试），**不再包含任何删除逻辑**。

**其它保留**：`.workbuddy/`（项目数据）、`.wbapp_*.genie` 与 `.wbapp_*.privacy.json`（应用卡/隐私配置）、`project.private.config.json`（开发者工具私有设置）、`sitemap.json`。

**可选**：`.codebuddy/skills/`、`.agents/skills/` 为 IDE 侧 CloudBase 技能副本，不影响项目构建，如需彻底清理可在确认后手动删除。

---

## 15. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-09 | 从微信云开发迁移到自有服务端：FastAPI + MySQL 8，22 个 action 全量平移，JWT 鉴权替代 `getWXContext().OPENID` |
| 2026-11-09 | 清理无效函数与越权写入口；修复「停用已发布模板」被拦截的既有缺陷 |
| 2026-11-09 | 项目名称统一为「报数机器人AI」；文档整合为 README + 本开发文档 + 服务端部署专题；输出无效文件清理脚本 |
| 2026-11-09 | 全链路操作场景走查后修 P0/P1：修复 records 跳 tabBar 断点、限制一人一团队、发布保留生效日、401 统一回登录页、停用成员明确提示、占位域名诊断、服务端提交字段复核与成员校验，并补业务流程单测 |
| 2026-11-09 | 走查 P2 边界项：补录入口贯通（首页日期切换 + records 跳转 + 服务端 31 天窗口）、listTeamEntries 自动分页、多模板 scope 并集、停用文案纠偏、草稿预览仅管理员、清理 hasTeam/myTeams 死字段、发布版本号并发加锁顺延；新增 5 个流程单测 |
| 2026-11-09 | 处理遗留项：内容中和 8 个云开发残留文件 + 3 个自动加载规则入口；`CODEBUDDY.md` 改写为自有服务端开发约定并移出删除清单；`finish.sh` 重写为三模式 + 6 项验证（action 契约改由 pytest 校验）；新增 §16 真机联调清单 |
| 2026-11-16 | P2 填报任务：`report_tasks` + 5 个 action + 服务端应提交口径单点实现，看板/报表改调 `getReportTaskStatus` |
| 2026-11-16 | P3 确定性分析：5 张 `analysis_*` 表 + 6 指标/3 规则单点实现 + 幂等执行与只读护栏 + 8 个 action + 小程序分析页；测试覆盖空分母、缺失不补零、阈值边界、幂等复用与写权限断言 |
| 2026-11-16 | 部署化与死代码清理：P2/P3 迁移脚本补部署说明、`SET NAMES utf8mb4` 与 `information_schema` 自检（MySQL 8 实测幂等）；`finish.sh` 改为纯验证脚本；删除 `metrics.definition_map()`、精简 `utils/stats.js` 导出、清理 handlers 注释中的云函数引用 |
| 2026-11-16 | P4 组织与多工作空间：`workspaces`/`departments`/`workspace_members` 三表 + 六表冗余 `workspace_id`；`services/org.py` 统一有效角色与读写判定；9 个 action；只读 viewer、部门 ≤3 级、空间 owner 非团队成员、跨空间隔离；`pages/team` 改为空间/团队切换 + 新建/加入，`pages/profile` 增加切换入口；P4 迁移与有损回滚脚本 |
| 2026-11-16 | P5 Web 管理后台：`web_login_tickets` + 扫码登录（小程序码 + 轮询 + 一次性 ticket）；`aud=web` 12 小时令牌与 `aud=mini` 隔离；`WEB_ACTIONS` 白名单；`confirmWebLogin`/`getWorkspaceOverview`/`listAuditLogs` 3 个 action（44→47）；Excel 导出；小程序 `pages/login-confirm`；`web/` Vue 3 后台（登录/工作台/组织/模板/任务/数据/分析/审计） |
| 2026-11-18 | P6 消息通知与运行验收：`notification_settings`/`notification_logs` 两表；四类微信订阅消息（模板可配置，未配置时 skipped）；提交后订阅授权；APScheduler 应用内调度 + 唯一键去重；分析异常预警；`getNotificationSettings`/`saveNotificationSettings`/`listNotificationLogs`/`getRuntimeMonitor` 4 个 action（47→51）；Web 工作台运行监控面板；修复工作台异常统计误用 `analysis_tasks.workspace_id` 的查询 |
| 2026-11-18 | 调度解耦 + 通知去重隔离：新增独立 `scheduler` 容器（`app/scheduler_worker.py`，backend 固定 `SCHEDULER_ENABLED=0`）与 `scheduler_heartbeats` 心跳表（60s 刷新、180s 判超时，工作台可区分运行中/心跳超时/已关闭）；通知唯一键加入 `scope_key`（团队 id 优先），修复同一用户跨团队互相吞通知；P6 心跳与 P7 去重迁移脚本及回滚 |
| 2026-11-18 | 工程护栏（G1）：新增 `handlers/registry.py` 集中 action 元数据并派生 `HANDLERS`/`WEB_ACTIONS`/`MINI_ONLY_ACTIONS`；订阅消息模板改为服务端 `WX_TMPL_*` 单一来源（`getSubscribeTemplates`，52 个 action），小程序授权按每批 ≤3 个轮换；新增 `tests/test_db_integration.py`（真实 MySQL，`TEST_MYSQL_URL` 门控）覆盖建表、p2–p8 迁移幂等与通知去重隔离，`finish.sh` 增加可选集成测试入口 |
| 2026-11-18 | 租户字段补齐（G1）：`analysis_tasks` 增加 `workspace_id`（创建任务时按团队反查固化）与 `idx_analysis_ws_time`，工作台运行监控改为直接按空间过滤、去掉 `JOIN teams`；P8 迁移与回滚脚本，回填存量任务空间归属 |
| 2026-11-18 | 静态检查（G2）：服务端新增 `pyproject.toml`（ruff 只开 E4/E7/E9/F/I；mypy 渐进式基线）与 `requirements-dev.txt`；修复 mypy 报出的类型问题（微信缓存/定时解析/组织环检测/令牌 sub 校验）；新增 `.github/workflows/ci.yml`（服务端静态检查 + 单测 + 真实 MySQL 集成测试、小程序语法、Web 构建）；`finish.sh` 增加第 7 项 ruff+mypy，未安装 dev 依赖时跳过 |
| 2026-11-18 | 前端测试（G2）：Web 工作台接入 `vitest` + `jsdom`，新增 `vitest.config.ts` 与 `npm test`；覆盖 `api/client`（action/payload、Bearer、401 清 token、业务错误、导出二进制/JSON 错误）、`utils/date`（本地日期、跨月跨年、格式化）、`stores/auth`（初始化、登录态、logout 清缓存）；CI 增加 `npm test`，`finish.sh` 增加第 8 项（无 `node_modules` 时跳过） |
| 2026-11-18 | 安全加固（G2）：新增 `app/security.py` 与 HTTP 中间件——统一安全响应头（HTTPS 才发 HSTS）、1MB 请求体上限（413）、`/auth/login` 等敏感端点进程内限流（429，带 `Retry-After` 与 CORS 头）、仅内网反代信任 `X-Real-IP`；`JWT_SECRET` 启动时要求 ≥32 字符；`/auth/web/refresh` 与 `/api/export/entries` 增加 `aud`/`sub` 校验；新增 9 项安全测试 |
| 2026-11-18 | 订阅授权修复：授权调用从「提交成功后」改到「提交点击」同步链路（异步之后再调会被微信判为非法触发）；模板超过微信单次 3 个上限时按优先级分批、每次点击只弹一组并按团队轮换游标，避免整次授权失败 |
| 2026-11-18 | 模板单一配置源：新增 `getSubscribeTemplates` action（52），模板 ID 只保留在服务端 `WX_TMPL_*`；小程序删除 `utils/config.js` 的 `SUBSCRIBE_TEMPLATES`，改为首页 `onShow` 拉取并缓存，消除两侧手工同步漂移 |
| 2026-11-18 | action 元数据：新增 `handlers/registry.py`，集中声明 52 个 action 的模块归属、Web 可用性、是否写操作与摘要；`HANDLERS` / `WEB_ACTIONS` / `MINI_ONLY_ACTIONS` 改为派生并在导入时双向校验，新增 action 不再需要三处同步白名单 |
| 2026-11-18 | 细节治理（G2）：`@app.on_event` 迁移为 `lifespan`（消除自有弃用警告）；新增统一异常处理器，404/405/413/422/500 一律返回 `{ok:false,message}` 契约（前端可直接展示）；版本号收敛为 `main.APP_VERSION` 单一来源并用于 OpenAPI 与 `/health`；`.gitignore` / `.dockerignore` 补 `.ruff_cache`、`.mypy_cache`、`.DS_Store`；新增 `tests/test_http_errors.py`（3 项） |
| 2026-11-18 | 调度启动竞态（G2）：MySQL 初始化期的临时实例只监听 socket，`mysqladmin ping -h localhost` 会误判健康，导致调度器首个心跳撞 `Connection refused`。compose 健康检查改为走 TCP 且执行真实 `SELECT 1`（含 30s `start_period`）；`scheduler_worker` 启动前调用 `wait_for_db()`（30s 内每 2s 重试，超时退出交由重启策略），新增 2 项单测 |

---

## 16. 真机联调清单（未实测项的可执行步骤）

> 前述修复均为静态走查 + 代码级修改，**尚未在微信开发者工具 / 真机实测**。上线前按下列顺序走一遍，逐项打勾；任何一项不符预期，先回到对应代码位置再改，不要带着疑问发布。

| # | 场景 | 操作步骤 | 预期结果 | 关联修复 |
|---|---|---|---|---|
| T0 | 环境准备 | 配好 `server/.env` 与 `utils/config.js` 域名，执行 `init_db`，启动 uvicorn；开发者工具勾选「不校验合法域名」 | `/health` 返回 200；域名仍是占位符时小程序明确报「服务端地址尚未配置」 | P1 配置诊断 |
| T1 | 冷启动登录 | 清除缓存后首次打开 → 微信一键登录 | 登录成功进入首页；Storage 中只有 token，无明文 openid | JWT 身份链 |
| T2 | 多空间团队 | 创建团队 A → 在 team 页「新建空间」并建团队 B → 在空间/团队列表来回切换 | 两次均成功；切换后首页数据属于对应团队；`active_team_id` 随切换更新 | P4 多空间 |
| T3 | 模板发布 | 新建草稿 → 设**未来生效日** → 「保存并发布」 | toast 显示「YYYY-MM-DD 起生效」而非 `vundefined`；生效日前成员端不展示该模板 | P1 生效日保留 |
| T4 | 填报与幂等 | 首页提交当天数据 → 修改后再提交 → 刷新 | 同一天只有一条记录（覆盖而非新增）；草稿可暂存 | 幂等 upsert |
| T5 | 服务端复核 | 绕过前端直接提交缺必填 / 超范围 / 跨团队 `template_id` 的数据 | 服务端拒绝并给出具体字段错误；草稿不校验必填 | P1 提交校验 |
| T6 | 补录 | records 页点「补录昨日」→ 首页日期变为昨天 → 提交 → 回 records | 昨天记录出现；选 32 天前日期被服务端拒「超出可补录范围」 | P2-1 |
| T7 | 大报表 | 造 > 1000 条录入，报表切「本年」 | 数据完整不静默截断；超 5 万条明确报错 | P2-2 |
| T8 | 多模板范围 | 发布两个模板，分别按成员 / 角色下发 | 看板「应提交名单」为两者并集，催填文案列出两个模板名 | P2-3 |
| T9 | 停用与预览 | 停用最后一个生效模板；普通成员尝试预览草稿 | 弹窗提示「暂无其它生效模板」；普通成员预览被拒 | P2-4 / P2-5 |
| T10 | 并发发版 | 两个管理员同时基于同一版本点「发新版本」 | 版本号顺延不撞唯一键，两者均成功 | P2-6 |
| T11 | 停用成员 | 管理员停用某成员 → 该成员切到 profile | 明确显示「你已被管理员停用」，退出按钮仍可见可点 | P1 停用出口 |
| T12 | 登录过期 | 改 `JWT_SECRET` 或等 token 过期后触发任意请求 | 回到登录页，不出现空壳主界面 | P1 401 错误态 |
| T13 | 迁移与验证 | 存量库按 P2 → P3 → P4 → P5 → P6 → P7 → P8 顺序执行迁移并核对自检数字；终端执行 `bash server/finish.sh` | 迁移自检数字符合 README 说明（P4 的 `*_null_workspace=0`、P5 的 `web_login_tickets_exists=1`、P6 的 `notification_tables_exists=2`、P7 的 `backfill_pending_rows=0`、P8 的 `analysis_workspace_column_exists=1`）；8 项验证全绿、退出码 `FAIL=0` | 本轮清理 |
| T14 | 只读成员 | 空间管理员把某成员设为 viewer → 该成员登录 | 可看首页/记录/模板/历史；提交、建模板、建任务均被拒「只读成员不能进行此操作」 | P4 viewer |
| T15 | 部门层级 | 空间内连续建 3 级部门 → 尝试建第 4 级 → 尝试把上级部门拖到自己的下级 | 第 4 级被拒「部门最多 3 级」；环路移动被拒「不能把部门移动到自己的下级」 | P4 部门 |
| T16 | 跨空间越权 | 用 A 空间账号直接请求 B 空间团队的 `teamId`（改包或改用例） | 读、写均返回业务错误，不泄露 B 空间数据 | P4 隔离 |
| T17 | 通知骨架 | 不配 `WX_TMPL_*` 提交一条日报 → 查看 `notification_logs` | 记录 `status=skipped`、原因为「未配置订阅消息模板」，填报本身成功不受影响 | P6 通知 |
| T18 | 通知去重 | 两个 gunicorn worker 同时触发同一周期提醒 | 同一 `(user_id, notify_type, period_key)` 只有一条记录，微信只收到一次 | P6 调度 |
| T19 | Web 扫码登录 | 打开 `https://api.modouyu.top/` → 微信扫码 → 小程序内点「确认登录」 | 空间 owner/admin 或团队 owner/manager 自动进入工作台；普通 member/viewer 提示「仅团队创建人及以上权限人员可登录管理后台」；同一二维码重复轮询只发一次令牌；5 分钟后过期自动换码 | P5 登录 |
| T20 | Web 白名单与导出 | Web 登录后切换空间/团队，浏览组织/模板/任务/数据/分析/审计；在数据中心导出 Excel | 数据与小程序一致；导出列头/权限与列表一致；用 Web 令牌直接调 `saveEntry` 返回「Web 端无权调用该操作」 | P5 白名单 / 导出 |

> T13 的输出建议整段贴回对话，便于按具体报错逐条收尾。

