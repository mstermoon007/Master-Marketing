# 报数机器人AI · 服务端部署说明

自有服务端（Python 3 + FastAPI + MySQL 8），替代原微信云开发云函数。
对外保持同一套 `action + payload` 契约，小程序端 10 个页面零改动。

> 项目总览见 [`../README.md`](../README.md)，完整接口/数据表/回归清单见 [`../docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md)。
> 本文件只讲**服务端部署与运维**，接口与字段约定以开发文档为准。

## 目录

| 路径 | 说明 |
|---|---|
| `app/main.py` | FastAPI 应用：`/auth/login`、`/api`、`/health` |
| `app/auth.py` | `code2session` + JWT 签发/验签 |
| `app/config.py` | 环境变量 + 启动时密钥校验 |
| `app/db.py` | MySQL 连接、字符串主键、JSON 列、标识符白名单 |
| `app/handlers/` | 22 个在用业务 action（团队/成员/模板/录入/审计） |
| `app/init_db.py` | 幂等建表入口 |
| `sql/schema.sql` | 5 张表 DDL + 唯一索引 |
| `tests/` | 契约、鉴权与业务流程单元测试（不依赖真实 MySQL） |
| `finish.sh` | 项目无效文件清理 + 6 项静态验证（项目根执行）；支持 `--yes` 免确认、`--verify-only` 只验证不删除 |

## 部署步骤

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # 填入 DB / WX_APPID / WX_SECRET / JWT_SECRET
python -m app.init_db     # 建库建表（幂等）
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
python -m pytest -q       # 部署前回归
```

生产建议 `gunicorn -k uvicorn.workers.UvicornWorker` 或 systemd 托管，前面挂 Nginx 终止 TLS。
环境变量清单与含义见开发文档 §10；`.env` 已由 `.gitignore` 排除，不得入库。

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
- **一人一团队**：`createTeam` / `joinTeam` 会拒绝已有成员记录的用户，避免 `getMyMember` 上下文随机落到别队。
- `saveEntry` 校验模板归属，并对 `status=submitted` 按模板 fields 复核必填/类型/范围/选项；草稿不校验必填。
- `getMyMember` 对停用成员直接返回明确业务错误；`getMyEntry` / `listMyEntries` 均经 `require_member` 校验。
- `entry_date` 由服务端独立校验：格式 `YYYY-MM-DD`、最多回溯 31 天、不可为未来（UTC 与本地时区跨日各放宽 1 天）。改窗口需同步小程序 `utils/date.js` 的 `BACKFILL_DAYS`。
- `listTeamEntries` 支持 `page` / `pageSize`（单页上限 1000），`ORDER BY entry_date DESC, id DESC` 保证翻页稳定；小程序 `store.js` 自动拉全，超 50 页会明确报错而非静默截断。
- `getTemplate` 对 `draft` / `archived` 模板要求管理员权限，普通成员凭 id 无法预览未发布模板。
- `publishTemplate` 在事务内 `SELECT ... FOR UPDATE` 锁团队行，冲突时把草稿 `version` 顺延到 `MAX(version)+1`，避免并发发布撞 `uk_tpl_team_id_ver`。

## 响应契约（速查）

```
POST /auth/login  {"code": "wx.login 返回的 code"}
 -> {"ok": true, "data": {"token": "...", "openid": "..."}}

POST /api  {"action": "listTemplates", "teamId": "T4K7QX"}   # 需 Bearer token
 -> {"ok": true, "data": [...]}   或  {"ok": false, "message": "..."}
```

`401` 表示登录过期，前端 `utils/http.js` 会清理本地登录态并引导重新登录。

## 字段与格式约定（回归关键）

- 主键为 24 位 hex 字符串 `id`，等价于旧云库的 `_id`，前端无需 `normalize`。
- 时间统一 ISO8601 UTC 字符串（`2026-11-09T09:08:02.000Z`），保障 `records.js` 的补录判定。
- `entry_date` / `effective_from` 为 `YYYY-MM-DD`，按字典序比较区间；`entry_date` 限于近 31 天补录窗口。
- `daily_entries` 唯一键 `(team_id, user_id, entry_date)` 保障 `saveEntry` 幂等；补录与当日提交共用该键。
- 补录沿用当前生效模板，历史版本发布时已归档；`source` 以 `backfill` 标记，不影响统计口径。

> 数据库名、logger、JWT issuer 仍使用内部标识 `jinribao`，与展示名称「报数机器人AI」无关，
> 改动会牵动已配置的 `.env`，请勿随项目改名一并修改。
