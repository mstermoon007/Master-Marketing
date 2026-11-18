"""统一错误响应：所有 HTTP 错误都返回 {ok:false, message}，前端可直接展示。"""
from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def test_unknown_route_returns_json_contract():
    resp = client.get("/not-exists")

    assert resp.status_code == 404
    assert resp.json() == {"ok": False, "message": "接口不存在"}
    # 错误响应同样经过安全中间件
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_wrong_method_returns_json_contract():
    resp = client.get("/api")

    assert resp.status_code == 405
    assert resp.json() == {"ok": False, "message": "请求方法不允许"}


def test_validation_error_returns_json_contract():
    resp = client.post("/api", json=[])

    assert resp.status_code == 422
    assert resp.json() == {"ok": False, "message": "请求参数不合法"}
