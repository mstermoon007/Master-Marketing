"""报数机器人AI · 自有服务端（FastAPI + MySQL 8）。

分层：config -> db -> auth -> handlers -> api -> main
对外契约与旧云函数保持一致：{ ok: true, data } | { ok: false, message }
"""
