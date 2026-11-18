"""安全加固：响应头、请求体上限、限流、令牌最小权限。"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app import auth, config, main, security

client = TestClient(main.app)
SHORT_SECRET = "unit-test-secret-0123456789abcdef"


@pytest.fixture(autouse=True)
def _reset_limits():
    security.reset_rate_limits()
    yield
    security.reset_rate_limits()


def _token(**claims) -> str:
    now = int(time.time())
    payload = {"iss": auth.JWT_ISS, "iat": now, "exp": now + 60, **claims}
    return jwt.encode(payload, SHORT_SECRET, algorithm=auth.JWT_ALG)


def test_health_sets_security_headers():
    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["cache-control"] == "no-store"
    # 普通 HTTP 不透出 HSTS
    assert "strict-transport-security" not in resp.headers


def test_hsts_only_when_https():
    resp = client.get("/health", headers={"X-Forwarded-Proto": "https"})

    assert resp.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )


def test_rejects_oversized_body():
    resp = client.post(
        "/api",
        content=b"x" * (security.MAX_BODY_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )

    assert resp.status_code == 413
    assert resp.json() == {"ok": False, "message": "请求体过大"}


def test_login_rate_limited_with_cors_headers():
    limit = security.RATE_LIMITS["/auth/login"][0]
    origin = "http://localhost:5173"

    for _ in range(limit):
        assert client.post("/auth/login", json={"code": ""}).status_code == 401

    resp = client.post("/auth/login", json={"code": ""}, headers={"Origin": origin})

    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"
    # 限流响应仍带跨域头，前端才能读到文案
    assert resp.headers["access-control-allow-origin"] == origin


def test_rate_limit_is_per_ip_and_path():
    limit = security.RATE_LIMITS["/auth/web/ticket"][0]

    assert all(not security.rate_limited("/auth/web/ticket", "1.1.1.1")
               for _ in range(limit))
    assert security.rate_limited("/auth/web/ticket", "1.1.1.1") is True
    # 换 IP 不受影响；未配置限流的路径不限流
    assert security.rate_limited("/auth/web/ticket", "2.2.2.2") is False
    assert security.rate_limited("/health", "1.1.1.1") is False


def test_web_refresh_rejects_token_without_sub(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", SHORT_SECRET)

    resp = client.post(
        "/auth/web/refresh",
        headers={"Authorization": "Bearer " + _token(aud="web")},
    )

    assert resp.status_code == 401


def test_export_rejects_unknown_audience(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", SHORT_SECRET)

    resp = client.post(
        "/api/export/entries",
        json={},
        headers={"Authorization": "Bearer " + _token(sub="u1", aud="other")},
    )

    assert resp.status_code == 401


def test_client_ip_only_trusts_forwarded_header_from_private_peer():
    # 内网/回环反代（Nginx、Docker 网关）才信任 X-Real-IP
    assert security.client_ip("127.0.0.1", "203.0.113.9") == "203.0.113.9"
    assert security.client_ip("172.17.0.1", "203.0.113.9") == "203.0.113.9"
    # 公网直连伪造 X-Real-IP 无效
    assert security.client_ip("8.8.8.8", "203.0.113.9") == "8.8.8.8"
    assert security.client_ip(None, "203.0.113.9") == "203.0.113.9"
    assert security.client_ip("testclient", "x") == "testclient"


def test_startup_rejects_short_jwt_secret(monkeypatch):
    monkeypatch.setenv("WX_APPID", "appid")
    monkeypatch.setenv("WX_SECRET", "secret")
    monkeypatch.setenv("JWT_SECRET", "too-short")

    with pytest.raises(RuntimeError, match="JWT_SECRET 至少 32 个字符"):
        config.require_runtime_secrets()
