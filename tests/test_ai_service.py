from types import SimpleNamespace

import httpx
import openai
import pytest

from app.config import Settings
from app.core.ai_service import (
    MAX_OUTPUT_TOKENS,
    MOCK_FALLBACK,
    AIRateLimitError,
    AIReply,
    AIService,
    AIUnavailableError,
    parse_fallback,
)


def make_settings(**overrides):
    values = dict(
        api_key="test-key",
        base_url="http://localhost:9",
        llm_model="test-model",
        access_code="letmein",
        mock_llm=False,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


class FakeCompletions:
    def __init__(self, content=None, error=None):
        self.calls = []
        self._content = content
        self._error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def make_service(content=None, error=None):
    service = AIService(make_settings())
    fake = FakeCompletions(content=content, error=error)
    service._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return service, fake


def sdk_error(status):
    request = httpx.Request("POST", "http://localhost:9/chat/completions")
    response = httpx.Response(status, request=request)
    cls = openai.RateLimitError if status == 429 else openai.APIStatusError
    return cls("boom", response=response, body=None)


MESSAGES = [{"role": "user", "content": "What does Cadre do?"}]


# --- fallback marker parser ---

def test_parse_fallback_plain_answer_has_no_reason():
    assert parse_fallback("Cadre does AI strategy.") == AIReply(
        reply="Cadre does AI strategy.", fallback_reason=None
    )


def test_parse_fallback_strips_marker_and_returns_reason():
    result = parse_fallback('Sorry, no idea. <fallback reason="not in kb"/>')
    assert result.reply == "Sorry, no idea."
    assert result.fallback_reason == "not in kb"


def test_parse_fallback_tolerates_single_quotes_and_spacing():
    result = parse_fallback("Hmm. <fallback reason='off topic' />")
    assert result.reply == "Hmm."
    assert result.fallback_reason == "off topic"


def test_parse_fallback_empty_reason_still_falls_back():
    result = parse_fallback('<fallback reason=""/>')
    assert result.fallback_reason == "unspecified"
    assert result.reply == ""


# --- get_response over a fake client ---

def test_get_response_returns_parsed_reply_and_caps_tokens():
    service, fake = make_service(content="Cadre helps with AI strategy.")
    result = service.get_response(MESSAGES)
    assert result == AIReply(reply="Cadre helps with AI strategy.", fallback_reason=None)
    call = fake.calls[0]
    assert call["model"] == "test-model"
    assert call["messages"] == MESSAGES
    assert call["max_tokens"] == MAX_OUTPUT_TOKENS == 500


def test_get_response_detects_fallback_marker():
    service, _ = make_service(content='Cannot say. <fallback reason="missing"/>')
    result = service.get_response(MESSAGES)
    assert result.fallback_reason == "missing"
    assert "<fallback" not in result.reply


def test_rate_limit_maps_to_ai_rate_limit_error():
    service, _ = make_service(error=sdk_error(429))
    with pytest.raises(AIRateLimitError):
        service.get_response(MESSAGES)


def test_api_status_error_maps_to_ai_unavailable_error():
    service, _ = make_service(error=sdk_error(500))
    with pytest.raises(AIUnavailableError):
        service.get_response(MESSAGES)


def test_empty_completion_raises_ai_unavailable_error():
    service, _ = make_service(content="")
    with pytest.raises(AIUnavailableError):
        service.get_response(MESSAGES)


# --- mock circuit ---

def test_mock_mode_builds_no_network_client():
    service = AIService(make_settings(mock_llm=True))
    assert service._client is None


def test_mock_mode_returns_canned_reply():
    service = AIService(make_settings(mock_llm=True))
    result = service.get_response(MESSAGES)
    assert result.fallback_reason is None
    assert result.reply


def test_mock_mode_canned_fallback_on_keyword():
    service = AIService(make_settings(mock_llm=True))
    result = service.get_response([{"role": "user", "content": "trigger a fallback"}])
    assert result.fallback_reason == "mock fallback"
    assert result == parse_fallback(MOCK_FALLBACK)
