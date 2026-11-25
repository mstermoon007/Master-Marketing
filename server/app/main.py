"""FastAPI 应用：登录端点 + Web 扫码登录 + 统一业务 API 分发。

对外契约与旧云函数一致，前端 store.js 的 callApi 无需感知后端已更换：
  POST /auth/login  { code }                 -> { ok, data:{ token, openid } }
  POST /api         { action, ...payload }   -> { ok, data } | { ok:false, message }
所有 /api 请求必须带 Authorization: Bearer <JWT>。

P5 新增：
  POST /auth/web/ticket          -> 生成扫码票据 + 小程序码
  POST /auth/web/ticket/status   -> 轮询状态，confirmed 时一次性发放 aud=web 令牌
  POST /auth/web/refresh         -> 续期 Web 令牌
  POST /api/export/entries       -> 导出 Excel（小程序或 Web 令牌均可）
"""
import logging
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, config, db, security
from .handlers import MINI_ONLY_ACTIONS, WEB_ACTIONS, BusinessError, dispatch, web
from .services import scheduler, wechat

logger = logging.getLogger("jinribao")

APP_VERSION = "2.0.0"
TICKET_TTL_SECONDS = 300
_TICKET_RE = re.compile(r"^[0-9a-f]{32}$")
_web_origins = [config.WEB_ORIGIN, "http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.require_runtime_secrets()
    # P6：应用内调度；多 worker 重复触发由 notification_logs 唯一键去重。
    # 调度是增强能力，启动失败只记日志，不能拖垮主服务。
    try:
        scheduler.start()
    except Exception:
        logger.exception("scheduler start failed")
    yield
    scheduler.shutdown()


app = FastAPI(
    title="报数机器人AI API",
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


_HTTP_ERROR_TEXT = {
    404: "接口不存在",
    405: "请求方法不允许",
    413: "请求体过大",
    429: "操作过于频繁，请稍后再试",
}


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """统一错误响应体，避免前端拿到 {"detail": ...} 无法展示。"""
    message = _HTTP_ERROR_TEXT.get(exc.status_code, str(exc.detail or "请求失败"))
    return JSONResponse(
        {"ok": False, "message": message},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse({"ok": False, "message": "请求参数不合法"}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, _exc: Exception) -> JSONResponse:
    logger.exception("unhandled error: %s %s", request.method, request.url.path)
    return JSONResponse({"ok": False, "message": "服务异常，请稍后重试"}, status_code=500)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "service": "jinribao", "version": APP_VERSION}


def _json(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status)


@app.middleware("http")
async def secure_http(request: Request, call_next):
    """安全响应头 + 请求体上限 + 敏感端点限流。

    先注册本中间件、再注册 CORS，使 CORS 处于最外层：
    被限流/413 提前返回的响应也能带上跨域头，前端才能读到错误文案。
    """
    peer = request.client.host if request.client else None
    if security.rate_limited(
        request.url.path,
        security.client_ip(peer, request.headers.get("x-real-ip")),
    ):
        return JSONResponse(
            {"ok": False, "message": "操作过于频繁，请稍后再试"},
            status_code=429,
            headers={"Retry-After": "60"},
        )

    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > security.MAX_BODY_BYTES:
        return JSONResponse({"ok": False, "message": "请求体过大"}, status_code=413)

    response = await call_next(request)
    scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme or "")
    for name, value in security.security_headers(scheme.split(",")[0].strip().lower()).items():
        response.headers[name] = value
    return response


# 小程序 wx.request 不触发 CORS；此处只放行管理后台域名与本机开发端口。
app.add_middleware(
    CORSMiddleware,
    allow_origins=_web_origins,
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _iso_in(seconds: int) -> str:
    moment = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _workspaces_by_ids(conn, ids):
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    rows = db.query(
        conn,
        "SELECT id, workspace_code, name FROM `workspaces` WHERE id IN (%s) "
        "ORDER BY created_at ASC, id ASC" % placeholders,
        tuple(ids),
    )
    return [{"id": r.get("id"), "workspace_code": r.get("workspace_code"),
             "name": r.get("name")} for r in rows]


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


# ---------------------------------------------------------------------------
# Web 扫码登录
# ---------------------------------------------------------------------------
@app.post("/auth/web/ticket")
def web_ticket(request: Request) -> JSONResponse:
    ticket = secrets.token_hex(16)
    try:
        with db.connection() as conn:
            # 顺手清理 24 小时前的历史票据，避免表无限增长
            db.execute(conn, "DELETE FROM `web_login_tickets` WHERE created_at < %s",
                       (_iso_in(-24 * 3600),))
            db.insert(conn, "web_login_tickets", {
                "ticket": ticket,
                "user_id": None,
                "status": "pending",
                "workspace_ids": None,
                "client_ip": request.client.host if request.client else None,
                "created_at": db.now_iso(),
                "expires_at": _iso_in(TICKET_TTL_SECONDS),
                "confirmed_at": None,
                "consumed_at": None,
            })
        qrcode = wechat.get_unlimited_qrcode(ticket)
        return _json({
            "ok": True,
            "data": {"ticket": ticket, "qrcode": qrcode,
                     "expiresIn": TICKET_TTL_SECONDS},
        })
    except BusinessError as e:
        return _json({"ok": False, "message": str(e)})
    except Exception:
        logger.exception("web ticket failed")
        return _json({"ok": False, "message": "登录服务异常，请稍后重试"}, status=500)


@app.post("/auth/web/ticket/status")
def web_ticket_status(body: Dict[str, Any]) -> JSONResponse:
    ticket = str(body.get("ticket") or "").strip()
    if not _TICKET_RE.fullmatch(ticket):
        return _json({"ok": True, "data": {"status": "expired"}})
    try:
        with db.connection() as conn:
            row = db.row_to_dict(db.one(
                conn,
                "SELECT * FROM `web_login_tickets` WHERE ticket = %s LIMIT 1 FOR UPDATE",
                (ticket,),
            ), "web_login_tickets")
            if not row:
                return _json({"ok": True, "data": {"status": "expired"}})

            status = row.get("status") or "pending"
            now = db.now_iso()
            if status == "pending" and (row.get("expires_at") or "") <= now:
                db.update(conn, "web_login_tickets", row["id"], {"status": "expired"})
                status = "expired"
            elif status == "confirmed":
                db.update(conn, "web_login_tickets", row["id"],
                          {"status": "consumed", "consumed_at": now})
                token = auth.issue_web_token(row["user_id"])
                spaces = _workspaces_by_ids(conn, row.get("workspace_ids") or [])
                return _json({"ok": True, "data": {
                    "status": "confirmed",
                    "token": token,
                    "expiresIn": config.WEB_TOKEN_TTL_HOURS * 3600,
                    "workspaces": spaces,
                }})

            return _json({"ok": True, "data": {"status": status}})
    except Exception:
        logger.exception("web ticket status failed")
        return _json({"ok": False, "message": "登录状态查询失败，请稍后重试"}, status=500)


@app.post("/auth/web/refresh")
def web_refresh(authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    claims = auth.extract_claims(authorization)
    uid = claims.get("sub") if claims else None
    if not claims or claims.get("aud") != "web" or not uid:
        return _json({"ok": False, "message": "登录已过期，请重新扫码"}, status=401)
    token = auth.issue_web_token(uid)
    return _json({"ok": True, "data": {
        "token": token,
        "expiresIn": config.WEB_TOKEN_TTL_HOURS * 3600,
    }})


# ---------------------------------------------------------------------------
# 统一业务入口
# ---------------------------------------------------------------------------
@app.post("/api")
def api(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None),
) -> JSONResponse:
    """统一业务入口。"""
    claims = auth.extract_claims(authorization)
    if not claims:
        # 401 供前端 http.js 拦截并触发重新登录
        return _json({"ok": False, "message": "登录已过期，请重新登录"}, status=401)

    audience = claims.get("aud") or "mini"
    if audience not in ("mini", "web"):
        return _json({"ok": False, "message": "登录凭证无效，请重新登录"}, status=401)

    action = str(body.get("action") or "")
    if audience == "web" and (action in MINI_ONLY_ACTIONS or action not in WEB_ACTIONS):
        return _json({"ok": False, "message": "Web 端无权调用该操作"})

    uid = claims.get("sub")
    if not uid:
        return _json({"ok": False, "message": "登录凭证无效，请重新登录"}, status=401)
    try:
        with db.connection() as conn:
            data = dispatch(conn, uid, body)
            if audience == "web" and action == "listMyWorkspaces" and isinstance(data, list):
                allowed_ids = {ws["id"] for ws in web.managed_workspaces(conn, uid)}
                data = [
                    item for item in data
                    if (item.get("workspace") or {}).get("id") in allowed_ids
                ]
        return _json({"ok": True, "data": data})
    except BusinessError as e:
        return _json({"ok": False, "message": str(e)})
    except Exception:
        logger.exception("api action failed: %s", action)
        return _json({"ok": False, "message": "请求失败，请重试"})


# ---------------------------------------------------------------------------
# Excel 导出（P5）
# ---------------------------------------------------------------------------
@app.post("/api/export/entries")
def export_entries(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None),
) -> Any:
    """导出团队日报；权限与 listTeamEntries 完全一致。"""
    claims = auth.extract_claims(authorization)
    uid = claims.get("sub") if claims else None
    if not claims or not uid:
        return _json({"ok": False, "message": "登录已过期，请重新登录"}, status=401)
    if claims.get("aud") not in (None, "mini", "web"):
        return _json({"ok": False, "message": "登录凭证无效，请重新登录"}, status=401)

    from .services import export as export_service

    try:
        with db.connection() as conn:
            stream, filename = export_service.build_entries_export(
                conn, uid, body)
        return StreamingResponse(
            stream,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
        )
    except BusinessError as e:
        return _json({"ok": False, "message": str(e)})
    except Exception:
        logger.exception("export entries failed")
        return _json({"ok": False, "message": "导出失败，请稍后重试"}, status=500)
