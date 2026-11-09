# 报数机器人AI

团队日报小程序：成员按模板填写当日成果，管理端下发模板、查看看板与报表。
架构为 **微信小程序 + 自有服务端（Python FastAPI）+ MySQL 8**，不使用微信云开发。

> **项目名称统一为「报数机器人AI」**。已覆盖小程序标题、登录页、开发者工具配置、应用卡配置与全部文档。
> 仅内部技术标识（`jinribao` 数据库名 / logger / JWT issuer）沿用旧值，不对外展示，改动会牵动已配置的 `.env`，故保留，详见开发文档 §1。

## 文档索引

| 文档 | 内容 |
|---|---|
| `README.md`（本文） | 项目总览、技术栈、快速开始、文档导航 |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | **开发文档**：架构、接口契约、22 个 action、数据表、安全约定、回归清单、**§16 真机联调清单** |
| [`server/README.md`](server/README.md) | 服务端部署与运维（环境变量、建表、进程、域名） |
| [`server/sql/schema.sql`](server/sql/schema.sql) | MySQL 8 建表脚本（5 张表 + 唯一索引） |
| `CODEBUDDY.md` | **项目开发约定**（IDE 自动加载）：自有服务端架构与强制约束，**保留项，勿删** |
| `server/tests/` | 契约、鉴权与业务流程单元测试 |
| `server/finish.sh` | 一次性清理无效文件 + 6 项静态验证；`--verify-only` 只验证不删除 |

## 架构

```
微信小程序（10 个页面 + dynamic-form 组件）
   │  utils/store.js    业务动作收敛为 action + payload
   │  utils/http.js     wx.request + Authorization: Bearer <JWT>
   ▼
自有服务端 server/（FastAPI）
   │  POST /auth/login  wx.login code → code2session → 签发 JWT
   │  POST /api         22 个 action 统一分发，验签后注入身份
   │  GET  /health      健康检查
   ▼
MySQL 8（teams / members / form_templates / daily_entries / audit_logs）
```

| 层 | 技术 | 入口 |
|---|---|---|
| 小程序 | 原生微信小程序（无框架） | `app.js`、`pages/`、`components/`、`utils/` |
| 传输 | `wx.request` + JWT | `utils/http.js`、`utils/session.js`、`utils/config.js` |
| 服务端 | Python 3 + FastAPI + PyMySQL + PyJWT | `server/app/` |
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

# 3) 验证与清理（三选一）
cd .. && bash server/finish.sh --verify-only   # 只跑 6 项验证，一个文件都不删
cd .. && bash server/finish.sh                 # 列清单 → 输入 yes → 删除 + 验证
cd .. && bash server/finish.sh --yes           # 跳过确认，直接删除 + 验证
```

### 首次启动自检（导入项目后先做这 3 件事）

1. `utils/config.js` 的 `RELEASE_BASE` / `DEV_BASE` 换成真实 HTTPS 域名；仍是 `example.com` 时，请求会直接报「服务端地址尚未配置」，而不是笼统的网络错误。
2. `server/.env` 由 `.env.example` 复制并填 `DB_*` / `WX_APPID` / `WX_SECRET` / `JWT_SECRET`；缺密钥服务启动即报错。
3. 开发期在微信开发者工具「详情 → 本地设置」勾选「不校验合法域名」（`project.config.json` 默认 `urlCheck: true`）。

> 脚本的「验证 7」会自动检查第 1、2 项是否遗漏，只提示不判失败。

## 上线前必做

1. `server/.env` 配好 `DB_*` / `WX_APPID` / `WX_SECRET` / `JWT_SECRET`（密钥只在服务端）。
2. `utils/config.js` 换成自己的 HTTPS 已备案域名；微信公众平台 → 开发管理 → 服务器域名 → 添加 **request 合法域名**。
3. 执行 `python -m app.init_db`，用 Nginx 终止 TLS，gunicorn/systemd 托管进程。
4. 真机预览与上线必须完成第 2 步；IP / localhost 在真机不可用。
5. `bash server/finish.sh` 的 6 项验证全绿，并按 [`docs/DEVELOPMENT.md` §16](docs/DEVELOPMENT.md) 的真机联调清单逐项走通。

## 开发约定（摘要）

- `utils/store.js` 的对外函数是对外契约，改动会连锁影响页面，非必要不动。
- 时间统一 ISO8601 UTC 字符串；`entry_date` / `effective_from` 为 `YYYY-MM-DD`。
- 主键为 24 位 hex 字符串 `id`（等价旧云库 `_id`），前端无需字段映射。
- 管理端权限由服务端 `require_manager` 校验，前端只负责隐藏入口；草稿/归档模板预览仅管理员可读。
- 补录窗口为近 31 天（`utils/date.js` 与 `entries.py` 的 `BACKFILL_DAYS` 必须一致），服务端独立校验日期。
- `listTeamEntries` 由 `store.js` 自动翻页拉全（单次 1000 条，上限 5 万条），超限明确报错而不是静默截断。
- 管理端「应提交名单」按**全部已生效模板**的下发范围取并集，不再只看最新一个模板。
- 新增 action 必须同时在 `utils/store.js` 与 `server/app/handlers/` 注册，并补 `server/tests/test_contract.py`。
- 强制约束全文见 `CODEBUDDY.md`（禁止 `wx.cloud` / 云函数 / CloudBase 能力）。

完整约定、接口清单与回归检查表见 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)。

## 无效文件清理

项目早期由 CloudBase 脚手架生成，残留文件与当前架构方向相反。它们已在 `project.config.json` 的 `packOptions.ignore` 中排除、**不进入小程序包**；并且已完成**内容中和**：

| 类别 | 路径 | 当前状态 |
|---|---|---|
| 云开发调用层 | `utils/cloud.js`、`utils/cloud-config.js` | 实现已清空，仅剩「已废弃」注释；无 `wx.cloud` / 旧名称 |
| 云环境/云函数 | `cloudbaserc.json`、`cloudfunctions/**`、`.cloudbase/container/debug.json` | 占位 JSON / 空注释，无任何可执行云函数代码 |
| 过时规则 | `rules/`、`codebuddy-plugin/` | 自动加载入口（`alwaysApply: true`）已禁用并改写为废弃说明 |
| **保留并改写** | `CODEBUDDY.md` | 已从 CloudBase 规则改写为**自有服务端开发约定**，是防止后续开发跑偏的关键入口，**勿删** |

也就是说：**即使暂时不执行清理脚本，这些残留也不会误导后续开发、不会进入小程序包**。执行 `bash server/finish.sh` 是为了彻底移除文件并运行终端侧验证（`compileall` / `pytest` / `node --check` / action 名称对账 / 残留引用 / 首次启动自检），输出建议整段贴回对话以便按报错收尾。

> 当前会话无命令行、无本地文件删除工具，也没有配置 Python/JS 语言服务，因此终端侧验证与物理删除需由你在本机执行；可在不删除任何文件的情况下先跑 `bash server/finish.sh --verify-only`。
