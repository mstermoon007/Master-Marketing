# 报数机器人AI · 开发文档

> 版本：2.0（自有服务器架构）｜更新日期：2026-11-09
> 适用代码：小程序前端根目录 + `server/` 服务端工程。本文是唯一开发依据；`rules/`、`CODEBUDDY.md`、`codebuddy-plugin/` 为旧 CloudBase 脚手架残留，**不再适用**（见 §14）。

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
| `pages/` | 10 个页面：index / records / profile / team + admin 下 6 页 | 只做 UI 与交互 |
| `components/dynamic-form/` | 动态表单组件（按模板 fields 渲染） | 字段契约见 §6 |
| `utils/store.js` | 22 个业务 action + `getActiveTemplate` / `getEffectiveTemplates` / `inScope` / `inAnyScope` + `listTeamEntries` 自动翻页 | **对外签名冻结** |
| `utils/http.js` | `wx.request`、Bearer、401 拦截、token 存储（含内存兜底） | 传输层唯一入口 |
| `utils/session.js` | 登录、上下文 `loadContext()`、退出、401 钩子 | 本地只存 token 与 openid 展示值 |
| `utils/config.js` | `RELEASE_BASE` / `DEV_BASE` / 超时 | 上线前必改 |
| `utils/date.js` / `stats.js` / `validator.js` | 日期（含 `BACKFILL_DAYS` 补录窗口）、统计聚合、表单校验（纯前端） | 无网络调用；改 `BACKFILL_DAYS` 必须同步服务端 |
| `project.config.json` | 开发者工具配置、`packOptions.ignore` 打包排除 | 后端/文档目录必须排除 |

### 服务端（`server/`）

| 路径 | 职责 |
|---|---|
| `app/main.py` | FastAPI：`/auth/login`、`/api`、`/health`、统一响应与异常 |
| `app/auth.py` | `code2session`、JWT 签发/验签、`extract_uid` |
| `app/config.py` | 环境变量集中读取 + 启动时密钥校验 |
| `app/db.py` | 连接、24 位 hex 主键、JSON 列序列化、标识符白名单 |
| `app/handlers/` | `common.py` + 5 个业务模块 + `__init__.py` 注册表（22 个 action） |
| `app/init_db.py` | 按 `sql/schema.sql` 幂等建表 |
| `sql/schema.sql` | 5 张表 DDL + 唯一索引 |
| `tests/test_contract.py` | action 对账、JWT、标识符校验等单测 |
| `.env.example` | 环境变量模板（**真实 `.env` 不入库**） |

---

## 4. 接口契约

### 4.1 端点

| 端点 | 方法 | 鉴权 | 请求 | 响应 |
|---|---|---|---|---|
| `/auth/login` | POST | 无 | `{"code": "<wx.login code>"}` | `{"ok":true,"data":{"token","openid"}}`（团队上下文由 `getMyMember`/`getTeam` 取，登录端点不返回 `hasTeam`） |
| `/api` | POST | `Authorization: Bearer <JWT>` | `{"action":"...", ...payload}` | `{"ok":true,"data":...}` 或 `{"ok":false,"message":"..."}` |
| `/health` | GET | 无 | — | `{"ok":true,"service":"jinribao","version":"2.0.0"}` |

**错误语义**：`401` = 登录过期（前端 `http.js` 清 token → `session.signOut()` → 页面回到登录态）；业务错误用 HTTP 200 + `ok:false` + `message`；服务异常用 HTTP 500 + 通用文案，不回传堆栈。

### 4.2 22 个业务 action

权限列说明：**登录** = 只需有效 JWT；**成员** = `require_member`；**管理员** = `require_manager`（owner/manager）；**本人** = 按 JWT 身份过滤本人数据。

| 分组 | action | 前端函数 | 说明 | 权限 |
|---|---|---|---|---|
| 团队 | `createTeam` | `store.createTeam(name, memberName)` | 创建团队并成为 owner | 登录 |
| 团队 | `findTeam` | `store.findTeamByCode(code)` | 按邀请码查团队 | 登录 |
| 团队 | `joinTeam` | `store.joinTeam(teamId, memberName)` | 加入团队 | 登录 |
| 团队 | `getTeam` | `store.getTeam(teamId)` | 团队详情 | 成员 |
| 团队 | `updateTeamConfig` | `store.updateTeamConfig(teamId, config)` | 团队配置（如 `memberSeeTeamTotal`） | 管理员 |
| 成员 | `getMyMember` | `store.getMyMember()` | 我的成员资料 | 登录 |
| 成员 | `listMembers` | `store.listMembers(teamId)` | 成员列表 | 管理员 |
| 成员 | `updateMember` | `store.updateMember(id, patch)` | 改姓名/角色/状态 | 管理员 |
| 成员 | `removeMember` | `store.removeMember(id)` | 移除成员 | 管理员 |
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
| 审计 | `log` | `store.logAction(teamId, action, ...)` | 上报审计，失败不阻断主流程 | 成员 |

> **纯前端判定**（不产生独立网络请求，不在 `HANDLERS` 注册表中）：
> `getEffectiveTemplates()` 取全部已生效的 published 模板（按生效日 → 版本降序）；
> `getActiveTemplate()` 从中取第一个命中成员 `inScope` 的（成员端一天一条记录）；
> `inAnyScope()` 供管理端算「应提交名单」——命中任意一个已生效模板即算，避免多模板分别下发时漏人。
> `listTeamEntries` 虽是一个 action，但 `store.js` 会按 1000 条/页循环调用直到拉全（上限 50 页，超限抛错）。
> 已删除的 `listEntriesByUser` 前端零调用，后端亦未迁移；新增 action 必须前后端成对注册并更新 `tests/test_contract.py` 的期望集合。

---

## 5. 登录与鉴权

| 环节 | 实现 | 位置 |
|---|---|---|
| 取 code | `wx.login` | `utils/session.js` `login()` |
| 换 openid | 服务端 `jscode2session` GET 微信接口 | `server/app/auth.py` `code2session()` |
| 签发 | HS256 JWT，`sub=openid`、`iss`、`iat`、`exp`（默认 30 天） | `auth.issue_token()` |
| 本地存储 | `auth_token` / `auth_openid`（Storage 失败时内存兜底） | `utils/http.js` / `session.js` |
| 每次请求 | `Authorization: Bearer <token>` | `utils/http.js` `request()` |
| 验签注入 | `extract_uid()` → `dispatch(conn, uid, event)` | `server/app/main.py` |
| 过期处理 | 401 → 清 token → `signOut()` → 页面回登录态 | `http.js` + `session.js` |

**AppSecret 与 `JWT_SECRET` 只允许出现在服务端环境变量，绝不进小程序包。**

---

## 6. 数据模型

`server/sql/schema.sql`，MySQL 8 / utf8mb4。主键均为 24 位 hex 字符串 `id`（等价旧云库 `_id`），前端无需 `normalize`。

| 表 | 关键字段 | 约束 / 索引 |
|---|---|---|
| `teams` | `team_id`(邀请码)、`name`、`owner_uid`、`config` JSON | `uk_teams_team_id` 唯一 |
| `members` | `team_id`、`user_id`(openid)、`name`、`role`(owner/manager/member)、`status` | `uk_members_team_user(team_id,user_id)` 唯一 |
| `form_templates` | `template_id`、`version`、`fields` JSON、`scope` JSON、`effective_from`、`status`(draft/published/archived) | `uk_tpl_team_id_ver(team_id,template_id,version)` 唯一 |
| `daily_entries` | `team_id`、`user_id`、`entry_date`、`form_data` JSON、`status`(draft/submitted)、`template_version` | `uk_entry_team_user_date` 唯一（**saveEntry 幂等**） |
| `audit_logs` | `actor`、`action`、`target_type`、`target_id`、`detail` JSON | `idx_audit_team_time` |

**字段/时间契约（回归关键）**

- 时间统一 ISO8601 UTC 字符串（`2026-11-09T09:08:02.000Z`），与旧云函数 `new Date().toISOString()` 一致，保障 `records.js` 的「补录」判定。
- `entry_date` / `effective_from` 为 `YYYY-MM-DD` 字符串，字典序即区间序。
- JSON 列（`config` / `fields` / `scope` / `form_data` / `detail`）由 `db.py` 自动序列化，读取时自动反序列化。
- 写入字段走白名单：客户端不能改写 `id`、`team_id`、`template_id`、`version`、`user_id`、`created_by` 等归属字段。

---

## 7. 前端分层约定

1. 页面只调用 `store.js` 与 `session.js`，**禁止直接 `wx.request` / 直接拼 URL**。
2. `store.js` 每个函数只做 `callApi(action, payload)`；跨请求组合逻辑（如 `getActiveTemplate`）也放在这一层。
3. 身份相关：页面可用 `ctx.uid` 做展示，但**不得把 uid 当作权限依据**；权限判定用 `session.isManager(member)`，最终以服务端校验为准。
4. `loadContext()` 有缓存；创建/加入团队后调用 `session.clearContext()` 再刷新。
5. 登录竞态：多个页面 `onShow` 可能并发调用 `loadContext()`，不要在页面里自行触发重复登录。
6. **补录链路**：首页 `entryDate` 默认今天，左右箭头 / `<picker mode="date">` 可切到近 31 天；`records` 页的「补录昨日」或点击记录日期，通过 Storage key `backfill_date` 把目标日期传给首页 `onShow`（index 是 tabBar 页，不能 URL 传参）。首页每次 `onShow` 默认回今天，只有读到合法 `backfill_date` 才切日期。补录沿用**当前生效模板**（旧版本发布时已归档），`source` 标记为 `backfill`。

---

## 8. 服务端分层约定

1. `main.py` 只做路由、验签、响应包装；业务逻辑一律在 `handlers/`。
2. 每个 handler 签名 `(conn, uid, payload)`；`uid` 来自 JWT，**不得从 payload 读取身份**。
3. 写操作先 `require_member` / `require_manager`，再校参数，最后落库；涉及团队归属必须先校验。
4. SQL 全部参数化；动态表名/列名经 `db._check_ident()` 白名单校验。
5. 抛 `BusinessError("用户可读文案")` 表示业务失败；其他异常由 `main.py` 统一记日志并返回通用错误。
6. 新增 action：在对应模块 `HANDLERS` 注册 → `store.js` 加包装函数 → 更新单测期望集合。

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
| R7 | **一人一团队** | `createTeam` / `joinTeam` 拒绝已有成员记录；`find_member_by_uid` 按 `joined_at ASC, id ASC` 取确定性结果，避免 `getMyMember` 随机落到别队 |
| R8 | 服务端提交复核 | `saveEntry` 校验模板归属，并对 `submitted` 按模板 fields 复核必填/类型/范围/选项；前端模板新鲜度校验失败时提交必须阻断（草稿可离线暂存） |
| R9 | 停用成员 | `getMyMember` 对 `status != active` 直接报「已被停用」，前端保留登录态以显示退出入口 |
| R10 | **补录窗口** | 前端 `date.js BACKFILL_DAYS=31` 与服务端 `entries.py BACKFILL_DAYS=31` 必须一致；服务端 UTC、前端本地时区，服务端上下各放宽 1 天避免凌晨误拒。两处任一改动都要同步 |
| R11 | 大数据静默截断 | `list_team_entries` 分页 SQL 的 `ORDER BY entry_date DESC, id DESC` 必须保留（同日多条翻页不重不漏）；前端 50 页上限触发时抛业务错误，不得降级为部分数据 |
| R12 | 多模板下发口径 | 管理端 `dashboard` / `reports` 的「应提交名单」必须走 `inAnyScope(所有已生效模板)`；只取最新一个模板会漏掉按成员/角色分别下发的成员 |
| R13 | 并发发布与预览 | `publishTemplate` 先 `SELECT ... FOR UPDATE` 锁团队行，再按冲突顺延 `version`（`uk_tpl_team_id_ver` 不再撞键）；草稿/归档 `getTemplate` 只放行管理员 |

另：模板状态只能经 `publishTemplate` 变成 `published`；`createDraft` 强制 draft；`updateTemplateRow` 只允许把状态改为 `archived`（停用），且允许停用已发布模板。停用**不会**回退到上一版本（旧版本发布时已归档），管理端弹窗按实际剩余的已生效模板数量提示。审计 `log` 需校验团队归属，防止跨团队写入。

---

## 10. 本地开发流程

### 环境变量（`server/.env`，参考 `.env.example`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3306` | MySQL 地址 |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `jinribao` / 空 / `jinribao` | 库名沿用内部标识 |
| `WX_APPID` / `WX_SECRET` | 空 | 服务端专用，启动时强制校验非空 |
| `JWT_SECRET` | 空 | 随机长串，启动时强制校验非空 |
| `JWT_TTL_DAYS` | `30` | token 有效期 |
| `WX_HTTP_TIMEOUT` | `5` | 微信接口超时（秒） |
| `PORT` | `8000` | 服务端口 |

### 步骤

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 填真实值
python -m app.init_db       # 幂等建库建表
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
python -m pytest -q         # 契约与鉴权单测
```

前端：改 `utils/config.js` 的域名 → 微信开发者工具导入项目根 → 详情/本地设置勾选「不校验合法域名」（仅开发期）。

---

## 11. 上线清单

- [ ] `server/.env` 配齐 DB / `WX_APPID` / `WX_SECRET` / `JWT_SECRET`，`.env` 不入库
- [ ] `python -m app.init_db` 成功，5 张表与唯一索引齐全
- [ ] `utils/config.js` 的 `RELEASE_BASE` / `DEV_BASE` 指向已备案 HTTPS 域名
- [ ] 微信公众平台配置 **request 合法域名**
- [ ] Nginx 终止 TLS + gunicorn/systemd 托管，`/health` 可访问
- [ ] `python -m pytest -q` 通过；`bash server/finish.sh` 的验证项全部通过
- [ ] 按 [§16 真机联调清单](#16-真机联调清单未实测项的可执行步骤) 逐项走通 T0–T13

---

## 12. 回归检查清单

| 检查项 | 方法 | 期望 |
|---|---|---|
| action 对账 | `cd server && python3 -m pytest -q tests/test_contract.py::test_all_legacy_actions_migrated`（即 finish.sh 验证 3 的单测） | 22 个，名称严格一一对应 |
| 云开发残留 | 检索 `wx.cloud` / `cloud-config` / `cloudbaserc` | 活跃 JS 中 0 命中 |
| 名称一致性 | 检索历史项目名字面（模式见 `server/finish.sh` 验证 5） | 活跃代码中 0 命中 |
| Python 语法 | `python3 -m compileall -q server/app server/tests` | 全通过 |
| 单测 | `cd server && python3 -m pytest -q` | 全通过 |
| 小程序语法 | 关键 JS 逐文件 `node --check` | 全通过 |
| 字段/时间/幂等 | 见 §6 | 格式不变、唯一索引存在 |
| 业务单测 | `cd server && python3 -m pytest -q` | 含发布生效日、一人一团队、停用成员、提交字段复核、补录窗口、分页 SQL、预览权限、版本号并发等流程用例 |
| 跳转方式 | 检索 `navigateTo.*pages/index/index` | 0 命中（index 是 tabBar 页，必须用 `switchTab`） |
| 占位域名 | 检索 `example.com` 在 `utils/config.js` | 上线前已替换；未替换时前端会明确报错 |
| 补录窗口一致 | 对比 `utils/date.js` 与 `entries.py` 的 `BACKFILL_DAYS` | 两侧同为 31 |
| 多模板口径 | 检索 `getActiveTemplate(..., true)` / `ignoreScope` | 0 命中；管理端只用 `getEffectiveTemplates` + `inAnyScope` |
| 死字段 | 检索 `hasTeam` / `myTeams` / `ignoreScope` | 仅历史注释可命中，代码 0 命中 |

> 当前会话无命令行工具、无本地文件删除能力，也未配置 Python / JS 语言服务（LSP 探测均返回 "No LSP server configured"），因此编译、单测与 `node --check` 必须在**本机终端**执行。
> `server/finish.sh` 已打包为 6 项一键验证：默认「列清单 → 输入 `yes` → 删除 + 验证」，`--yes` 免确认，`--verify-only` 只验证不删除；任一失败项会汇总为 `FAIL=1` 退出码。
> 会话内**已实际执行**的静态验证：前端 22 个 action ↔ 后端 22 个 `HANDLERS`、云开发引用 0 命中、旧名称 0 命中（仅脚本检索模式自引用）、死字段 0 命中、`alwaysApply: true` 仅剩已改写的 `CODEBUDDY.md` 与脚本检索模式。

---

## 13. 代码规范

- 小程序端 CommonJS（`require` / `module.exports`），ES6 async/await，不使用 npm 构建。
- 服务端 Python 3，类型注解，模块级 docstring；配置只从 `app/config.py` 读取。
- 命名：展示文案用中文「报数机器人AI」；action 用驼峰；数据库列用 snake_case；日期变量 `entry_date` / `effective_from`。
- 注释说明「为什么」而非「做什么」；禁止在前端注释或代码中出现密钥。
- 改动 `store.js` 签名、`HANDLERS` 集合、`schema.sql` 字段时，必须同步 §4 / §6 与单测。

---

## 14. 无效文件与清理

会话环境无删除能力，因此采取「**先内容中和，再由脚本物理删除**」两步。当前所有残留文件均已清空实现、去掉旧名称与 CloudBase 引导，并被 `project.config.json` → `packOptions.ignore` 排除，**不进入小程序包、不会误导后续开发**。

| 类别 | 路径 | 中和后的状态 | 脚本是否删除 |
|---|---|---|---|
| 云开发调用层 | `utils/cloud.js`、`utils/cloud-config.js` | 仅剩「已废弃」注释，无可执行代码、无 `wx.cloud` | 是 |
| 云环境/云函数 | `cloudbaserc.json`、`cloudfunctions/login/**`、`cloudfunctions/api/**`、`.cloudbase/container/debug.json` | 占位 JSON / 空注释，原 400 余行云函数实现已清空 | 是 |
| 过时规则目录 | `rules/`、`codebuddy-plugin/` | 3 个 `alwaysApply: true` 自动加载入口已改为 `false` 并写成废弃说明 | 是（整目录） |
| **保留并改写** | `CODEBUDDY.md` | 已从 CloudBase 规则改写为**自有服务端开发约定**（§0 强制约束），是防止后续开发跑偏的关键入口 | **否，务必保留** |

执行 `bash server/finish.sh` 可彻底删除上述「是」的文件与目录，并顺带完成 §12 的 6 项静态验证；清理完成后 `packOptions.ignore` 中对应条目可精简，保留也无害。只验证不删除用 `--verify-only`。

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

---

## 16. 真机联调清单（未实测项的可执行步骤）

> 前述修复均为静态走查 + 代码级修改，**尚未在微信开发者工具 / 真机实测**。上线前按下列顺序走一遍，逐项打勾；任何一项不符预期，先回到对应代码位置再改，不要带着疑问发布。

| # | 场景 | 操作步骤 | 预期结果 | 关联修复 |
|---|---|---|---|---|
| T0 | 环境准备 | 配好 `server/.env` 与 `utils/config.js` 域名，执行 `init_db`，启动 uvicorn；开发者工具勾选「不校验合法域名」 | `/health` 返回 200；域名仍是占位符时小程序明确报「服务端地址尚未配置」 | P1 配置诊断 |
| T1 | 冷启动登录 | 清除缓存后首次打开 → 微信一键登录 | 登录成功进入首页；Storage 中只有 token，无明文 openid | JWT 身份链 |
| T2 | 团队约束 | 未入团队 → 创建团队 → 再尝试创建或用邀请码加入第二个团队 | 第一次成功；第二次明确提示「已有团队」并回首页，不再出现团队上下文随机错乱 | P0 一人一团队 |
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
| T13 | 清理与验证 | 终端执行 `bash server/finish.sh` | 6 项验证全绿、退出码 `FAIL=0` | 本轮清理 |

> T13 的输出建议整段贴回对话，便于按具体报错逐条收尾。

