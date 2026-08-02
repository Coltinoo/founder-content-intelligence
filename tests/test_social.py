"""The social channel must never contact the platforms it reports on.

The whole design rests on one property: items are emitted with
``needs_fetch=False``, so the pipeline issues no HTTP request to linkedin.com
or x.com at any point. These tests hold that line, because it is the difference
between a lawful search-index reader and a scraper.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fcie.connectors.social import SocialDiscoveryConnector, _handle_from_url

RECENT = datetime.now(timezone.utc) - timedelta(days=3)
STALE = datetime.now(timezone.utc) - timedelta(days=400)


class _Cfg:
    """Minimal config stub with social discovery switched on."""

    def __init__(self, **overrides):
        # Pinned so these tests do not move when config/sources.yaml changes.
        self.social_discovery = {
            "enabled": True,
            "results_per_query": 3,
            "max_age_days": 45,
            "platforms": [{"name": "LinkedIn", "site": "linkedin.com/posts"},
                          {"name": "X", "site": "x.com"}],
            "topics": ["missed calls"],
            **overrides,
        }

        class _Creds:
            search_provider = "tavily"

        class _Discovery:
            lookback_days = 45

        self.credentials = _Creds()
        self.discovery = _Discovery()


HITS = [
    {"url": "https://www.linkedin.com/posts/someone_ai-activity-123",
     "title": "Owners keep missing calls", "summary": "A short public snippet.",
     "published_at": RECENT},
    {"url": "https://x.com/someone/status/456",
     "title": "Speed to lead thread", "summary": "Another public snippet.",
     "published_at": RECENT},
    {"url": "https://randomblog.com/post",
     "title": "Off-platform result", "summary": "Search returned something else.",
     "published_at": RECENT},
    {"url": "https://www.linkedin.com/products/some-product",
     "title": "A product page, not a post", "summary": "Marketing.",
     "published_at": RECENT},
]


def _run(hits=HITS, **cfg_overrides):
    connector = SocialDiscoveryConnector(fetcher=object(), config=_Cfg(**cfg_overrides))
    with patch("fcie.connectors.web_search.WebSearchConnector") as ws:
        ws.return_value._provider_runner.return_value = lambda q, n: (hits, None)
        return connector.discover()


class TestNeverFetches:
    def test_every_item_is_marked_do_not_fetch(self):
        """The single property the whole design rests on."""
        result = _run()
        assert result.items
        assert all(item.needs_fetch is False for item in result.items), (
            "a social item with needs_fetch=True would cause the pipeline to "
            "issue a request to the platform — that is scraping"
        )

    def test_the_platforms_stay_blocked_from_crawling(self):
        """Even if something tried, the fetcher must refuse."""
        from fcie.config import load_config

        blocked = load_config().blocked_domains
        for host in ("linkedin.com", "x.com", "twitter.com"):
            assert host in blocked, f"{host} must remain in blocked_domains"

    def test_only_the_search_snippet_is_stored(self):
        result = _run()
        for item in result.items:
            assert item.metadata["snippet_only"] is True
            assert item.raw_text == item.metadata["search_snippet"]
            assert "never crawled" in item.metadata["collection_note"]


class TestResultHandling:
    def test_off_platform_hits_are_discarded(self):
        result = _run()
        hosts = {item.metadata["source_domain"] for item in result.items}
        assert "randomblog.com" not in hosts
        assert any("not on" in s for s in result.skipped)

    def test_non_post_urls_are_rejected_at_discovery(self):
        """`site:` returns product pages and partner directories, not just posts."""
        result = _run()
        assert not any("/products/" in i.source_url for i in result.items)
        assert any("not a post" in s for s in result.skipped)

    def test_stale_posts_are_dropped(self):
        """Replying to a ten-month-old post is worse than replying to nothing."""
        stale = [dict(HITS[0], published_at=STALE)]
        result = _run(hits=stale)
        assert result.items == []
        assert any("older than" in s for s in result.skipped)

    def test_undated_posts_are_dropped(self):
        undated = [dict(HITS[0], published_at=None)]
        result = _run(hits=undated)
        assert result.items == []
        assert any("no publication date" in s for s in result.skipped)

    def test_the_poster_is_identified_from_the_url(self):
        """A watchlist entry that cannot say who posted is close to useless."""
        assert _handle_from_url(
            "https://linkedin.com/posts/larrycfischer_local-activity-1") == "larrycfischer"
        assert _handle_from_url("https://x.com/coreyganim/status/12345") == "coreyganim"
        assert _handle_from_url("https://linkedin.com/pulse/an-article") is None
        result = _run()
        assert any(i.author for i in result.items)

    def test_both_platforms_are_searched(self):
        result = _run()
        platforms = {item.metadata["social_platform"] for item in result.items}
        assert platforms == {"LinkedIn", "X"}

    def test_disabled_reports_itself_rather_than_failing(self):
        result = _run(enabled=False)
        assert not result.configured
        assert "disabled" in result.setup_message.lower()
        assert result.items == []

    def test_no_provider_reports_setup_instead_of_erroring(self):
        connector = SocialDiscoveryConnector(fetcher=object(), config=_Cfg())
        connector.provider = None
        result = connector.discover()
        assert not result.configured
        assert result.items == []

    def test_empty_results_say_so_rather_than_looking_broken(self):
        result = _run(hits=[])
        assert result.items == []
        assert any("sparse" in s for s in result.skipped)
