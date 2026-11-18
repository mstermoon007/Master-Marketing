"""微信服务端接口（P5）：access_token 缓存与无限制小程序码。

约束：
- AppID/AppSecret 只在服务端环境变量；
- access_token 内存缓存，提前 300 秒刷新，刷新失败不覆盖旧值；
- 微信原始错误码不透传给客户端，统一转成可展示的业务错误。
"""
import base64
import threading
import time
from typing import Any, Dict, Optional

import requests

from .. import config
from ..handlers.common import BusinessError

_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
_QRCODE_URL = "https://api.weixin.qq.com/wxa/getwxacodeunlimit"
_SUBSCRIBE_URL = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"
_QRCODE_PAGE = "pages/login-confirm/login-confirm"
_REFRESH_AHEAD_SECONDS = 300
_SAFE_ERROR = "小程序码生成失败，请稍后重试"

_lock = threading.Lock()
_cache: Dict[str, Any] = {"value": "", "expires_at": 0.0}


def reset_cache() -> None:
    """供测试与运维手动清空缓存。"""
    with _lock:
        _cache["value"] = ""
        _cache["expires_at"] = 0.0


def get_access_token() -> str:
    now = time.time()
    if _cache["value"] and now < _cache["expires_at"] - _REFRESH_AHEAD_SECONDS:
        return _cache["value"]

    with _lock:
        # 双重检查：并发请求只刷新一次
        now = time.time()
        if _cache["value"] and now < _cache["expires_at"] - _REFRESH_AHEAD_SECONDS:
            return _cache["value"]
        if not config.WX_APPID or not config.WX_SECRET:
            raise BusinessError("服务端未配置微信 AppID/AppSecret")
        try:
            resp = requests.get(
                _TOKEN_URL,
                params={
                    "grant_type": "client_credential",
                    "appid": config.WX_APPID,
                    "secret": config.WX_SECRET,
                },
                timeout=config.WX_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            raise BusinessError(_SAFE_ERROR)

        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise BusinessError(_SAFE_ERROR)
        try:
            expires_in = int(data.get("expires_in") or 7200)
        except (TypeError, ValueError):
            expires_in = 7200
        _cache["value"] = token
        _cache["expires_at"] = time.time() + expires_in
        return token


def get_unlimited_qrcode(scene: str, page: Optional[str] = None) -> str:
    """生成小程序码，返回可直接放进 <img src> 的 PNG data URL。"""
    access_token = get_access_token()
    payload: Dict[str, Any] = {
        "scene": scene,
        "page": page or _QRCODE_PAGE,
        "check_path": False,
        "env_version": "release",
    }
    try:
        resp = requests.post(
            _QRCODE_URL,
            params={"access_token": access_token},
            json=payload,
            timeout=config.WX_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException:
        raise BusinessError(_SAFE_ERROR)

    content = resp.content or b""
    if not content or _looks_like_error(content):
        raise BusinessError(_SAFE_ERROR)
    return "data:image/png;base64," + base64.b64encode(content).decode("ascii")


def _looks_like_error(content: bytes) -> bool:
    """微信失败时返回 JSON（errcode/errmsg），成功时是 PNG 二进制。"""
    head = content[:1]
    return head in (b"{", b"<")


def send_subscribe_message(openid: str, template_id: str,
                           page: Optional[str] = None,
                           data: Optional[dict] = None) -> Dict[str, Any]:
    """发送订阅消息，统一返回 {errcode, errmsg}（errcode=0 表示成功）。

    约束：任何网络/解析异常都折叠成 errcode=-1，不把微信原始错误透传客户端；
    调用方（services.notify）据 errcode 决定 sent / skipped / failed。
    """
    try:
        access_token = get_access_token()
    except BusinessError:
        return {"errcode": -1, "errmsg": "access_token unavailable"}

    payload: Dict[str, Any] = {
        "touser": openid,
        "template_id": template_id,
        "page": page or "pages/index/index",
        "data": data or {},
    }
    try:
        resp = requests.post(
            _SUBSCRIBE_URL,
            params={"access_token": access_token},
            json=payload,
            timeout=config.WX_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
    except (requests.RequestException, ValueError):
        return {"errcode": -1, "errmsg": "request failed"}

    if not isinstance(result, dict):
        return {"errcode": -1, "errmsg": "invalid response"}
    try:
        errcode = int(result.get("errcode") or 0)
    except (TypeError, ValueError):
        errcode = -1
    return {"errcode": errcode, "errmsg": str(result.get("errmsg") or "")}
