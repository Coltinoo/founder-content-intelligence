"""Reddit discussions, through the official Data API.

Why the API and not the RSS feed
--------------------------------
Reddit publishes search results as Atom at ``/r/<sub>/search.rss``, and that URL
returns rich data — full post bodies, named authors, recent timestamps — without
any credential. It is also disallowed. Reddit's robots.txt is ``Disallow: /``
for every user agent, with a header pointing at their Public Content Policy.
A request that succeeds is not a request that is permitted, and this project's
whole claim is that it respects robots.

So this connector uses the sanctioned route: OAuth against
``oauth.reddit.com`` with a registered application's client credentials. That is
an API key, not somebody's account login — the same category as the search and
model keys already in ``.env``. Reddit's free tier covers non-commercial use at
100 queries/minute, which is far more than this needs.

Why Reddit at all
-----------------
For this market it is the best source available. r/smallbusiness, r/HVAC,
r/plumbing and r/AutoDetailing are where owners describe the exact problem
Podium sells against, in their own words, at length, with a name attached — and
they are asking for help, which is the one context where a reply is welcome
rather than an intrusion.

What it never does
------------------
Comment, vote, message, or post. Items land in the engagement watchlist for a
human to read and decide on, exactly like every other channel.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from ..config import load_config
from ..utils.http import PoliteFetcher
from ..utils.text import clean_text
from ..utils.urls import normalize_url
from .base import BaseConnector, ConnectorResult, DiscoveredItem

log = logging.getLogger(__name__)

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_ROOT = "https://oauth.reddit.com"

SETUP_MESSAGE = (
    "Reddit discussions are skipped: no REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET "
    "set. Register a 'script' app at reddit.com/prefs/apps (free, ~2 minutes) "
    "and add both to .env. This uses application credentials through Reddit's "
    "official API — never an account login, and never the robots-disallowed "
    "RSS endpoints."
)

MIN_BODY_WORDS = 20


class RedditConnector(BaseConnector):
    name = "reddit"

    def __init__(self, fetcher: PoliteFetcher | None = None, config=None):
        self.cfg = config or load_config()
        self.creds = self.cfg.credentials
        self.settings = self.cfg.reddit_discovery
        self.fetcher = fetcher or PoliteFetcher()

    # ── auth ────────────────────────────────────────────────────────────
    def _token(self) -> tuple[str | None, str | None]:
        client_id = getattr(self.creds, "reddit_client_id", None)
        client_secret = getattr(self.creds, "reddit_client_secret", None)
        if not (client_id and client_secret):
            return None, "no credentials"
        try:
            response = httpx.post(
                TOKEN_URL,
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.cfg.crawl.user_agent},
                timeout=self.cfg.crawl.request_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            return None, f"{exc.__class__.__name__}: {exc}"
        if response.status_code != 200:
            return None, f"token request returned HTTP {response.status_code}"
        return response.json().get("access_token"), None

    # ── discovery ───────────────────────────────────────────────────────
    def discover(self) -> ConnectorResult:
        if not self.settings.get("enabled", False):
            return self.not_configured(
                "Reddit discovery is disabled. Enable it under `reddit_discovery` "
                "in config/sources.yaml."
            )
        subreddits = [s for s in self.settings.get("subreddits", []) if s]
        queries = [q for q in self.settings.get("queries", []) if q]
        if not subreddits or not queries:
            return self.not_configured(
                "No subreddits or queries configured under `reddit_discovery`."
            )

        token, error = self._token()
        if not token:
            return self.not_configured(
                SETUP_MESSAGE if error == "no credentials"
                else f"{SETUP_MESSAGE} (last attempt: {error})"
            )

        result = ConnectorResult(connector=self.name)
        max_age = int(self.settings.get("max_age_days", self.cfg.discovery.lookback_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age)
        limit = int(self.settings.get("results_per_query", 10))
        headers = {"Authorization": f"Bearer {token}",
                   "User-Agent": self.cfg.crawl.user_agent}
        seen: set[str] = set()
        too_old = thin = 0

        with httpx.Client(headers=headers, timeout=self.cfg.crawl.request_timeout) as client:
            for subreddit in subreddits:
                for query in queries:
                    url = f"{API_ROOT}/r/{subreddit}/search"
                    params = {"q": query, "restrict_sr": 1, "sort": "new",
                              "t": "month", "limit": limit}
                    try:
                        response = client.get(url, params=params)
                        result.requests_made += 1
                    except Exception as exc:  # noqa: BLE001
                        result.errors.append(
                            f"r/{subreddit} '{query}': {exc.__class__.__name__}: {exc}")
                        continue
                    if response.status_code != 200:
                        result.errors.append(
                            f"r/{subreddit} '{query}': HTTP {response.status_code}")
                        continue

                    for child in response.json().get("data", {}).get("children", []):
                        post = child.get("data") or {}
                        permalink = post.get("permalink")
                        if not permalink:
                            continue
                        link = normalize_url("https://www.reddit.com" + permalink)
                        if not link or link in seen:
                            continue

                        created = post.get("created_utc")
                        published = (datetime.fromtimestamp(created, tz=timezone.utc)
                                     if created else None)
                        if published and published < cutoff:
                            too_old += 1
                            continue

                        body = clean_text(post.get("selftext") or "")
                        title = (post.get("title") or "").strip()
                        # A link-only post is a headline with no argument in it.
                        if len((body + " " + title).split()) < MIN_BODY_WORDS:
                            thin += 1
                            continue

                        seen.add(link)
                        author = post.get("author")
                        full_text = f"{title}\n\n{body}".strip()
                        result.items.append(
                            DiscoveredItem(
                                source_url=link,
                                source_type=self.name,
                                title=title or f"r/{subreddit} discussion",
                                author=f"u/{author}" if author and author != "[deleted]" else None,
                                published_at=published,
                                search_query=f"r/{subreddit}: {query}",
                                summary=body[:400],
                                raw_text=full_text,
                                # The API response already carries the whole post.
                                # Nothing further is fetched from reddit.com.
                                needs_fetch=False,
                                metadata={
                                    "cleaned_text": full_text,
                                    "subreddit": subreddit,
                                    "reddit_score": post.get("score"),
                                    "reddit_comments": post.get("num_comments"),
                                    "social_platform": f"r/{subreddit}",
                                    "collection_note": (
                                        "Retrieved through Reddit's official Data API "
                                        "with application credentials. No account "
                                        "login, and no robots-disallowed endpoint."
                                    ),
                                },
                            )
                        )

        if too_old:
            result.skipped.append(f"{too_old} post(s) older than {max_age} days.")
        if thin:
            result.skipped.append(
                f"{thin} link-only post(s) with too little text to analyse.")
        return result
