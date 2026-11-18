---
description: 报数机器人AI · 项目开发约定（自有服务端架构）
globs: *
alwaysApply: true
inclusion: always
---

# 报数机器人AI · 开发约定

本项目**已从微信云开发（CloudBase）完整迁移到自有服务器**，唯一合法的后端形态：

| 层 | 实现 |
|---|---|
| 服务端 | Python 3 + FastAPI，代码在 `server/` |
| 数据库 | MySQL 8，建表脚本 `server/sql/schema.sql` |
| 登录 | `wx.login` code → `POST /auth/login` → 服务端 code2session → 签发 JWT |
| 传输 | 小程序 `wx.request`，统一 `POST /api` RPC：`utils/http.js` → `utils/store.js` |
| 身份 | 服务端验 JWT，取 `sub`（openid），**不信任客户端传的任何身份字段** |

## 强制约束

1. **禁止**新增或引用任何云开发能力：`wx.cloud.*`、`wx-server-sdk`、云函数、云数据库、云托管、CloudBase CLI / MCP / Skill。
2. `utils/store.js` 的 52 个 action 与 `server/app/handlers/` 的 `HANDLERS` 必须成对注册；新增 action 同步更新 `server/tests/test_contract.py`。
3. 权限校验一律在服务端（`require_member` / `require_manager`），前端只负责隐藏入口。
4. `saveEntry` 必须按模板 `fields` 在服务端复核；`entry_date` 受 31 天回溯窗口约束，不接受未来日期。
5. `daily_entries(team_id, user_id, entry_date)` 唯一键保障幂等 upsert；`normalize` 的 `_id → id` 映射与 UTC 时间格式不得变更。
6. 模板状态只能经 `publishTemplate` 变为 `published`；草稿预览限管理员。
7. 数据分析一律用确定性程序实现：禁止引入任何大模型 SDK、模型 API、Prompt 工程或对话式问答；报告只拼接已计算结果。
8. 指标计算只允许一份实现（`server/app/services/metrics.py`），应提交口径只允许一份实现（`services/expected.py`），看板/报表/导出/分析不得各写一套。
9. 分析引擎只读业务数据：写操作白名单仅 `analysis_*`；不得写 `daily_entries` / `form_templates` / `members` / `teams`。
10. 阶段编号口径：产品演进用 `P0–P8`，工程质量轮次用 `G0–G2`，二者不混用；详见 `docs/DEVELOPMENT.md` §0。

## 文档索引

- `docs/DEVELOPMENT.md` — 完整开发文档（唯一事实源）：接口契约、52 个 action 权限表、数据表、登录鉴权、R1–R15 风险、部署与回归清单、阶段口径
- `server/README.md` — 服务端部署运维专题
- `README.md` — 项目总览与快速开始

## 关于历史脚手架

`rules/`、`codebuddy-plugin/`、`.cloudbase/`、`cloudfunctions/`、`cloudbaserc.json`、`utils/cloud*.js` 均为早期 CloudBase 脚手架残留，**已废弃，不得作为开发依据**。执行 `bash server/finish.sh` 只做验证（8 项），**不删除任何文件**。
