"""Talks to the LLM: chat completions plus the fallback-marker parser."""

import re
from dataclasses import dataclass
from functools import lru_cache

import structlog
from openai import APIError, OpenAI, RateLimitError

from app.config import Settings, get_settings

MAX_OUTPUT_TOKENS = 500  # support answers are short; bounds the cost of every reply

_FALLBACK_MARKER = re.compile(
    r"""<fallback\s+reason=(?P<quote>["'])(?P<reason>.*?)(?P=quote)\s*/?>""",
    re.DOTALL,
)

MOCK_REPLY = (
    "Canned reply (MOCK_LLM=true, no credits spent): Cadre AI is an AI strategy and "
    "implementation consultancy. Ask me about services, industries, or booking a call."
)
MOCK_FALLBACK = 'Sorry, I can\'t help with that one. <fallback reason="mock fallback"/>'


class AIUnavailableError(Exception):
    """The LLM endpoint failed or is unreachable."""


class AIRateLimitError(Exception):
    """The LLM endpoint rejected the call because of rate limiting."""


@dataclass(frozen=True)
class AIReply:
    reply: str
    fallback_reason: str | None  # None means a normal answer


def parse_fallback(text: str) -> AIReply:
    """Finds the <fallback reason=""/> marker, strips it, returns reply + reason."""
    match = _FALLBACK_MARKER.search(text)
    if match is None:
        return AIReply(reply=text.strip(), fallback_reason=None)
    reply = _FALLBACK_MARKER.sub("", text).strip()
    reason = match.group("reason").strip() or "unspecified"
    return AIReply(reply=reply, fallback_reason=reason)


class AIService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = structlog.get_logger()
        self._client = (
            None  # mock mode never builds a network client
            if settings.mock_llm
            else OpenAI(api_key=settings.api_key, base_url=settings.base_url)
        )

    def get_response(self, messages: list[dict[str, str]]) -> AIReply:
        if self._client is None:
            return self._mock_response(messages)
        try:
            completion = self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=messages,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except RateLimitError as exc:
            self._logger.warning("llm_rate_limited", error=str(exc))
            raise AIRateLimitError("LLM rate limit hit") from exc
        except APIError as exc:
            self._logger.error("llm_unavailable", error=str(exc))
            raise AIUnavailableError("LLM call failed") from exc

        content = completion.choices[0].message.content or ""
        if not content.strip():
            self._logger.error("llm_empty_reply")
            raise AIUnavailableError("LLM returned an empty reply")

        result = parse_fallback(content)
        self._logger.info(
            "llm_reply",
            chars=len(result.reply),
            fallback=result.fallback_reason is not None,
        )
        return result

    def _mock_response(self, messages: list[dict[str, str]]) -> AIReply:
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        canned = MOCK_FALLBACK if "fallback" in last_user.lower() else MOCK_REPLY
        return parse_fallback(canned)


@lru_cache
def get_ai_service() -> AIService:
    return AIService(get_settings())
