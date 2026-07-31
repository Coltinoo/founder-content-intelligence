"""RSS / Atom ingestion.

This is the primary zero-credential source of genuine public data. Feed items
give us title, link, author, publication date and a summary; the full article
body is fetched separately by the ingest pipeline (subject to robots.txt), and
we keep the feed summary as a fallback when the article body is unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import feedparser

from ..config import load_config
from ..utils.http import PoliteFetcher
from ..utils.text import clean_text
from ..utils.urls import domain_of, normalize_url
from .base import BaseConnector, ConnectorResult, DiscoveredItem

log = logging.getLogger(__name__)


def _entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, key, None) or entry.get(key) if hasattr(entry, "get") else None
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _entry_summary(entry) -> str:
    for key in ("summary", "description"):
        value = entry.get(key) if hasattr(entry, "get") else getattr(entry, key, None)
        if value:
            # Feed summaries are HTML fragments — strip to text.
            from bs4 import BeautifulSoup

            return clean_text(BeautifulSoup(value, "lxml").get_text(" ", strip=True))
    content = entry.get("content") if hasattr(entry, "get") else None
    if content and isinstance(content, list) and content:
        from bs4 import BeautifulSoup

        return clean_text(BeautifulSoup(content[0].get("value", ""), "lxml").get_text(" ", strip=True))
    return ""


class RSSConnector(BaseConnector):
    name = "rss"

    def __init__(self, feeds: list[dict] | None = None, fetcher: PoliteFetcher | None = None):
        self.cfg = load_config()
        self.feeds = feeds if feeds is not None else self.cfg.enabled_feeds
        self.fetcher = fetcher or PoliteFetcher()
        self._own_fetcher = fetcher is None

    def discover(self) -> ConnectorResult:
        result = ConnectorResult(connector=self.name)
        if not self.feeds:
            return self.not_configured(
                "No RSS feeds enabled. Add feeds in config/feeds.yaml or on the Settings page. "
                "The rest of the pipeline runs without them."
            )

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cfg.discovery.lookback_days)
        per_feed = self.cfg.discovery.rss_items_per_feed

        for feed in self.feeds:
            url = feed.get("url")
            feed_name = feed.get("name", url)
            if not url:
                continue

            # Fetch the bytes ourselves so the request is bounded by our timeout,
            # rate limiter and user agent. feedparser's own HTTP has no timeout.
            body, error = self.fetcher.fetch_feed(url)
            result.requests_made += 1
            if error:
                result.errors.append(f"{feed_name}: {error}")
                continue

            try:
                parsed = feedparser.parse(body)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{feed_name}: {exc.__class__.__name__}: {exc}")
                continue

            if not parsed.entries:
                reason = getattr(parsed, "bozo_exception", None) or "no entries in feed"
                result.errors.append(f"{feed_name}: {reason}")
                continue

            kept = 0
            for entry in parsed.entries:
                if kept >= per_feed:
                    break
                link = entry.get("link") or entry.get("id")
                if not link or not link.startswith("http"):
                    continue

                published = _entry_datetime(entry)
                if published and published < cutoff:
                    continue

                author = entry.get("author") or (
                    entry.get("authors", [{}])[0].get("name") if entry.get("authors") else None
                )
                summary = _entry_summary(entry)

                result.items.append(
                    DiscoveredItem(
                        source_url=normalize_url(link),
                        source_type=self.name,
                        title=(entry.get("title") or "").strip() or None,
                        author=author,
                        published_at=published,
                        search_query=None,
                        summary=summary,
                        needs_fetch=True,
                        metadata={
                            "feed_name": feed_name,
                            "feed_url": url,
                            "feed_category": feed.get("category"),
                            "industry_hint": feed.get("industry"),
                            "source_domain": domain_of(link),
                            "feed_summary": summary,
                            "tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")],
                        },
                    )
                )
                kept += 1

            if kept == 0:
                result.skipped.append(
                    f"{feed_name}: no entries within the {self.cfg.discovery.lookback_days}-day window"
                )

        return result

    def close(self) -> None:
        if self._own_fetcher:
            self.fetcher.close()
