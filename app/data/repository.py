"""Read access to the knowledge base: section retrieval and the booking link."""

import re
from abc import ABC, abstractmethod
from functools import lru_cache

import structlog

from app.data.knowledge import KnowledgeSection, load_knowledge

_URL = re.compile(r"https?://[^\s\"')]+")


class KnowledgeSource(ABC):
    @abstractmethod
    def retrieve(self, query: str) -> list[KnowledgeSection]: ...


class StaticKnowledgeSource(KnowledgeSource):
    """Returns every section; ignores the query."""

    def __init__(self, sections: list[KnowledgeSection]) -> None:
        self._sections = sections

    def retrieve(self, query: str) -> list[KnowledgeSection]:
        return list(self._sections)


@lru_cache
def get_booking_link() -> str:
    """The contact-page URL: the first URL in the knowledge-base section whose
    title mentions contact. Raises when no such section or URL exists, so a KB
    edit that drops the contact data is caught at startup."""
    for section in get_knowledge_source().retrieve("contact"):
        if "contact" in section.title.lower():
            match = _URL.search(section.content)
            if match:
                return match.group()
    raise ValueError("knowledge base has no contact section with a URL")


@lru_cache
def get_knowledge_source() -> KnowledgeSource:
    sections = load_knowledge()
    structlog.get_logger().info("kb_loaded", sections=len(sections))
    return StaticKnowledgeSource(sections)
