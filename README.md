# 报数机器人AI

团队日报小程序 + Web 管理后台：成员按模板填写当日成果，管理端下发模板、查看看板与报表。
架构为 **微信小程序 + Web 管理后台（Vue 3）+ 自有服务端（Python FastAPI）+ MySQL 8**，不使用微信云开发。

> **项目名称统一为「报数机器人AI」**。已覆盖小程序标题、登录页、开发者工具配置、应用卡配置与全部文档。
> 仅内部技术标识（`jinribao` 数据库名 / logger / JWT issuer）沿用旧值，不对外展示，改动会牵动已配置的 `.env`，故保留，详见开发文档 §1。

## 文档索引

| 文档 | 内容 |
|---|---|
| `README.md`（本文） | 项目总览、技术栈、快速开始、文档导航 |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | **开发文档**：架构、接口契约、47 个 action、数据表、Web 扫码登录、安全约定、回归清单、**§16 真机联调清单** |
| [`server/README.md`](server/README.md) | 服务端部署与运维（环境变量、建表、进程、域名、Web 后台） |
| [`server/sql/schema.sql`](server/sql/schema.sql) | MySQL 8 建表脚本（15 张表 + 唯一索引） |
| `CODEBUDDY.md` | **项目开发约定**（IDE 自动加载）：自有服务端架构与强制约束，**保留项，勿删** |
| `server/tests/` | 契约、鉴权与业务流程单元测试 |
| `server/finish.sh` | 6 项静态验证（只验证，不修改/删除任何文件） |

## 架构

```
微信小程序（12 个页面 + dynamic-form 组件）
   │  utils/store.js    业务动作收敛为 action + payload
   │  utils/http.js     wx.request + Authorization: Bearer <JWT>
   ▼
自有服务端 server/（FastAPI）
   │  POST /auth/login          wx.login code → code2session → 签发小程序 JWT
   │  POST /auth/web/ticket     管理后台扫码票据 + 小程序码
   │  POST /auth/web/ticket/status  轮询 → 一次性签发 aud=web JWT
   │  POST /api                 47 个 action 统一分发，按 aud 做白名单
   │  POST /api/export/entries  团队日报 Excel 导出
   │  GET  /health              健康检查
   ▼
MySQL 8（workspaces / departments / workspace_members / teams / members / form_templates / daily_entries / report_tasks / audit_logs / analysis_* / web_login_tickets）

Web 管理后台 web/（Vue 3 + Vite + Element Plus + Pinia）
   └─ admin.modouyu.top，仅空间所有者扫码登录
```

| 层 | 技术 | 入口 |
|---|---|---|
| 小程序 | 原生微信小程序（无框架） | `app.js`、`pages/`、`components/`、`utils/` |
| Web 后台 | Vue 3 + Vite + TypeScript + Element Plus + Pinia | `web/src/` |
| 传输 | `wx.request` / `fetch` + JWT | `utils/http.js`、`utils/session.js`、`web/src/api/client.ts` |
| 服务端 | Python 3 + FastAPI + PyMySQL + PyJWT + openpyxl | `server/app/` |
| 数据 | MySQL 8（JSON 列承载模板/录入结构） | `server/sql/schema.sql` |

身份只认服务端验签 JWT 的 `sub`（openid），**客户端传的 uid/openid 一律不参与鉴权**。

## 快速开始

```bash
# 1) 服务端
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 填 DB / WX_APPID / WX_SECRET / JWT_SECRET
python -m app.init_db         # 幂等建库建表
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2) 小程序：改 utils/config.js 的 RELEASE_BASE / DEV_BASE 为已备案 HTTPS 域名
#    用微信开发者工具导入项目根目录；开发期可勾选「不校验合法域名」

# 3) Web 管理后台（可选）
cd web
npm ci
npm run dev        # http://localhost:5173，代理到本机 8000

# 4) 验证（只跑 6 项静态检查，不修改任何文件）
bash server/finish.sh
```

### 首次启动自检（导入项目后先做这 3 件事）

1. `utils/config.js` 的 `RELEASE_BASE` / `DEV_BASE` 换成真实 HTTPS 域名；仍是 `example.com` 时，请求会直接报「服务端地址尚未配置」，而不是笼统的网络错误。
2. `server/.env` 由 `.env.example` 复制并填 `DB_*` / `WX_APPID` / `WX_SECRET` / `JWT_SECRET`；缺密钥服务启动即报错。
3. 开发期在微信开发者工具「详情 → 本地设置」勾选「不校验合法域名」（`project.config.json` 默认 `urlCheck: true`）。

> `bash server/finish.sh` 的验证 6/6 会自动检查第 1、2 项是否遗漏，只提示不判失败。

## 上线前必做

1. `server/.env` 配好 `DB_*` / `WX_APPID` / `WX_SECRET` / `JWT_SECRET`（密钥只在服务端）。
2. `utils/config.js` 换成自己的 HTTPS 已备案域名；微信公众平台 → 开发管理 → 服务器域名 → 添加 **request 合法域名**。
3. 全新安装执行 `python -m app.init_db`（15 张表）；存量库按顺序执行 `server/sql/migrate_p2_report_tasks.sql` → `server/sql/migrate_p3_analysis.sql` → `server/sql/migrate_p4_workspaces.sql` → `server/sql/migrate_p5_web_tickets.sql`（幂等，脚本末尾自带自检）。P4 回滚脚本 `migrate_p4_rollback.sql` 有损，执行前先备份；P5 回滚 `migrate_p5_rollback.sql` 只删登录票据表。用 Nginx 终止 TLS，gunicorn/systemd 托管进程。
4. Web 后台设置 `WEB_ORIGIN=https://admin.modouyu.top` 与 `VITE_API_BASE=https://api.modouyu.top`，构建 `web/dist` 后部署到独立子域；小程序需包含 `pages/login-confirm/login-confirm`。
5. 真机预览与上线必须完成第 2 步；IP / localhost 在真机不可用。
6. `bash server/finish.sh` 的 6 项验证全绿，并按 [`docs/DEVELOPMENT.md` §16](docs/DEVELOPMENT.md) 的真机联调清单逐项走通。

## 开发约定（摘要）

- `utils/store.js` 的对外函数是对外契约，改动会连锁影响页面，非必要不动。
- 时间统一 ISO8601 UTC 字符串；`entry_date` / `effective_from` 为 `YYYY-MM-DD`。
- 主键为 24 位 hex 字符串 `id`（等价旧云库 `_id`），前端无需字段映射。
- 管理端权限由服务端 `require_manager` 校验，前端只负责隐藏入口；草稿/归档模板预览仅管理员可读。
- 补录窗口为近 31 天（`utils/date.js` 与 `entries.py` 的 `BACKFILL_DAYS` 必须一致），服务端独立校验日期。
- `listTeamEntries` 由 `store.js` 自动翻页拉全（单次 1000 条，上限 5 万条），超限明确报错而不是静默截断。
- 管理端「应提交名单」按**全部已生效模板**的下发范围取并集，不再只看最新一个模板。
- 新增 action 必须同时在 `utils/store.js` 与 `server/app/handlers/` 注册，并补 `server/tests/test_contract.py`。
- Web 管理后台仅空间所有者可扫码登录；Web 令牌（`aud=web`）只能调用 `handlers.WEB_ACTIONS` 白名单，不能调用填报类 action。
- 强制约束全文见 `CODEBUDDY.md`（禁止 `wx.cloud` / 云函数 / CloudBase 能力）。

完整约定、接口清单与回归检查表见 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)。

## 无效文件清理结果

项目早期由 CloudBase 脚手架生成，这些文件与当前自有服务端架构方向相反，**已全部物理删除**（`git ls-files` 中不再存在）：

| 类别 | 路径 | 处理结果 |
|---|---|---|
| 云开发调用层 | `utils/cloud.js`、`utils/cloud-config.js` | 已删除 |
| 云环境/云函数 | `cloudbaserc.json`、`cloudfunctions/**`、`.cloudbase/container/debug.json` | 已删除 |
| 过时规则 | `rules/`、`codebuddy-plugin/` | 已删除（整目录） |
| **保留并改写** | `CODEBUDDY.md` | 已从 CloudBase 规则改写为**自有服务端开发约定**，是防止后续开发跑偏的关键入口，**勿删** |

`bash server/finish.sh` 现在是**纯验证脚本**，不再删除任何文件，只跑 6 项静态检查：依赖预检、`compileall`、`pytest`（含 action 契约对账）、`node --check`、残留引用/旧名称/死字段检索、首次启动配置自检。
