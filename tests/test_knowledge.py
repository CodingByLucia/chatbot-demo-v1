import pytest

from app.data.knowledge import KB_PATH, load_knowledge


def write_kb(tmp_path, text):
    path = tmp_path / "kb.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_sections_with_slug_ids(tmp_path):
    path = write_kb(tmp_path, "## About Cadre\nWho we are.\n\n## Booking & Contact\nBook here.\n")
    sections = load_knowledge(path)
    assert [(s.id, s.title, s.content) for s in sections] == [
        ("about-cadre", "About Cadre", "Who we are."),
        ("booking-contact", "Booking & Contact", "Book here."),
    ]


def test_skips_dashes_separator_heading(tmp_path):
    path = write_kb(tmp_path, "## First\ncontent\n## --------\n\n## Second\nmore\n")
    assert [s.title for s in load_knowledge(path)] == ["First", "Second"]


def test_missing_file_fails_fast(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_knowledge(tmp_path / "nope.md")


def test_empty_section_fails_fast(tmp_path):
    path = write_kb(tmp_path, "## Full\ncontent\n\n## Empty\n\n")
    with pytest.raises(ValueError, match="Empty"):
        load_knowledge(path)


def test_file_without_sections_fails_fast(tmp_path):
    path = write_kb(tmp_path, "just prose, no headings\n")
    with pytest.raises(ValueError, match="no sections"):
        load_knowledge(path)


def test_real_kb_loads_clean():
    sections = load_knowledge(KB_PATH)
    titles = [s.title for s in sections]
    assert "Booking & Contact" in titles
    assert "MANUALLY SOURCED INFO (do not edit)" in titles
    assert all(s.content for s in sections)
