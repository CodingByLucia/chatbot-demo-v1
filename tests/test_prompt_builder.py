from dataclasses import dataclass
from pathlib import Path

import pytest

import app.core.prompt_builder as prompt_builder
from app.core.prompt_builder import (
    BOUNDARIES,
    FALLBACK_PROTOCOL,
    PERSONA,
    build_system_prompt,
)


@dataclass
class StubSection:  # any object with title+content fits, no app/data needed
    title: str
    content: str


SECTIONS = [
    StubSection("AI Strategy", "45-day AI Transformation Intensive."),
    StubSection("Booking & Contact", "Book a call: https://www.cadreai.com/contact"),
]


def test_prompt_contains_every_kb_section():
    prompt = build_system_prompt(SECTIONS)
    for section in SECTIONS:
        assert section.title in prompt
        assert section.content in prompt


def test_prompt_contains_persona_boundaries_and_fallback_protocol():
    prompt = build_system_prompt(SECTIONS)
    assert PERSONA in prompt
    assert BOUNDARIES in prompt
    assert FALLBACK_PROTOCOL in prompt
    assert '<fallback reason=' in prompt


def test_prompt_orders_persona_kb_boundaries_fallback():
    prompt = build_system_prompt(SECTIONS)
    positions = [
        prompt.index(PERSONA),
        prompt.index(SECTIONS[0].content),
        prompt.index(BOUNDARIES),
        prompt.index(FALLBACK_PROTOCOL),
    ]
    assert positions == sorted(positions)


def test_empty_sections_rejected():
    with pytest.raises(ValueError):
        build_system_prompt([])


def test_prompt_builder_never_imports_app_data():
    source = Path(prompt_builder.__file__).read_text(encoding="utf-8")
    assert "from app.data" not in source
    assert "import app.data" not in source
