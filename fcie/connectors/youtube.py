"""YouTube discovery.

Two lawful paths, no scraping and no caption bypassing:

1. **YouTube Data API v3** (``YOUTUBE_API_KEY``) — keyword search across the
   configured queries, then a ``videos.list`` call for full snippet metadata and
   a ``captions.list`` call to record *whether* captions exist.
2. **Public per-channel Atom feeds** (no credentials) —
   ``https://www.youtube.com/feeds/videos.xml?channel_id=…``. This is a
   published, unauthenticated endpoint.

Transcripts are only stored when supplied through a supported, authorised route.
When captions are unavailable we record ``transcript_status`` and move on; we
never attempt to extract captions that YouTube has not made available.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import feedparser

from ..config import load_config
from ..utils.http import PoliteFetcher
from ..utils.text import clean_text
from ..utils.urls import youtube_video_id
from .base import BaseConnector, ConnectorResult, DiscoveredItem

log = logging.getLogger(__name__)

API_ROOT = "https://www.googleapis.com/youtube/v3"

VIDEO_QUERIES = [
    "Eric Rea Podium interview",
    "Podium AI Employee demo",
    "Podium customer story",
    "AI agents local business panel",
    "AI home services technology",
    "AI automotive dealership technology",
    "AI medspa marketing technology",
]


class YouTubeConnector(BaseConnector):
    name = "youtube"

    def __init__(self, queries: list[str] | None = None, fetcher: PoliteFetcher | None = None):
        self.cfg = load_config()
        self.creds = self.cfg.credentials
        self.queries = queries if queries is not None else VIDEO_QUERIES
        self.fetcher = fetcher or PoliteFetcher()
        self._own_fetcher = fetcher is None

    def discover(self) -> ConnectorResult:
        if self.creds.has_youtube_api:
            return self._discover_via_api()
        return self._discover_via_channel_feeds()

    # ── API path ────────────────────────────────────────────────────────

    def _discover_via_api(self) -> ConnectorResult:
        result = ConnectorResult(connector=f"{self.name} [data-api]")
        limit = self.cfg.discovery.youtube_results_per_query
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=self.cfg.discovery.lookback_days * 4)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        seen: set[str] = set()

        for query in self.queries:
            payload, error = self.fetcher.get_json(
                f"{API_ROOT}/search",
                params={
                    "key": self.creds.youtube_api_key,
                    "q": query,
                    "part": "snippet",
                    "type": "video",
                    "maxResults": limit,
                    "order": "relevance",
                    "publishedAfter": published_after,
                    "relevanceLanguage": "en",
                },
            )
            result.requests_made += 1
            if error:
                result.errors.append(f"search '{query}': {error}")
                continue

            ids = [
                item["id"]["videoId"]
                for item in payload.get("items", [])
                if item.get("id", {}).get("videoId") and item["id"]["videoId"] not in seen
            ]
            if not ids:
                continue

            details, error = self.fetcher.get_json(
                f"{API_ROOT}/videos",
                params={
                    "key": self.creds.youtube_api_key,
                    "id": ",".join(ids),
                    "part": "snippet,contentDetails,statistics",
                },
            )
            result.requests_made += 1
            if error:
                result.errors.append(f"videos.list for '{query}': {error}")
                continue

            for item in details.get("items", []):
                vid = item["id"]
                if vid in seen:
                    continue
                seen.add(vid)
                snippet = item.get("snippet", {})
                thumbs = snippet.get("thumbnails", {})
                thumb = (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("default") or {}).get("url")
                caption_flag = item.get("contentDetails", {}).get("caption") == "true"

                result.items.append(self._item(
                    video_id=vid,
                    title=snippet.get("title"),
                    description=snippet.get("description", ""),
                    channel=snippet.get("channelTitle"),
                    channel_id=snippet.get("channelId"),
                    published=snippet.get("publishedAt"),
                    thumbnail=thumb,
                    query=query,
                    transcript_status=(
                        "captions_available_not_ingested" if caption_flag
                        else "no_captions_published"
                    ),
                    extra={
                        "duration": item.get("contentDetails", {}).get("duration"),
                        "view_count": item.get("statistics", {}).get("viewCount"),
                        "discovery_method": "data_api",
                    },
                ))

        if not result.items and not result.errors:
            result.skipped.append("YouTube Data API returned no videos for the configured queries.")
        return result

    # ── Public channel Atom feed path (no credentials) ──────────────────

    def _discover_via_channel_feeds(self) -> ConnectorResult:
        channels = self.cfg.youtube_channels
        result = ConnectorResult(
            connector=f"{self.name} [channel-rss]",
            setup_message=(
                "No YOUTUBE_API_KEY set, so keyword video search is unavailable. "
                "Falling back to public per-channel Atom feeds "
                "(youtube.com/feeds/videos.xml). Add YOUTUBE_API_KEY to enable "
                "query-based video discovery."
            ),
        )
        if not channels:
            return self.not_configured(
                "No YOUTUBE_API_KEY and no youtube_channels configured in "
                "config/sources.yaml. YouTube discovery is skipped."
            )

        for channel in channels:
            channel_id = channel.get("channel_id")
            channel_name = channel.get("name", channel_id)
            if not channel_id:
                continue
            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            body, error = self.fetcher.fetch_feed(feed_url)
            result.requests_made += 1
            if error:
                result.errors.append(
                    f"{channel_name} (id={channel_id}): {error}. Verify the channel ID with "
                    "`python scripts/verify_youtube.py --resolve @handle` and update "
                    "config/sources.yaml."
                )
                continue

            try:
                parsed = feedparser.parse(body)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{channel_name}: {exc.__class__.__name__}: {exc}")
                continue

            if not parsed.entries:
                result.errors.append(
                    f"{channel_name} (id={channel_id}): no entries returned — the channel ID "
                    "may be wrong. Verify it and update config/sources.yaml."
                )
                continue

            for entry in parsed.entries[: self.cfg.discovery.youtube_results_per_query]:
                link = entry.get("link", "")
                vid = youtube_video_id(link)
                if not vid:
                    continue
                media = entry.get("media_thumbnail") or []
                description = ""
                if hasattr(entry, "summary"):
                    description = clean_text(entry.summary)
                published = None
                if entry.get("published_parsed"):
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

                result.items.append(self._item(
                    video_id=vid,
                    title=entry.get("title"),
                    description=description,
                    channel=entry.get("author") or channel_name,
                    channel_id=channel_id,
                    published=published,
                    thumbnail=media[0].get("url") if media else None,
                    query=None,
                    transcript_status="not_checked_no_api_key",
                    extra={"discovery_method": "channel_rss", "feed_url": feed_url},
                ))

        return result

    # ── shared ──────────────────────────────────────────────────────────

    @staticmethod
    def _item(*, video_id, title, description, channel, channel_id, published,
              thumbnail, query, transcript_status, extra) -> DiscoveredItem:
        if isinstance(published, str):
            from dateutil import parser as dp
            try:
                published = dp.parse(published)
            except (ValueError, TypeError):
                published = None

        url = f"https://www.youtube.com/watch?v={video_id}"
        body = "\n\n".join(part for part in [title, description] if part)
        return DiscoveredItem(
            source_url=url,
            source_type="youtube",
            title=title,
            author=channel,
            published_at=published,
            search_query=query,
            summary=(description or "")[:600],
            raw_text=body,
            needs_fetch=False,   # title + description is the lawful payload
            metadata={
                "video_id": video_id,
                "channel": channel,
                "channel_id": channel_id,
                "thumbnail_url": thumbnail,
                "transcript_status": transcript_status,
                "transcript": None,
                "cleaned_text": clean_text(body),
                "source_domain": "youtube.com",
                "content_note": (
                    "Title and public description only. Transcript not ingested — "
                    "captions are used solely when lawfully available through a "
                    "supported API."
                ),
                **extra,
            },
        )

    def close(self) -> None:
        if self._own_fetcher:
            self.fetcher.close()
