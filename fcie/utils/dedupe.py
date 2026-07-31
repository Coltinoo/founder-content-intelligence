"""Four-layer duplicate detection.

An article surfaced by six different search queries must produce exactly one
``sources`` row, while every query that found it is preserved in
``metadata_json['discovered_by_queries']``.

Layers, cheapest first:
    1. canonical URL equality
    2. exact content hash
    3. title similarity (token-set ratio) within a plausible window
    4. semantic / near-duplicate similarity via word-shingle Jaccard
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from rapidfuzz import fuzz

from .hashing import content_hash, text_similarity
from .urls import normalize_url

TITLE_SIMILARITY_THRESHOLD = 92.0   # 0-100
BODY_SIMILARITY_THRESHOLD = 0.72    # 0-1 Jaccard over 5-word shingles
SHORT_DOC_WORDS = 120               # below this, body similarity is unreliable


@dataclass
class DuplicateVerdict:
    is_duplicate: bool
    matched_id: int | None = None
    method: str | None = None       # canonical_url | content_hash | title | body
    score: float | None = None
    detail: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.is_duplicate


@dataclass
class CandidateRecord:
    """Minimal projection of an existing source row, for comparison."""

    id: int
    canonical_url: str
    content_hash: str | None = None
    title: str | None = None
    cleaned_text: str | None = None


def _normalize_title(title: str | None) -> str:
    if not title:
        return ""
    t = title.lower().strip()
    # Strip trailing site names: "Headline | Publication" / "Headline - Publication"
    for sep in (" | ", " — ", " – ", " - "):
        if sep in t:
            head = t.split(sep)[0]
            if len(head.split()) >= 4:
                t = head
                break
    return " ".join(t.split())


def title_similarity(a: str | None, b: str | None) -> float:
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0
    if len(na.split()) < 4 or len(nb.split()) < 4:
        # Very short titles ("About", "Pricing") collide constantly on
        # marketing sites — never treat them as a duplicate signal.
        return 0.0
    return float(fuzz.token_set_ratio(na, nb))


def find_duplicate(
    canonical_url: str,
    text: str | None,
    title: str | None,
    candidates: Iterable[CandidateRecord],
    *,
    text_hash: str | None = None,
    title_threshold: float = TITLE_SIMILARITY_THRESHOLD,
    body_threshold: float = BODY_SIMILARITY_THRESHOLD,
) -> DuplicateVerdict:
    """Compare one incoming document against existing rows."""
    target_url = normalize_url(canonical_url)
    target_hash = text_hash or (content_hash(text) if text else None)
    candidates = list(candidates)

    # 1. canonical URL
    for cand in candidates:
        if cand.canonical_url and normalize_url(cand.canonical_url) == target_url:
            return DuplicateVerdict(True, cand.id, "canonical_url", 1.0,
                                    "Identical canonical URL")

    # 2. exact content hash
    if target_hash:
        for cand in candidates:
            if cand.content_hash and cand.content_hash == target_hash:
                return DuplicateVerdict(True, cand.id, "content_hash", 1.0,
                                        "Byte-identical normalised content")

    # 3. title similarity
    best_title: tuple[float, CandidateRecord | None] = (0.0, None)
    for cand in candidates:
        score = title_similarity(title, cand.title)
        if score > best_title[0]:
            best_title = (score, cand)
    if best_title[0] >= title_threshold and best_title[1] is not None:
        return DuplicateVerdict(True, best_title[1].id, "title", best_title[0] / 100.0,
                                f"Title match {best_title[0]:.0f}%")

    # 4. body near-duplicate (syndicated reprints, mirrored press releases)
    if text and len(text.split()) >= SHORT_DOC_WORDS:
        best_body: tuple[float, CandidateRecord | None] = (0.0, None)
        for cand in candidates:
            if not cand.cleaned_text or len(cand.cleaned_text.split()) < SHORT_DOC_WORDS:
                continue
            score = text_similarity(text, cand.cleaned_text)
            if score > best_body[0]:
                best_body = (score, cand)
        if best_body[0] >= body_threshold and best_body[1] is not None:
            return DuplicateVerdict(True, best_body[1].id, "body", best_body[0],
                                    f"Body overlap {best_body[0]:.0%}")

    return DuplicateVerdict(False)


def merge_discovery_metadata(existing: dict, new_query: str | None,
                             new_source_type: str | None = None,
                             new_url: str | None = None) -> dict:
    """Record that an already-stored source was rediscovered another way.

    We keep every query that surfaced it — that repetition is itself signal.
    """
    meta = dict(existing or {})
    queries = list(meta.get("discovered_by_queries", []))
    if new_query and new_query not in queries:
        queries.append(new_query)
    meta["discovered_by_queries"] = queries

    channels = list(meta.get("discovered_by_channels", []))
    if new_source_type and new_source_type not in channels:
        channels.append(new_source_type)
    meta["discovered_by_channels"] = channels

    alt = list(meta.get("alternate_urls", []))
    if new_url:
        n = normalize_url(new_url)
        if n and n not in alt:
            alt.append(n)
    meta["alternate_urls"] = alt
    meta["rediscovery_count"] = int(meta.get("rediscovery_count", 0)) + 1
    return meta


def dedupe_batch(records: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """Deduplicate a freshly discovered batch against *itself*.

    Returns ``(unique, duplicates)``. Each duplicate carries ``_duplicate_of``
    pointing at the index of the record it collided with.
    """
    unique: list[dict] = []
    duplicates: list[dict] = []
    seen_urls: dict[str, int] = {}
    seen_hashes: dict[str, int] = {}

    for record in records:
        url = normalize_url(record.get("canonical_url") or record.get("source_url", ""))
        text = record.get("cleaned_text") or record.get("raw_text") or ""
        h = content_hash(text) if text else None
        title = record.get("title")

        if url and url in seen_urls:
            record["_duplicate_of"] = seen_urls[url]
            record["_duplicate_method"] = "canonical_url"
            duplicates.append(record)
            continue
        if h and h in seen_hashes:
            record["_duplicate_of"] = seen_hashes[h]
            record["_duplicate_method"] = "content_hash"
            duplicates.append(record)
            continue

        collided = False
        for idx, kept in enumerate(unique):
            if title_similarity(title, kept.get("title")) >= TITLE_SIMILARITY_THRESHOLD:
                record["_duplicate_of"] = idx
                record["_duplicate_method"] = "title"
                duplicates.append(record)
                collided = True
                break
        if collided:
            continue

        position = len(unique)
        if url:
            seen_urls[url] = position
        if h:
            seen_hashes[h] = position
        unique.append(record)

    return unique, duplicates
