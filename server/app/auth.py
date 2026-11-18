"""微信登录与自有会话令牌。

替代原云函数的 cloud.getWXContext().OPENID：
  wx.login -> code -> 服务端 code2session(AppID+AppSecret) -> openid
          -> 签发 JWT -> 之后每次 /api 请求由服务端验签注入身份

安全约束（对应方案 R1）：
- AppSecret、JWT 签名密钥只在服务端环境变量中，永不进小程序包。
- 客户端传来的 uid/openid/user_id 一律不信任，身份只取 JWT 的 sub。
"""
import time
from typing import Optional

import jwt
import requests

from . import config

WX_CODE2SESSION = "https://api.weixin.qq.com/sns/jscode2session"
JWT_ALG = "HS256"
JWT_ISS = "jinribao-selfhosted"


class AuthError(Exception):
    """可安全展示给客户端的认证错误。"""


def code2session(code: str) -> dict:
    if not code or not isinstance(code, str) or len(code) > 256:
        raise AuthError("微信登录凭证无效，请重试")
    if not config.WX_APPID or not config.WX_SECRET:
        raise AuthError("服务端未配置微信 AppID/AppSecret")
    try:
        resp = requests.get(
            WX_CODE2SESSION,
            params={
                "appid": config.WX_APPID,
                "secret": config.WX_SECRET,
                "js_code": code,
                "grant_type": "authorization_code",
            },
            timeout=config.WX_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        raise AuthError("微信登录服务暂时不可用，请稍后重试")

    if data.get("errcode"):
        # 不把微信原始错误透传给客户端，避免泄露配置细节
        raise AuthError("微信登录失败，请重新进入小程序再试")
    openid = data.get("openid")
    if not openid:
        raise AuthError("微信登录失败，未获取到身份信息")
    return {"openid": openid, "unionid": data.get("unionid")}


def issue_token(openid: str, unionid: Optional[str] = None) -> str:
    """小程序令牌：aud=mini，30 天。"""
    if not config.JWT_SECRET:
        raise RuntimeError("JWT_SECRET 未配置")
    now = int(time.time())
    payload = {
        "sub": openid,
        "iss": JWT_ISS,
        "aud": "mini",
        "iat": now,
        "exp": now + config.JWT_TTL_DAYS * 24 * 3600,
    }
    if unionid:
        payload["unionid"] = unionid
    return jwt.encode(payload, config.JWT_SECRET, algorithm=JWT_ALG)


def issue_web_token(openid: str) -> str:
    """Web 管理后台令牌：aud=web，默认 12 小时。"""
    if not config.JWT_SECRET:
        raise RuntimeError("JWT_SECRET 未配置")
    now = int(time.time())
    payload = {
        "sub": openid,
        "iss": JWT_ISS,
        "aud": "web",
        "iat": now,
        "exp": now + config.WEB_TOKEN_TTL_HOURS * 3600,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> Optional[dict]:
    """验签并返回完整 claims；无效/过期返回 None。"""
    if not token or not config.JWT_SECRET:
        return None
    try:
        return jwt.decode(
            token,
            config.JWT_SECRET,
            algorithms=[JWT_ALG],
            issuer=JWT_ISS,
            options={
                "require": ["exp", "iat", "sub"],
                # aud 由 verify_token / 调用方显式判定，避免 web 与 mini 互斥校验被默认规则覆盖
                "verify_aud": False,
            },
        )
    except jwt.PyJWTError:
        return None


def verify_token(token: str) -> Optional[str]:
    """返回小程序身份 openid；Web 令牌（aud=web）在此一律视为无效。"""
    payload = decode_token(token)
    if not payload:
        return None
    # 兼容 P5 之前签发、没有 aud 的旧令牌
    if payload.get("aud") not in (None, "mini"):
        return None
    return payload.get("sub")


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not isinstance(authorization, str):
        return None
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def extract_claims(authorization: Optional[str]) -> Optional[dict]:
    """从 Authorization: Bearer <token> 提取完整 claims（含 aud）。"""
    token = _bearer(authorization)
    if not token:
        return None
    return decode_token(token)


def extract_uid(authorization: Optional[str]) -> Optional[str]:
    """从 Authorization: Bearer <token> 提取小程序身份。"""
    token = _bearer(authorization)
    if not token:
        return None
    return verify_token(token)
