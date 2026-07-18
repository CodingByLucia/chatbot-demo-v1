from types import SimpleNamespace

import httpx
import openai
import pytest
import structlog

from app.config import Settings
from app.core.ai_service import (
    MAX_OUTPUT_TOKENS,
    MOCK_FALLBACK,
    UNVERIFIED_REPLY,
    VERDICT_MAX_TOKENS,
    AIRateLimitError,
    AIReply,
    AIService,
    AIUnavailableError,
    match_section,
    parse_fallback,
    parse_grounding_verdict,
    recommends_contact,
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
    """Returns (or raises) one scripted outcome per create() call, in order."""

    def __init__(self, outcomes):
        self.calls = []
        self._outcomes = list(outcomes)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        message = SimpleNamespace(content=outcome)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=5),
        )


def make_service(*outcomes):
    service = AIService(make_settings())
    fake = FakeCompletions(outcomes)
    service._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return service, fake


def sdk_error(status):
    request = httpx.Request("POST", "http://localhost:9/chat/completions")
    response = httpx.Response(status, request=request)
    cls = openai.RateLimitError if status == 429 else openai.APIStatusError
    return cls("boom", response=response, body=None)


SECTIONS = [
    SimpleNamespace(title="AI Strategy", content="45-day AI Transformation Intensive."),
    SimpleNamespace(
        title="Industries", content="Healthcare, insurance, financial services."
    ),
]

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


# --- grounding verdict parser ---

def test_verdict_grounded_in_any_case():
    assert parse_grounding_verdict("GROUNDED") is True
    assert parse_grounding_verdict("grounded.") is True


def test_verdict_ungrounded_wins_even_though_it_contains_grounded():
    assert parse_grounding_verdict("UNGROUNDED") is False
    assert parse_grounding_verdict("The answer is ungrounded") is False


def test_verdict_negated_grounded_counts_as_ungrounded():
    assert parse_grounding_verdict("NOT GROUNDED") is False
    assert parse_grounding_verdict("The answer isn't grounded") is False


def test_verdict_anything_unclear_counts_as_ungrounded():
    assert parse_grounding_verdict("") is False
    assert parse_grounding_verdict("maybe?") is False


def test_verdict_grounded_with_extra_words_still_passes():
    assert parse_grounding_verdict("GROUNDED - every claim checks out") is True


# --- contact recommendation detector ---

def test_recommends_contact_on_email():
    assert recommends_contact("Reach the team at team@example.com for access.")


def test_recommends_contact_on_phone_number():
    assert recommends_contact("Call (555) 123-4567 to get started.")
    assert recommends_contact("Call 555-123-4567 to get started.")


def test_recommends_contact_on_contact_page_url():
    assert recommends_contact("Fill the form at https://example.com/contact today.")


def test_recommends_contact_on_booking_wording():
    assert recommends_contact("You can book a call with a strategist.")
    assert recommends_contact("Booking a call is the fastest way.")


def test_recommends_contact_false_on_plain_answer():
    assert not recommends_contact("Cadre helps with AI strategy and engineering.")


# --- KB section matcher ---

def test_match_section_finds_title_keyword():
    section = match_section("Tell me about your industries", SECTIONS)
    assert section is SECTIONS[1]


def test_match_section_best_overlap_wins():
    sections = [
        SimpleNamespace(title="AI Strategy", content="s"),
        SimpleNamespace(title="AI Strategy Engineering", content="e"),
    ]
    assert match_section("strategy engineering work", sections) is sections[1]


def test_match_section_ignores_generic_words():
    # "Cadre" and "AI" appear in most titles; alone they identify nothing.
    assert match_section("What is Cadre AI?", SECTIONS) is None


def test_match_section_no_overlap_returns_none():
    assert match_section("What's the weather today?", SECTIONS) is None


# --- get_response over a fake client ---

def test_grounded_answer_ships_and_caps_tokens():
    service, fake = make_service("Cadre helps with AI strategy.", "GROUNDED")
    result = service.get_response(MESSAGES, SECTIONS)
    assert result == AIReply(reply="Cadre helps with AI strategy.", fallback_reason=None)
    answer_call, verdict_call = fake.calls
    assert answer_call["model"] == "test-model"
    assert answer_call["messages"] == MESSAGES
    assert answer_call["max_tokens"] == MAX_OUTPUT_TOKENS == 500
    assert verdict_call["max_tokens"] == VERDICT_MAX_TOKENS


def test_grounding_call_sees_kb_and_answer():
    service, fake = make_service("Cadre helps with AI strategy.", "GROUNDED")
    service.get_response(MESSAGES, SECTIONS)
    check_prompt = fake.calls[1]["messages"][1]["content"]
    assert "45-day AI Transformation Intensive." in check_prompt
    assert "Cadre helps with AI strategy." in check_prompt


def test_grounded_reply_with_contact_details_is_flagged():
    service, _ = make_service("Email team@example.com to get set up.", "GROUNDED")
    result = service.get_response(MESSAGES, SECTIONS)
    assert result.fallback_reason is None
    assert result.contact_recommended is True


def test_fallback_reply_skips_the_grounding_check():
    service, fake = make_service('Cannot say. <fallback reason="missing"/>')
    result = service.get_response(MESSAGES, SECTIONS)
    assert result.fallback_reason == "missing"
    assert "<fallback" not in result.reply
    assert len(fake.calls) == 1


def test_ungrounded_degrades_to_matching_kb_section_verbatim():
    service, _ = make_service("Invented facts.", "UNGROUNDED")
    messages = [{"role": "user", "content": "Tell me about your industries"}]
    result = service.get_response(messages, SECTIONS)
    assert result == AIReply(
        reply="Healthcare, insurance, financial services.", fallback_reason=None
    )


def test_ungrounded_with_no_matching_section_falls_back():
    service, _ = make_service("Invented facts.", "UNGROUNDED")
    result = service.get_response(MESSAGES, SECTIONS)
    assert result.reply == UNVERIFIED_REPLY
    assert result.fallback_reason == "answer failed the grounding check"


def test_unclear_verdict_degrades_too():
    service, _ = make_service("Invented facts.", "no idea")
    result = service.get_response(MESSAGES, SECTIONS)
    assert result.fallback_reason == "answer failed the grounding check"


def test_failed_grounding_check_degrades_instead_of_raising():
    service, _ = make_service("Some answer.", sdk_error(500))
    result = service.get_response(MESSAGES, SECTIONS)
    assert result.reply == UNVERIFIED_REPLY
    assert result.fallback_reason is not None


def test_rate_limited_grounding_check_degrades_instead_of_raising():
    service, _ = make_service("Some answer.", sdk_error(429))
    result = service.get_response(MESSAGES, SECTIONS)
    assert result.fallback_reason is not None


def test_rate_limit_on_answer_maps_to_ai_rate_limit_error():
    service, _ = make_service(sdk_error(429))
    with pytest.raises(AIRateLimitError):
        service.get_response(MESSAGES, SECTIONS)


def test_api_status_error_on_answer_maps_to_ai_unavailable_error():
    service, _ = make_service(sdk_error(500))
    with pytest.raises(AIUnavailableError):
        service.get_response(MESSAGES, SECTIONS)


def test_empty_completion_raises_ai_unavailable_error():
    service, _ = make_service("")
    with pytest.raises(AIUnavailableError):
        service.get_response(MESSAGES, SECTIONS)


# --- observability ---

def test_llm_reply_logs_duration_and_token_usage():
    service, _ = make_service("An answer.", "GROUNDED")
    with structlog.testing.capture_logs() as logs:
        service.get_response(MESSAGES, SECTIONS)
    event = next(e for e in logs if e["event"] == "llm_reply")
    assert event["duration_ms"] >= 0
    assert event["prompt_tokens"] == 7
    assert event["completion_tokens"] == 5


def test_passed_grounding_check_is_logged():
    service, _ = make_service("An answer.", "GROUNDED")
    with structlog.testing.capture_logs() as logs:
        service.get_response(MESSAGES, SECTIONS)
    event = next(e for e in logs if e["event"] == "grounding_check")
    assert event["grounded"] is True


# --- mock circuit ---

def test_mock_mode_builds_no_network_client():
    service = AIService(make_settings(mock_llm=True))
    assert service._client is None


def test_mock_mode_returns_canned_reply():
    service = AIService(make_settings(mock_llm=True))
    result = service.get_response(MESSAGES, SECTIONS)
    assert result.fallback_reason is None
    assert result.reply


def test_mock_mode_canned_fallback_on_keyword():
    service = AIService(make_settings(mock_llm=True))
    result = service.get_response(
        [{"role": "user", "content": "trigger a fallback"}], SECTIONS
    )
    assert result.fallback_reason == "mock fallback"
    assert result == parse_fallback(MOCK_FALLBACK)
