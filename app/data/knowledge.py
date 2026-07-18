"""Parses docs/cadre-kb.md into KnowledgeSection objects."""

import re
from dataclasses import dataclass
from pathlib import Path

KB_PATH = Path(__file__).resolve().parents[2] / "docs" / "cadre-kb.md"

_HEADING = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_SEPARATOR = re.compile(r"^-+$")  # `## --------` visual separator, not a section


@dataclass(frozen=True)
class KnowledgeSection:
    id: str
    title: str
    content: str


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def load_knowledge(path: Path = KB_PATH) -> list[KnowledgeSection]:
    if not path.is_file():
        raise FileNotFoundError(f"KB file not found: {path}")

    blocks: list[tuple[str, list[str]]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = _HEADING.match(line)
        if match:
            blocks.append((match.group("title"), []))
        elif blocks:
            blocks[-1][1].append(line)

    sections = []
    for title, lines in blocks:
        if _SEPARATOR.fullmatch(title):
            continue
        content = "\n".join(lines).strip()
        if not content:
            raise ValueError(f"KB section '{title}' is empty: {path}")
        sections.append(KnowledgeSection(id=_slug(title), title=title, content=content))

    if not sections:
        raise ValueError(f"KB file has no sections: {path}")
    return sections
