"""Podium first-party public content.

Allowlisted-domain crawling only: seed URLs come from ``config/sources.yaml``
and link-following is capped per section and confined to the same domain.
robots.txt and crawl-delay are enforced by :class:`PoliteFetcher`.
"""

from __future__ import annotations

import logging

from ..config import load_config
from ..utils.article import parse_html
from ..utils.http import PoliteFetcher
from ..utils.urls import domain_of, is_allowed, normalize_url
from .base import BaseConnector, ConnectorResult, DiscoveredItem

log = logging.getLogger(__name__)

MIN_WORDS = 90  # below this a page is nav chrome, not content


class PodiumSiteConnector(BaseConnector):
    name = "podium_site"

    def __init__(self, fetcher: PoliteFetcher | None = None, sections: list[dict] | None = None):
        self.cfg = load_config()
        self.fetcher = fetcher or PoliteFetcher()
        self.sections = sections if sections is not None else self.cfg.podium_sections
        self._own_fetcher = fetcher is None

    def discover(self) -> ConnectorResult:
        result = ConnectorResult(connector=self.name)
        if not self.sections:
            return self.not_configured(
                "No podium_sections defined in config/sources.yaml."
            )

        allowed = self.cfg.allowed_domains
        blocked = self.cfg.blocked_domains
        max_pages = self.cfg.crawl.max_pages_per_podium_section
        visited: set[str] = set()

        for section in self.sections:
            name = section.get("name", "unnamed section")
            category = section.get("category", "podium")
            follow = bool(section.get("follow_links"))
            queue: list[str] = [normalize_url(u) for u in section.get("seeds", []) if u]
            pages_in_section = 0

            while queue and pages_in_section < max_pages:
                url = queue.pop(0)
                if not url or url in visited:
                    continue
                visited.add(url)

                if not is_allowed(url, allowed, blocked):
                    result.skipped.append(f"{url} — not on the allowlist")
                    continue

                fetched = self.fetcher.fetch(url)
                result.requests_made += 1

                if not fetched.ok:
                    if fetched.skipped_reason:
                        result.skipped.append(f"{url} — {fetched.error}")
                    else:
                        # 404s on speculative seed URLs are expected, not failures.
                        if fetched.status_code == 404:
                            result.skipped.append(f"{url} — HTTP 404 (seed URL not present)")
                        else:
                            result.errors.append(f"{url} — {fetched.error}")
                    continue

                article = parse_html(fetched.html, fetched.final_url or url, collect_links=follow)
                pages_in_section += 1

                if article.word_count < MIN_WORDS:
                    result.skipped.append(
                        f"{url} — only {article.word_count} words of body text"
                    )
                else:
                    result.items.append(
                        DiscoveredItem(
                            source_url=article.canonical_url or url,
                            source_type=self.name,
                            title=article.title,
                            author=article.author,
                            published_at=article.published_at,
                            search_query=None,
                            summary=article.excerpt,
                            raw_text=fetched.html,
                            needs_fetch=False,
                            metadata={
                                "podium_section": name,
                                "podium_category": category,
                                "cleaned_text": article.text,
                                "extractor": article.extractor,
                                "word_count": article.word_count,
                                "is_promotional": article.is_promotional,
                                "http_status": fetched.status_code,
                                "final_url": fetched.final_url,
                                "source_domain": domain_of(url),
                                "first_party": True,
                            },
                        )
                    )

                if follow:
                    for link in article.links:
                        if link in visited or link in queue:
                            continue
                        if not is_allowed(link, allowed, blocked):
                            continue
                        if pages_in_section + len(queue) >= max_pages:
                            break
                        queue.append(link)

        if not result.items and not result.errors:
            result.errors.append(
                "No Podium pages returned usable content — check the seed URLs in "
                "config/sources.yaml (the site structure may have changed)."
            )
        return result

    def close(self) -> None:
        if self._own_fetcher:
            self.fetcher.close()
