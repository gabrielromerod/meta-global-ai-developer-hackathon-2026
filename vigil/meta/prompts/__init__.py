"""Versioned prompt templates for Spark, Wonder and Glimmer (FR-009, FR-013, FR-014, FR-021).

Each ``<name>.md`` starts with a header line
``<!-- vigil-prompt name=<name> version=<n> fr=<FR ids> -->``. Bump the version whenever
the text changes. The prompt text is part of every request body, so any change is a cache
miss rather than a silent mix of old and new answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent
_HEADER = re.compile(r"^<!--\s*vigil-prompt\s+(?P<attrs>.*?)\s*-->$")

PROMPTS = ("appearance_notes", "story", "rule_compile", "triage")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    fr: str
    text: str

    @property
    def tag(self) -> str:
        return f"{self.name}@v{self.version}"


@lru_cache
def load_prompt(name: str) -> Prompt:
    if name not in PROMPTS:
        raise KeyError(f"unknown prompt {name!r}; known: {PROMPTS}")
    raw = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    first, _, rest = raw.partition("\n")
    m = _HEADER.match(first.strip())
    if not m:
        raise ValueError(f"prompt {name!r} has no vigil-prompt header line")
    attrs = dict(a.split("=", 1) for a in m.group("attrs").split() if "=" in a)
    if attrs.get("name") != name or "version" not in attrs:
        raise ValueError(f"prompt {name!r} header must give name={name} and a version")
    return Prompt(name=name, version=attrs["version"], fr=attrs.get("fr", ""), text=rest.strip())
