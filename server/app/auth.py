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
    if not config.JWT_SECRET:
        raise RuntimeError("JWT_SECRET 未配置")
    now = int(time.time())
    payload = {
        "sub": openid,
        "iss": JWT_ISS,
        "iat": now,
        "exp": now + config.JWT_TTL_DAYS * 24 * 3600,
    }
    if unionid:
        payload["unionid"] = unionid
    return jwt.encode(payload, config.JWT_SECRET, algorithm=JWT_ALG)


def verify_token(token: str) -> Optional[str]:
    """返回 openid；无效/过期返回 None。"""
    if not token or not config.JWT_SECRET:
        return None
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET,
            algorithms=[JWT_ALG],
            issuer=JWT_ISS,
            options={"require": ["exp", "iat", "sub"]},
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def extract_uid(authorization: Optional[str]) -> Optional[str]:
    """从 Authorization: Bearer <token> 提取身份。"""
    if not authorization or not isinstance(authorization, str):
        return None
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return verify_token(parts[1])
