import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.ai_service import (
    AIRateLimitError,
    AIReply,
    AIUnavailableError,
    get_ai_service,
)
from app.main import create_app
from app.sessions.manager import SessionManager, get_session_manager
from app.sessions.store import InMemorySessionStore

ACCESS_CODE = "letmein"
HEADERS = {"X-Access-Code": ACCESS_CODE}

ENV = {
    "API_KEY": "test-key",
    "BASE_URL": "http://localhost:9",
    "LLM_MODEL": "test-model",
    "ACCESS_CODE": ACCESS_CODE,
    "MOCK_LLM": "false",
}


class FakeAIService:
    """Stands in for AIService: returns a scripted reply or raises a scripted error."""

    def __init__(self):
        self.calls = []
        self.sections = []
        self.result = AIReply(reply="Canned answer.", fallback_reason=None)
        self.error = None

    def get_response(self, messages, sections):
        self.calls.append(messages)
        self.sections.append(sections)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def api(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    app = create_app()
    fake_ai = FakeAIService()
    manager = SessionManager(InMemorySessionStore(ttl_seconds=3600))
    app.dependency_overrides[get_ai_service] = lambda: fake_ai
    app.dependency_overrides[get_session_manager] = lambda: manager
    yield TestClient(app), fake_ai, manager
    get_settings.cache_clear()


# --- access code gate ---

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


# --- chat flow ---

def test_start_chat_returns_reply_and_chat_id(api):
    client, _, _ = api
    response = client.post(
        "/api/v1/chat", json={"message": "What does Cadre do?"}, headers=HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Canned answer."
    assert body["fallback"] is None
    assert body["chat_id"]


def test_model_gets_system_prompt_with_kb_then_history(api):
    client, fake_ai, _ = api
    client.post("/api/v1/chat", json={"message": "What does Cadre do?"}, headers=HEADERS)
    messages = fake_ai.calls[0]
    assert messages[0]["role"] == "system"
    assert "KNOWLEDGE BASE" in messages[0]["content"]
    assert "BOUNDARIES" in messages[0]["content"]
    assert messages[1:] == [{"role": "user", "content": "What does Cadre do?"}]


def test_continue_chat_appends_to_history(api):
    client, _, _ = api
    chat_id = client.post(
        "/api/v1/chat", json={"message": "hi"}, headers=HEADERS
    ).json()["chat_id"]
    response = client.post(
        f"/api/v1/chat/{chat_id}/messages", json={"message": "more"}, headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json()["chat_id"] == chat_id

    history = client.get(f"/api/v1/chat/{chat_id}", headers=HEADERS).json()
    roles = [m["role"] for m in history["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_only_last_ten_messages_reach_the_model(api):
    client, fake_ai, manager = api
    session = manager.create_session()
    for i in range(14):
        role = "user" if i % 2 == 0 else "assistant"
        manager.add_message(session, role, f"old {i}")
    client.post(
        f"/api/v1/chat/{session.id}/messages", json={"message": "newest"}, headers=HEADERS
    )
    messages = fake_ai.calls[0]
    assert messages[0]["role"] == "system"
    assert len(messages) == 1 + 10
    assert messages[-1] == {"role": "user", "content": "newest"}


def test_fallback_reply_carries_reason_and_booking_link(api):
    client, fake_ai, _ = api
    fake_ai.result = AIReply(reply="Sorry, can't help.", fallback_reason="not in kb")
    body = client.post(
        "/api/v1/chat", json={"message": "off topic"}, headers=HEADERS
    ).json()
    assert body["fallback"] == {
        "reason": "not in kb",
        "booking_url": "https://www.cadreai.com/contact",
    }


def test_kb_sections_reach_the_ai_service(api):
    client, fake_ai, _ = api
    client.post("/api/v1/chat", json={"message": "hi"}, headers=HEADERS)
    sections = fake_ai.sections[0]
    assert sections
    assert all(s.title and s.content for s in sections)


def test_history_carries_fallback_so_the_card_survives_reload(api):
    client, fake_ai, _ = api
    fake_ai.result = AIReply(reply="Sorry, can't help.", fallback_reason="not in kb")
    chat_id = client.post(
        "/api/v1/chat", json={"message": "off topic"}, headers=HEADERS
    ).json()["chat_id"]

    history = client.get(f"/api/v1/chat/{chat_id}", headers=HEADERS).json()
    user_message, assistant_message = history["messages"]
    assert user_message["fallback"] is None
    assert assistant_message["fallback"] == {
        "reason": "not in kb",
        "booking_url": "https://www.cadreai.com/contact",
    }


# --- contact capture ---

def test_contact_is_stored_on_the_session(api):
    client, _, manager = api
    chat_id = client.post(
        "/api/v1/chat", json={"message": "hi"}, headers=HEADERS
    ).json()["chat_id"]
    response = client.post(
        f"/api/v1/chat/{chat_id}/contact",
        json={"name": "Ada Lovelace", "email": "ada@example.com"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    contact = manager.get_session(chat_id).contact
    assert (contact.name, contact.email) == ("Ada Lovelace", "ada@example.com")


def test_contact_for_unknown_chat_is_404(api):
    client, _, _ = api
    response = client.post(
        "/api/v1/chat/nope/contact",
        json={"name": "Ada", "email": "ada@example.com"},
        headers=HEADERS,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "UNKNOWN_CHAT"


def test_contact_with_invalid_email_is_422(api):
    client, _, _ = api
    chat_id = client.post(
        "/api/v1/chat", json={"message": "hi"}, headers=HEADERS
    ).json()["chat_id"]
    response = client.post(
        f"/api/v1/chat/{chat_id}/contact",
        json={"name": "Ada", "email": "not-an-email"},
        headers=HEADERS,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INVALID_REQUEST"
    assert set(body) == {"code", "message"}


def test_contact_requires_access_code(api):
    client, _, _ = api
    response = client.post(
        "/api/v1/chat/any/contact", json={"name": "Ada", "email": "ada@example.com"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "ACCESS_DENIED"


# --- error mapping ---

def test_unknown_chat_is_404(api):
    client, _, _ = api
    for response in (
        client.post("/api/v1/chat/nope/messages", json={"message": "hi"}, headers=HEADERS),
        client.get("/api/v1/chat/nope", headers=HEADERS),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "UNKNOWN_CHAT"


def test_ai_unavailable_maps_to_502(api):
    client, fake_ai, _ = api
    fake_ai.error = AIUnavailableError("down")
    response = client.post("/api/v1/chat", json={"message": "hi"}, headers=HEADERS)
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "AI_UNAVAILABLE"
    assert set(body) == {"code", "message"}


def test_rate_limit_maps_to_429(api):
    client, fake_ai, _ = api
    fake_ai.error = AIRateLimitError("slow down")
    response = client.post("/api/v1/chat", json={"message": "hi"}, headers=HEADERS)
    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"


def test_failed_ai_call_leaves_session_history_unchanged(api):
    client, fake_ai, _ = api
    chat_id = client.post(
        "/api/v1/chat", json={"message": "hi"}, headers=HEADERS
    ).json()["chat_id"]
    fake_ai.error = AIUnavailableError("down")
    response = client.post(
        f"/api/v1/chat/{chat_id}/messages", json={"message": "again"}, headers=HEADERS
    )
    assert response.status_code == 502

    fake_ai.error = None
    history = client.get(f"/api/v1/chat/{chat_id}", headers=HEADERS).json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]


def test_unmatched_path_keeps_error_shape(api):
    client, _, _ = api
    response = client.get("/api/v1/nope", headers=HEADERS)
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert set(body) == {"code", "message"}


def test_unexpected_exception_keeps_error_shape(api):
    client, fake_ai, _ = api
    fake_ai.error = ValueError("boom")
    quiet = TestClient(client.app, raise_server_exceptions=False)
    response = quiet.post("/api/v1/chat", json={"message": "hi"}, headers=HEADERS)
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert set(body) == {"code", "message"}


def test_blank_message_is_422_invalid_request(api):
    client, _, _ = api
    response = client.post("/api/v1/chat", json={"message": "   "}, headers=HEADERS)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INVALID_REQUEST"
    assert set(body) == {"code", "message"}
