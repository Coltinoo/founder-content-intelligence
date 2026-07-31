"""Manual source entry.

The lawful route for anything that cannot be collected automatically: public
LinkedIn post text a human has copied, interview transcripts, meeting notes,
customer insights, and press quotes.

Nothing here fetches a page. The human supplies the text and the canonical URL.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..utils.text import clean_text, word_count
from ..utils.urls import domain_of, normalize_url
from .base import ConnectorResult, DiscoveredItem

MANUAL_TYPES = {
    "manual_url": "Public URL (text pasted by a human)",
    "manual_text": "Pasted text",
    "manual_social": "Public social post (pasted)",
    "manual_transcript": "Transcript",
    "manual_note": "Meeting note",
    "manual_customer_insight": "Customer insight",
}


def build_manual_item(
    *,
    text: str,
    source_type: str = "manual_text",
    url: str | None = None,
    title: str | None = None,
    author: str | None = None,
    published_at: datetime | None = None,
    description: str | None = None,
    added_by: str = "dashboard",
) -> DiscoveredItem:
    """Turn a dashboard submission into a :class:`DiscoveredItem`.

    Raises ``ValueError`` on empty text — we never store a source with no body.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Manual sources require pasted text. A URL alone is not stored.")
    if source_type not in MANUAL_TYPES:
        source_type = "manual_text"

    cleaned = clean_text(text)
    normalized_url = normalize_url(url) if url else ""
    if not normalized_url:
        # Stable synthetic identifier so dedupe and evidence links still work.
        from ..utils.hashing import short_hash

        normalized_url = f"manual://{source_type}/{short_hash(cleaned, 16)}"

    if not title:
        first_line = cleaned.split("\n", 1)[0]
        title = (first_line[:120] + "…") if len(first_line) > 120 else first_line

    return DiscoveredItem(
        source_url=normalized_url,
        source_type=source_type,
        title=title,
        author=author,
        published_at=published_at,
        search_query=None,
        summary=(description or cleaned[:400]),
        raw_text=text,
        needs_fetch=False,
        metadata={
            "cleaned_text": cleaned,
            "manual_description": description,
            "manual_type_label": MANUAL_TYPES[source_type],
            "added_by": added_by,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "source_domain": domain_of(normalized_url) or "manual-entry",
            "word_count": word_count(cleaned),
            "human_supplied": True,
            "has_publication_date": published_at is not None,
        },
    )


def manual_result(items: list[DiscoveredItem]) -> ConnectorResult:
    return ConnectorResult(connector="manual", items=items)
