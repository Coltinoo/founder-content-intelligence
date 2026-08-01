"""Prompt loading.

Prompts live as editable markdown in ``prompts/`` — never as string literals
scattered through the code. ``_shared_rules.md`` is prepended to every prompt so
the anti-hallucination contract cannot be edited out of one prompt by accident.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..config import PROMPTS_DIR

SHARED_RULES_FILE = "_shared_rules.md"

PROMPT_FILES = {
    "source_extraction": "source_extraction.md",
    "claim_evidence": "claim_evidence.md",
    "theme_classification": "theme_classification.md",
    "trend_analysis": "trend_analysis.md",
    "opportunity_scoring": "opportunity_scoring.md",
    "brief_generation": "brief_generation.md",
    "voice_analysis": "voice_analysis.md",
    "linkedin_draft": "linkedin_draft.md",
    "longform_outline": "longform_outline.md",
    "engagement_recommendation": "engagement_recommendation.md",
    "factcheck_review": "factcheck_review.md",
    "meeting_notes": "meeting_notes.md",
}


class _SafeFormatter(string.Formatter):
    """``str.format`` that leaves unknown placeholders intact.

    Prompt files contain JSON schema examples full of literal braces; a plain
    ``.format()`` would explode on them.
    """

    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            return kwargs.get(key, "{" + key + "}")
        return super().get_value(key, args, kwargs)

    def parse(self, format_string):
        # Treat "{{" / "}}" normally; tolerate stray braces from JSON blocks.
        try:
            yield from super().parse(format_string)
        except ValueError:
            yield format_string, None, None, None


_FORMATTER = _SafeFormatter()


@dataclass
class Prompt:
    name: str
    body: str
    shared_rules: str

    def render(self, **values) -> str:
        """Fill placeholders. Missing keys are left visible, not silently blank."""
        safe = {k: ("" if v is None else str(v)) for k, v in values.items()}
        try:
            filled = _FORMATTER.vformat(self.body, (), safe)
        except (ValueError, KeyError, IndexError):
            filled = self.body
            for key, value in safe.items():
                filled = filled.replace("{" + key + "}", value)
        return f"{self.shared_rules}\n\n---\n\n{filled}"

    @property
    def path(self) -> Path:
        return PROMPTS_DIR / PROMPT_FILES.get(self.name, f"{self.name}.md")


@lru_cache(maxsize=1)
def _shared_rules() -> str:
    path = PROMPTS_DIR / SHARED_RULES_FILE
    if not path.exists():
        # Fail loud rather than silently dropping the integrity contract.
        raise FileNotFoundError(
            f"Missing {path}. The shared integrity rules are required for every prompt."
        )
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=32)
def load_prompt(name: str) -> Prompt:
    filename = PROMPT_FILES.get(name)
    if not filename:
        raise KeyError(f"Unknown prompt '{name}'. Known: {sorted(PROMPT_FILES)}")
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file missing: {path}")
    return Prompt(name=name, body=path.read_text(encoding="utf-8"), shared_rules=_shared_rules())


class PromptLibrary:
    """Read/write access for the Settings page."""

    @staticmethod
    def names() -> list[str]:
        return sorted(PROMPT_FILES)

    @staticmethod
    def read(name: str) -> str:
        return load_prompt(name).body

    @staticmethod
    def read_shared_rules() -> str:
        return _shared_rules()

    @staticmethod
    def write(name: str, body: str) -> None:
        filename = PROMPT_FILES.get(name)
        if not filename:
            raise KeyError(f"Unknown prompt '{name}'")
        (PROMPTS_DIR / filename).write_text(body, encoding="utf-8")
        load_prompt.cache_clear()

    @staticmethod
    def status() -> list[dict]:
        rows = []
        for name, filename in sorted(PROMPT_FILES.items()):
            path = PROMPTS_DIR / filename
            rows.append({
                "prompt": name,
                "file": f"prompts/{filename}",
                "exists": path.exists(),
                "chars": path.stat().st_size if path.exists() else 0,
            })
        return rows
