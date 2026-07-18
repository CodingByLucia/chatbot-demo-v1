from app.data.knowledge import KnowledgeSection
from app.data.repository import (
    StaticKnowledgeSource,
    get_booking_link,
    get_knowledge_source,
)

SECTIONS = [
    KnowledgeSection(id="a", title="A", content="alpha"),
    KnowledgeSection(id="b", title="B", content="beta"),
]


def test_static_source_returns_everything_and_ignores_query():
    source = StaticKnowledgeSource(SECTIONS)
    assert source.retrieve("pricing") == SECTIONS
    assert source.retrieve("") == source.retrieve("anything else")


def test_booking_link_is_the_contact_page():
    assert get_booking_link() == "https://www.cadreai.com/contact"


def test_get_knowledge_source_is_a_singleton_over_the_real_kb():
    get_knowledge_source.cache_clear()
    source = get_knowledge_source()
    assert source is get_knowledge_source()
    assert len(source.retrieve("")) > 0
