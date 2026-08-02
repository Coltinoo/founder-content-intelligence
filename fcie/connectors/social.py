"""Public social discussion, found through search — never by crawling a platform.

The distinction this module rests on
------------------------------------
Reading LinkedIn or X directly means authenticating, or evading the fact that
they require it. This connector does neither. It asks the same lawful search
API the rest of the pipeline uses for *publicly indexed* posts, and keeps only
what the search index already publishes: a title, a snippet, a URL, a date.

Every item is emitted with ``needs_fetch = False``. That is the whole safety
property, and it is asserted in tests: the pipeline issues **no HTTP request to
linkedin.com or x.com at any point**. Those hosts stay in ``blocked_domains``,
so even if something later tried to fetch one, the fetcher would refuse.

What this gives up
------------------
Snippets, not full posts. No comment threads, no reaction counts, no follower
data, no private or logged-in content, and no coverage of anything search has
not indexed. That is a real limitation and the UI says so rather than implying
the coverage is complete.

What it never does
------------------
Comment, like, repost, follow, connect, or message. It produces a review queue
for a human and stops. That is enforced in ``pipeline/engagement.py``, which is
where these land.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ..config import load_config
from ..utils.http import PoliteFetcher
from ..utils.urls import domain_of, normalize_url
from .base import BaseConnector, ConnectorResult, DiscoveredItem
from .web_search import SETUP_MESSAGE as SEARCH_SETUP_MESSAGE

log = logging.getLogger(__name__)

SETUP_MESSAGE = (
    "Social discovery needs a web-search provider, because that is the only "
    "lawful way it reads these platforms. " + SEARCH_SETUP_MESSAGE
)

NOT_ENABLED_MESSAGE = (
    "Social discovery is disabled. Enable it under `social_discovery` in "
    "config/sources.yaml."
)

# URL shapes that are an actual post or article. Everything else on these hosts
# is a profile, a product page or a partner directory — somewhere to go rather
# than something to reply to. Mirrors the check in pipeline/engagement.py.
CONVERSATION_MARKERS = ("/posts/", "/pulse/", "/status/", "/feed/update/")


def _handle_from_url(url: str) -> str | None:
    """The poster's handle, read out of the post URL.

    Search providers rarely return an author for social results, and a
    watchlist entry that cannot say who posted is close to useless — the whole
    question is who you would be replying to. Both platforms put the handle in
    the path: linkedin.com/posts/<handle>_<slug> and x.com/<handle>/status/<id>.
    """
    import re

    match = re.search(r"linkedin\.com/posts/([^/_?#]+)", url, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"(?:x|twitter)\.com/([^/?#]+)/status/", url, re.IGNORECASE)
    if match and match.group(1).lower() not in {"i", "home"}:
        return match.group(1)
    return None


class SocialDiscoveryConnector(BaseConnector):
    """Public posts on social platforms, via the search index only."""

    name = "social_public"

    def __init__(self, fetcher: PoliteFetcher | None = None, config=None):
        self.cfg = config or load_config()
        self.creds = self.cfg.credentials
        self.provider = self.creds.search_provider
        # Held only so the shared politeness budget is respected by the search
        # provider call itself. It is never pointed at a social platform.
        self.fetcher = fetcher or PoliteFetcher()
        self.settings = self.cfg.social_discovery

    def discover(self) -> ConnectorResult:
        if not self.settings.get("enabled", False):
            return self.not_configured(NOT_ENABLED_MESSAGE)
        platforms = [p for p in self.settings.get("platforms", []) if p.get("site")]
        topics = [t for t in self.settings.get("topics", []) if t]
        if not platforms or not topics:
            return self.not_configured(
                "No platforms or topics configured under `social_discovery`."
            )
        if not self.provider:
            return self.not_configured(SETUP_MESSAGE)

        # Reuse the search plumbing rather than reimplementing five providers.
        from .web_search import WebSearchConnector

        searcher = WebSearchConnector(queries=[], fetcher=self.fetcher)
        runner = searcher._provider_runner()  # noqa: SLF001 — same package
        if runner is None:
            return self.not_configured(SETUP_MESSAGE)

        result = ConnectorResult(connector=f"{self.name} [{self.provider}]")
        limit = int(self.settings.get("results_per_query", 6))
        seen: set[str] = set()
        max_age = int(self.settings.get("max_age_days",
                                        self.cfg.discovery.lookback_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age)
        undated = too_old = 0

        for platform in platforms:
            site = platform["site"].strip().lower()
            label = platform.get("name") or site
            for topic in topics:
                query = f"site:{site} {topic}"
                try:
                    hits, error = runner(query, limit)
                    result.requests_made += 1
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(f"{query}: {exc.__class__.__name__}: {exc}")
                    continue
                if error:
                    result.errors.append(f"{query}: {error}")
                    continue

                for hit in hits:
                    url = normalize_url(hit.get("url", ""))
                    if not url or url in seen:
                        continue
                    host = domain_of(url)
                    # The search engine can return anything; only keep hits that
                    # really are on the platform we asked about.
                    if not (host == site.split("/")[0]
                            or host.endswith("." + site.split("/")[0])):
                        result.skipped.append(f"{url} — not on {label}")
                        continue
                    # ...and only ones that are actually posts. A `site:` query
                    # happily returns product pages and partner directories —
                    # linkedin.com/products/… and partners.x.com/… both came back
                    # on the first live run. Storing those and filtering them
                    # downstream wastes an extraction call each and pads the
                    # library with pages nobody would ever reply to.
                    if not any(marker in url.lower() for marker in CONVERSATION_MARKERS):
                        result.skipped.append(f"{url} — not a post")
                        continue
                    # Recency is not optional here. Search ranks by relevance,
                    # so a `site:` query happily returns a post from last year —
                    # the first live run surfaced three good ones dated April,
                    # September and June. Replying to a ten-month-old post is
                    # worse than replying to nothing, and an undated post could
                    # be any age, so both are dropped rather than guessed at.
                    published = hit.get("published_at")
                    if published is None:
                        undated += 1
                        continue
                    if published < cutoff:
                        too_old += 1
                        continue
                    seen.add(url)
                    snippet = (hit.get("summary") or "").strip()
                    result.items.append(
                        DiscoveredItem(
                            source_url=url,
                            source_type=self.name,
                            title=hit.get("title") or f"{label} post",
                            author=hit.get("author") or _handle_from_url(url),
                            published_at=hit.get("published_at"),
                            search_query=query,
                            summary=snippet,
                            raw_text=snippet,
                            # Load-bearing. False means the pipeline never
                            # requests this URL. Do not change it.
                            needs_fetch=False,
                            metadata={
                                "search_provider": self.provider,
                                "search_snippet": snippet,
                                "cleaned_text": snippet,
                                "social_platform": label,
                                "source_domain": host,
                                "snippet_only": True,
                                "collection_note": (
                                    f"Public search result only. {label} was never "
                                    f"crawled, logged into, or contacted."
                                ),
                            },
                        )
                    )
        if undated:
            result.skipped.append(
                f"{undated} post(s) dropped: no publication date, and an undated "
                f"post could be any age."
            )
        if too_old:
            result.skipped.append(
                f"{too_old} post(s) dropped: older than {max_age} days. Search "
                f"ranks by relevance, not recency."
            )
        if not result.items and not result.errors:
            result.skipped.append(
                "No recent public posts matched. Search indexes only a fraction "
                "of social content and favours older, well-linked posts, so this "
                "channel is expected to be sparse."
            )
        return result
