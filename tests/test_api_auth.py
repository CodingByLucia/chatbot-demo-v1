"""Access-code gate: the auth check route and the 401 mapping on /api/v1/*."""

import structlog

from tests.conftest import HEADERS


def test_health_needs_no_access_code(api):
    client, _, _ = api
    assert client.get("/health").status_code == 200


def test_missing_access_code_is_401_with_error_shape(api):
    client, _, _ = api
    response = client.post("/api/v1/chat", json={"message": "hi"})
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_DENIED"
    assert set(body) == {"code", "message"}


def test_wrong_access_code_is_401(api):
    client, _, _ = api
    response = client.post(
        "/api/v1/chat", json={"message": "hi"}, headers={"X-Access-Code": "nope"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_DENIED"


def test_auth_check_with_valid_code_is_200(api):
    client, _, _ = api
    response = client.get("/api/v1/auth", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_check_without_code_is_401_with_error_shape(api):
    client, _, _ = api
    response = client.get("/api/v1/auth")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ACCESS_DENIED"
    assert set(body) == {"code", "message"}


def test_auth_check_with_wrong_code_is_401(api):
    client, _, _ = api
    response = client.get("/api/v1/auth", headers={"X-Access-Code": "nope"})
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_DENIED"


def test_gate_401_logs_access_denied(api):
    client, _, _ = api
    with structlog.testing.capture_logs() as logs:
        client.get("/api/v1/auth", headers={"X-Access-Code": "nope"})
    event = next(e for e in logs if e["event"] == "access_denied")
    assert event["header_present"] is True
