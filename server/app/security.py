"""安全加固：安全响应头、请求体上限、敏感端点限流。

限流为**进程内**滑动窗口：Gunicorn 多 worker 时每进程独立计数，
只能削峰、不能当作强一致的配额；生产环境仍建议在 Nginx 加 `limit_req`。
"""
import ipaddress
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

# 单个请求体上限：业务最大的是批量模板/任务，1MB 足够；导出是响应方向不受此限制。
MAX_BODY_BYTES = 1_000_000

# path -> (次数, 窗口秒数)
RATE_LIMITS: Dict[str, Tuple[int, int]] = {
    "/auth/login": (20, 60),
    "/auth/web/ticket": (10, 60),
    "/auth/web/ticket/status": (300, 60),
}

_hits: Dict[str, Deque[float]] = defaultdict(deque)


def reset_rate_limits() -> None:
    """清空计数，仅供测试使用。"""
    _hits.clear()


def _client_key(path: str, client_ip: Optional[str]) -> str:
    return "%s|%s" % (path, client_ip or "-")


def client_ip(peer: Optional[str], real_ip: Optional[str]) -> Optional[str]:
    """取真实客户端 IP。

    只有直连方是内网/回环（Nginx、Docker 网关）时才信任 `X-Real-IP`；
    公网直连客户端伪造该头不会绕过限流。Nginx 必须用 `$remote_addr` 覆盖。
    """
    if not peer:
        return real_ip or None
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if addr.is_loopback or addr.is_private:
        return (real_ip or "").strip() or peer
    return peer


def rate_limited(path: str, client_ip: Optional[str]) -> bool:
    """命中限流返回 True；未配置限流的 path 恒为 False。"""
    rule = RATE_LIMITS.get(path)
    if not rule:
        return False
    limit, window = rule
    now = time.monotonic()
    hits = _hits[_client_key(path, client_ip)]
    while hits and now - hits[0] >= window:
        hits.popleft()
    if len(hits) >= limit:
        return True
    hits.append(now)
    if len(_hits) > 5000:
        _purge_stale(now, window)
    return False


def _purge_stale(now: float, window: int) -> None:
    """偶尔清理过期 key，避免被大量伪造 IP 撑大内存。"""
    for key in [k for k, v in _hits.items() if not v or now - v[-1] >= window]:
        _hits.pop(key, None)


def security_headers(scheme: str) -> Dict[str, str]:
    """统一响应头；HSTS 只在 HTTPS 下发送。"""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cache-Control": "no-store",
    }
    if scheme == "https":
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers
