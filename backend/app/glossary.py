"""Local glossary lookup for definition questions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

GLOSSARY_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "glossary.md"


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    aliases: tuple[str, ...]
    body: str


def _parse() -> list[GlossaryEntry]:
    if not GLOSSARY_PATH.exists():
        return []
    text = GLOSSARY_PATH.read_text(encoding="utf-8")
    entries: list[GlossaryEntry] = []
    for block in re.split(r"(?m)^##\s+", text)[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        term = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        aliases = [term]
        for line in lines[1:]:
            if line.startswith("**别名**") or line.startswith("**全称**"):
                value = line.split(":", 1)[-1]
                aliases.extend(part.strip() for part in value.split(",") if part.strip())
        entries.append(GlossaryEntry(term=term, aliases=tuple(dict.fromkeys(aliases)), body=body))
    return entries


_ENTRIES = _parse()


def lookup(question: str) -> GlossaryEntry | None:
    lowered = question.lower()
    candidates = []
    for entry in _ENTRIES:
        for alias in entry.aliases:
            if alias.lower() in lowered:
                candidates.append((len(alias), entry))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]
