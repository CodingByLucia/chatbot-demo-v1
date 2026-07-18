"""Shared fixtures for the route tests: test env, fake AI client, TestClient."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.ai_service import AIReply, get_ai_service
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
