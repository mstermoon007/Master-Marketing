"""FastAPI 应用：登录端点 + 统一业务 API 分发。

对外契约与旧云函数一致，前端 store.js 的 callApi 无需感知后端已更换：
  POST /auth/login  { code }                 -> { ok, data:{ token, openid } }
  POST /api         { action, ...payload }   -> { ok, data } | { ok:false, message }
所有 /api 请求必须带 Authorization: Bearer <JWT>。
"""
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import auth, config, db
from .handlers import BusinessError, dispatch

logger = logging.getLogger("jinribao")
app = FastAPI(title="报数机器人AI API", version="2.0.0", docs_url=None, redoc_url=None)

# 小程序 wx.request 不触发 CORS，此配置仅为将来管理后台 Web 端预留。
# 生产环境应把 allow_origins 收紧为实际管理端域名。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
def on_startup() -> None:
    config.require_runtime_secrets()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "jinribao", "version": "2.0.0"}


def _json(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status)


@app.post("/auth/login")
def login(body: Dict[str, Any]) -> JSONResponse:
    """wx.login 的 code 换自有会话令牌。"""
    try:
        identity = auth.code2session(str(body.get("code") or ""))
        openid = identity["openid"]
        token = auth.issue_token(openid, identity.get("unionid"))
        # 团队上下文统一由 getMyMember/getTeam 在 loadContext 里取；
        # 登录端点不再返回未被使用的团队标记字段（避免两处口径不一致）。
        return _json({
            "ok": True,
            "data": {
                "token": token,
                "openid": openid,
            },
        })
    except auth.AuthError as e:
        return _json({"ok": False, "message": str(e)}, status=401)
    except Exception:
        logger.exception("login failed")
        return _json({"ok": False, "message": "登录服务异常，请稍后重试"}, status=500)


@app.post("/api")
def api(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """统一业务入口。"""
    uid = auth.extract_uid(authorization)
    if not uid:
        # 401 供前端 http.js 拦截并触发重新登录
        return _json({"ok": False, "message": "登录已过期，请重新登录"}, status=401)

    try:
        with db.connection() as conn:
            data = dispatch(conn, uid, body)
        return _json({"ok": True, "data": data})
    except BusinessError as e:
        return _json({"ok": False, "message": str(e)})
    except Exception:
        logger.exception("api action failed: %s", body.get("action"))
        return _json({"ok": False, "message": "请求失败，请重试"})
