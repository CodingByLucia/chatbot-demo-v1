"""Talks to the LLM: chat completions, the fallback-marker parser, and the
grounding check that verifies every answer before it ships."""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

import structlog
from openai import APIError, OpenAI, RateLimitError

from app.config import Settings, get_settings
from app.core.prompt_builder import SectionLike, render_sections

MAX_OUTPUT_TOKENS = 500  # support answers are short; bounds the cost of every reply
VERDICT_MAX_TOKENS = 8  # the grounding check answers with a single word

_FALLBACK_MARKER = re.compile(
    r"""<fallback\s+reason=(?P<quote>["'])(?P<reason>.*?)(?P=quote)\s*/?>""",
    re.DOTALL,
)

_WORD = re.compile(r"[a-z0-9]+")

# Words too generic to identify a section: nearly every title mentions Cadre or AI,
# and question words appear in any visitor message.
_STOPWORDS = frozenset(
    "a an and or of for to in on at with the is are was be it this that "
    "what who how why when where do does can could would you your i we "
    "tell me more cadre ai".split()
)

GROUNDING_INSTRUCTIONS = (
    "You verify a support bot's draft answer against its knowledge base. "
    "Reply with exactly one word: GROUNDED if every factual claim in the answer "
    "is stated in the knowledge base, UNGROUNDED otherwise."
)

UNVERIFIED_REPLY = (
    "I'm not confident I can answer that accurately, so I'd rather put you in "
    "touch with the team directly."
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


def parse_grounding_verdict(text: str) -> bool:
    """True only when the verifier clearly answered GROUNDED — any negation
    ("UNGROUNDED", "not grounded", "isn't grounded") counts as ungrounded."""
    upper = text.upper()
    if re.search(r"\bUNGROUNDED\b|\bNOT\b|N'T\b", upper):
        return False
    return re.search(r"\bGROUNDED\b", upper) is not None


def match_section(query: str, sections: Sequence[SectionLike]) -> SectionLike | None:
    """Returns the section whose title shares the most keywords with the query,
    or None when no title keyword appears in the query at all."""
    query_words = set(_WORD.findall(query.lower())) - _STOPWORDS
    best: SectionLike | None = None
    best_score = 0
    for section in sections:
        title_words = set(_WORD.findall(section.title.lower())) - _STOPWORDS
        score = len(title_words & query_words)
        if score > best_score:
            best, best_score = section, score
    return best


class AIService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._logger = structlog.get_logger()
        self._client = (
            None  # mock mode never builds a network client
            if settings.mock_llm
            else OpenAI(api_key=settings.api_key, base_url=settings.base_url)
        )

    def get_response(
        self, messages: list[dict[str, str]], sections: Sequence[SectionLike]
    ) -> AIReply:
        """Answers from the conversation; sections are the KB the answer must be
        grounded in, and the degrade source when it is not."""
        if self._client is None:
            return self._mock_response(messages)
        content = self._complete(messages, MAX_OUTPUT_TOKENS)
        if not content.strip():
            self._logger.error("llm_empty_reply")
            raise AIUnavailableError("LLM returned an empty reply")

        result = parse_fallback(content)
        if result.fallback_reason is None and not self._is_grounded(
            result.reply, sections
        ):
            return self._degrade(messages, sections)
        self._logger.info(
            "llm_reply",
            chars=len(result.reply),
            fallback=result.fallback_reason is not None,
        )
        return result

    def _complete(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        try:
            completion = self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=messages,
                max_tokens=max_tokens,
            )
        except RateLimitError as exc:
            self._logger.warning("llm_rate_limited", error=str(exc))
            raise AIRateLimitError("LLM rate limit hit") from exc
        except APIError as exc:
            self._logger.error("llm_unavailable", error=str(exc))
            raise AIUnavailableError("LLM call failed") from exc
        return completion.choices[0].message.content or ""

    def _is_grounded(self, reply: str, sections: Sequence[SectionLike]) -> bool:
        """Second LLM call judging the reply against the KB. A failed or
        unreadable check counts as ungrounded: the reply must never ship unchecked."""
        check = [
            {"role": "system", "content": GROUNDING_INSTRUCTIONS},
            {
                "role": "user",
                "content": (
                    f"KNOWLEDGE BASE:\n{render_sections(sections)}\n\nANSWER:\n{reply}"
                ),
            },
        ]
        try:
            verdict = self._complete(check, VERDICT_MAX_TOKENS)
        except (AIRateLimitError, AIUnavailableError) as exc:
            self._logger.error("grounding_check_failed", error=str(exc))
            return False
        grounded = parse_grounding_verdict(verdict)
        if not grounded:
            self._logger.warning("ungrounded_reply", verdict=verdict.strip())
        return grounded

    def _degrade(
        self, messages: list[dict[str, str]], sections: Sequence[SectionLike]
    ) -> AIReply:
        """Replaces an unverified answer: verbatim KB text when a section matches
        the question, the fallback card when none does."""
        query = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        section = match_section(query, sections)
        if section is not None:
            self._logger.warning("ungrounded_degraded_to_kb", section=section.title)
            return AIReply(reply=section.content, fallback_reason=None)
        self._logger.warning("ungrounded_degraded_to_fallback")
        return AIReply(
            reply=UNVERIFIED_REPLY,
            fallback_reason="answer failed the grounding check",
        )

    def _mock_response(self, messages: list[dict[str, str]]) -> AIReply:
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        canned = MOCK_FALLBACK if "fallback" in last_user.lower() else MOCK_REPLY
        return parse_fallback(canned)


@lru_cache
def get_ai_service() -> AIService:
    return AIService(get_settings())
