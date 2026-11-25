"""P5 Web 扫码登录：ticket 生命周期、web/mini 令牌隔离、白名单、微信客户端。

沿用现有 monkeypatch 风格，不依赖真实 MySQL / 微信接口 / HTTP 客户端。
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import auth, config, main
from app.services import wechat


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _iso(seconds):
    moment = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


TICKET = "0123456789abcdef0123456789abcdef"


def _body(resp):
    return json.loads(resp.body)


@pytest.fixture(autouse=True)
def _secrets(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "unit-test-secret-0123456789abcdef")
    monkeypatch.setattr(config, "WEB_TOKEN_TTL_HOURS", 12)


# ---------------------------------------------------------------- 令牌隔离

def test_web_and_mini_tokens_are_mutually_exclusive():
    mini = auth.issue_token("openid-1")
    web = auth.issue_web_token("openid-1")

    assert auth.extract_uid("Bearer " + mini) == "openid-1"
    assert auth.extract_uid("Bearer " + web) is None
    assert auth.extract_claims("Bearer " + mini)["aud"] == "mini"
    claims = auth.extract_claims("Bearer " + web)
    assert claims["aud"] == "web"
    assert claims["sub"] == "openid-1"
    assert claims["exp"] - claims["iat"] == 12 * 3600


def test_legacy_token_without_aud_still_valid():
    """P5 之前签发的 30 天 token 没有 aud，升级后必须继续可用。"""
    import time

    import jwt

    now = int(time.time())
    token = jwt.encode({
        "sub": "openid-old", "iss": auth.JWT_ISS, "iat": now, "exp": now + 3600,
    }, config.JWT_SECRET, algorithm=auth.JWT_ALG)
    assert auth.extract_uid("Bearer " + token) == "openid-old"


# ---------------------------------------------------------------- /api 白名单

def test_api_rejects_web_token_for_mini_actions(monkeypatch):
    monkeypatch.setattr(main.db, "connection", lambda: _Conn())
    monkeypatch.setattr(main, "dispatch", lambda conn, uid, body: {"called": body["action"]})
    token = auth.issue_web_token("openid-1")

    for action in ("saveEntry", "getMyEntry", "listMyEntries", "confirmWebLogin"):
        resp = main.api({"action": action}, "Bearer " + token)
        body = _body(resp)
        assert body["ok"] is False
        assert "无权" in body["message"]


def test_api_allows_web_whitelisted_action(monkeypatch):
    called = {}
    monkeypatch.setattr(main.db, "connection", lambda: _Conn())
    monkeypatch.setattr(
        main, "dispatch",
        lambda conn, uid, body: called.update(uid=uid, action=body["action"]) or {"spaces": []},
    )
    token = auth.issue_web_token("openid-1")
    body = _body(main.api({"action": "listMyWorkspaces"}, "Bearer " + token))
    assert body["ok"] is True
    assert called == {"uid": "openid-1", "action": "listMyWorkspaces"}


def test_api_filters_web_workspaces_to_managed_spaces(monkeypatch):
    monkeypatch.setattr(main.db, "connection", lambda: _Conn())
    monkeypatch.setattr(
        main, "dispatch",
        lambda conn, uid, body: [
            {"workspace": {"id": "W1"}}, {"workspace": {"id": "W2"}},
        ],
    )
    monkeypatch.setattr(
        main.web, "managed_workspaces",
        lambda conn, uid: [{"id": "W2"}],
    )
    token = auth.issue_web_token("openid-1")
    body = _body(main.api({"action": "listMyWorkspaces"}, "Bearer " + token))
    assert body["ok"] is True
    assert [item["workspace"]["id"] for item in body["data"]] == ["W2"]


def test_api_keeps_mini_token_behavior(monkeypatch):
    called = {}
    monkeypatch.setattr(main.db, "connection", lambda: _Conn())
    monkeypatch.setattr(main, "dispatch", lambda conn, uid, body: called.setdefault("action", body["action"]))
    token = auth.issue_token("openid-1")
    body = _body(main.api({"action": "saveEntry"}, "Bearer " + token))
    assert body["ok"] is True
    assert called["action"] == "saveEntry"


def test_api_unknown_audience_rejected(monkeypatch):
    import time

    import jwt

    now = int(time.time())
    token = jwt.encode({
        "sub": "openid-1", "iss": auth.JWT_ISS, "aud": "other",
        "iat": now, "exp": now + 3600,
    }, config.JWT_SECRET, algorithm=auth.JWT_ALG)
    resp = main.api({"action": "listMyWorkspaces"}, "Bearer " + token)
    assert resp.status_code == 401


# ---------------------------------------------------------------- ticket 生命周期

def test_create_ticket_returns_qrcode(monkeypatch):
    inserted = {}
    cleaned = []
    monkeypatch.setattr(main.db, "connection", lambda: _Conn())
    monkeypatch.setattr(main.db, "execute", lambda conn, sql, args: cleaned.append(args))
    monkeypatch.setattr(main.db, "insert", lambda conn, table, data: inserted.update(data) or "id-1")
    monkeypatch.setattr(main.wechat, "get_unlimited_qrcode", lambda scene: "data:image/png;base64,AAA")

    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    body = _body(main.web_ticket(request))

    assert body["ok"] is True
    data = body["data"]
    assert len(data["ticket"]) == 32
    assert data["qrcode"].startswith("data:image/png;base64,")
    assert data["expiresIn"] == main.TICKET_TTL_SECONDS
    assert inserted["status"] == "pending"
    assert inserted["client_ip"] == "127.0.0.1"
    assert inserted["expires_at"] > inserted["created_at"]
    assert cleaned  # 顺带清理 24 小时前的历史票据


def test_create_ticket_hides_wechat_error(monkeypatch):
    from app.handlers import BusinessError

    monkeypatch.setattr(main.db, "connection", lambda: _Conn())
    monkeypatch.setattr(main.db, "execute", lambda *a, **k: None)
    monkeypatch.setattr(main.db, "insert", lambda *a, **k: "id-1")

    def boom(scene):
        raise BusinessError("小程序码生成失败，请稍后重试")

    monkeypatch.setattr(main.wechat, "get_unlimited_qrcode", boom)
    body = _body(main.web_ticket(SimpleNamespace(client=None)))
    assert body["ok"] is False
    assert body["message"] == "小程序码生成失败，请稍后重试"


def _patch_ticket_row(monkeypatch, row):
    updates = []
    monkeypatch.setattr(main.db, "connection", lambda: _Conn())
    monkeypatch.setattr(main.db, "one", lambda conn, sql, args=None: row)
    monkeypatch.setattr(main.db, "row_to_dict", lambda raw, table: dict(raw))
    monkeypatch.setattr(
        main.db, "update",
        lambda conn, table, row_id, data: updates.append(data),
    )
    monkeypatch.setattr(main, "_workspaces_by_ids", lambda conn, ids: [
        {"id": i, "workspace_code": "W" + i, "name": "空间" + i} for i in ids
    ])
    return updates


def test_confirmed_ticket_issues_web_token_once(monkeypatch):
    row = {
        "id": "t1", "ticket": TICKET, "user_id": "openid-1", "status": "confirmed",
        "workspace_ids": ["W1", "W2"], "expires_at": _iso(120),
    }
    updates = _patch_ticket_row(monkeypatch, row)

    body = _body(main.web_ticket_status({"ticket": TICKET}))
    assert body["ok"] is True
    data = body["data"]
    assert data["status"] == "confirmed"
    assert [w["id"] for w in data["workspaces"]] == ["W1", "W2"]
    assert auth.extract_claims("Bearer " + data["token"])["aud"] == "web"
    assert updates[-1]["status"] == "consumed"

    # 第二次轮询：ticket 已被消费，不再发放 token
    row["status"] = "consumed"
    body = _body(main.web_ticket_status({"ticket": TICKET}))
    assert body["data"] == {"status": "consumed"}
    assert "token" not in body["data"]


def test_pending_ticket_expires_on_poll(monkeypatch):
    row = {
        "id": "t1", "ticket": TICKET, "user_id": None, "status": "pending",
        "workspace_ids": None, "expires_at": _iso(-1),
    }
    updates = _patch_ticket_row(monkeypatch, row)
    body = _body(main.web_ticket_status({"ticket": TICKET}))
    assert body["data"]["status"] == "expired"
    assert updates[-1]["status"] == "expired"


def test_invalid_ticket_format_returns_expired_without_db(monkeypatch):
    monkeypatch.setattr(main.db, "one", lambda *a, **k: pytest.fail("不应查库"))
    body = _body(main.web_ticket_status({"ticket": "not-a-ticket"}))
    assert body["data"]["status"] == "expired"


def test_web_refresh_requires_web_token():
    web = auth.issue_web_token("openid-1")
    body = _body(main.web_refresh("Bearer " + web))
    assert body["ok"] is True
    assert auth.extract_claims("Bearer " + body["data"]["token"])["aud"] == "web"

    mini = auth.issue_token("openid-1")
    resp = main.web_refresh("Bearer " + mini)
    assert resp.status_code == 401


# ---------------------------------------------------------------- 微信客户端

class _Resp:
    def __init__(self, data=None, content=b""):
        self._data = data
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def _reset_wechat_cache():
    wechat.reset_cache()
    yield
    wechat.reset_cache()


def test_access_token_is_cached(monkeypatch):
    monkeypatch.setattr(config, "WX_APPID", "wx-test")
    monkeypatch.setattr(config, "WX_SECRET", "secret")
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _Resp({"access_token": "tok-1", "expires_in": 7200})

    monkeypatch.setattr(wechat.requests, "get", fake_get)
    assert wechat.get_access_token() == "tok-1"
    assert wechat.get_access_token() == "tok-1"
    assert len(calls) == 1


def test_qrcode_returns_data_url(monkeypatch):
    monkeypatch.setattr(wechat, "get_access_token", lambda: "tok-1")
    png = b"\x89PNG\r\n\x1a\nfake"
    monkeypatch.setattr(wechat.requests, "post", lambda *a, **k: _Resp(content=png))
    url = wechat.get_unlimited_qrcode(TICKET)
    assert url.startswith("data:image/png;base64,")


def test_qrcode_error_payload_is_hidden(monkeypatch):
    from app.handlers import BusinessError

    monkeypatch.setattr(wechat, "get_access_token", lambda: "tok-1")
    error = json.dumps({"errcode": 40001, "errmsg": "invalid credential"}).encode()
    monkeypatch.setattr(wechat.requests, "post", lambda *a, **k: _Resp(content=error))
    with pytest.raises(BusinessError) as exc:
        wechat.get_unlimited_qrcode(TICKET)
    assert "40001" not in str(exc.value)
    assert "invalid credential" not in str(exc.value)
