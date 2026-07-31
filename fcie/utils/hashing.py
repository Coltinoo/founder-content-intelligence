"""Content hashing and text fingerprints used for deduplication."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
# Boilerplate lines that appear on every page of a marketing site and would
# otherwise make unrelated pages hash-similar.
_BOILERPLATE = re.compile(
    r"(cookie policy|accept all cookies|privacy policy|terms of service|"
    r"all rights reserved|subscribe to our newsletter|skip to (main )?content)",
    flags=re.IGNORECASE,
)


def normalize_for_hash(text: str | None) -> str:
    """Aggressively normalise text so trivial formatting differences collapse."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-").replace(" ", " ")
    text = _BOILERPLATE.sub(" ", text)
    text = text.lower()
    text = _PUNCT.sub(" ", text)
    text = _WHITESPACE.sub(" ", text)
    return text.strip()


def content_hash(text: str | None) -> str:
    """SHA-256 of normalised text. Stable across runs and platforms."""
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()


def short_hash(text: str | None, length: int = 12) -> str:
    return content_hash(text)[:length]


def shingles(text: str | None, size: int = 5) -> set[str]:
    """Word n-grams, used for near-duplicate (Jaccard) comparison."""
    words = normalize_for_hash(text).split()
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def text_similarity(a: str | None, b: str | None, shingle_size: int = 5) -> float:
    """0.0-1.0 near-duplicate score between two documents."""
    return jaccard(shingles(a, shingle_size), shingles(b, shingle_size))


def slugify(text: str, max_length: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_length].strip("-") or "untitled"
