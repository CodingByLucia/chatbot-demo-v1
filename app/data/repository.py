"""Read access to the knowledge base: section retrieval and the booking link."""

from abc import ABC, abstractmethod
from functools import lru_cache

import structlog

from app.data.knowledge import KnowledgeSection, load_knowledge

BOOKING_LINK = "https://www.cadreai.com/contact"


class KnowledgeSource(ABC):
    @abstractmethod
    def retrieve(self, query: str) -> list[KnowledgeSection]: ...


class StaticKnowledgeSource(KnowledgeSource):
    """Returns every section; ignores the query."""

    def __init__(self, sections: list[KnowledgeSection]) -> None:
        self._sections = sections

    def retrieve(self, query: str) -> list[KnowledgeSection]:
        return list(self._sections)


def get_booking_link() -> str:
    return BOOKING_LINK


@lru_cache
def get_knowledge_source() -> KnowledgeSource:
    sections = load_knowledge()
    structlog.get_logger().info("kb_loaded", sections=len(sections))
    return StaticKnowledgeSource(sections)
