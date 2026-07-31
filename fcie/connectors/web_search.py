"""Public web search through lawful search APIs.

Supported providers, in preference order: Tavily, Brave, Bing Web Search,
Google Programmable Search, OpenAI Responses ``web_search``.

Search-engine result pages are NEVER scraped. When no provider is configured
the connector reports itself as unconfigured with a setup message, and the rest
of the pipeline continues on RSS + first-party sources.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from dateutil import parser as date_parser

from ..config import load_config
from ..utils.http import PoliteFetcher
from ..utils.urls import domain_of, normalize_url
from .base import BaseConnector, ConnectorResult, DiscoveredItem

log = logging.getLogger(__name__)

SETUP_MESSAGE = (
    "No web-search provider configured. Set one of: TAVILY_API_KEY, "
    "BRAVE_SEARCH_API_KEY, BING_SEARCH_API_KEY, or GOOGLE_CSE_API_KEY + "
    "GOOGLE_CSE_CX (or OPENAI_API_KEY with FCIE_OPENAI_WEB_SEARCH=1). "
    "Recurring query discovery is skipped until then; RSS, first-party Podium "
    "crawling, YouTube and manual entry continue to work."
)


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = date_parser.parse(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


class WebSearchConnector(BaseConnector):
    name = "web_search"

    def __init__(self, queries: list[dict] | None = None, fetcher: PoliteFetcher | None = None):
        self.cfg = load_config()
        self.creds = self.cfg.credentials
        self.queries = queries if queries is not None else self.cfg.enabled_queries
        self.fetcher = fetcher or PoliteFetcher()
        self._own_fetcher = fetcher is None
        self.provider = self.creds.search_provider

    def discover(self) -> ConnectorResult:
        if not self.provider:
            return self.not_configured(SETUP_MESSAGE)
        if not self.queries:
            return self.not_configured("No search queries enabled in config/queries.yaml.")

        result = ConnectorResult(connector=f"{self.name} [{self.provider}]")
        limit = self.cfg.discovery.search_results_per_query
        blocked = self.cfg.blocked_domains
        seen: set[str] = set()

        runner = {
            "tavily": self._search_tavily,
            "brave": self._search_brave,
            "bing": self._search_bing,
            "google_cse": self._search_google,
            "openai_web_search": self._search_openai,
        }[self.provider]

        for entry in self.queries:
            query = entry.get("query")
            if not query:
                continue
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
                if any(host == b.removeprefix("www.") or host.endswith("." + b.removeprefix("www."))
                       for b in blocked):
                    result.skipped.append(f"{url} — platform excluded from automated collection")
                    continue
                seen.add(url)
                result.items.append(
                    DiscoveredItem(
                        source_url=url,
                        source_type=self.name,
                        title=hit.get("title"),
                        author=hit.get("author"),
                        published_at=hit.get("published_at"),
                        search_query=query,
                        summary=hit.get("summary", ""),
                        needs_fetch=True,
                        metadata={
                            "search_provider": self.provider,
                            "search_category": entry.get("category"),
                            "search_rank": hit.get("rank"),
                            "search_snippet": hit.get("summary", ""),
                            "source_domain": host,
                        },
                    )
                )
        return result

    # ── providers ───────────────────────────────────────────────────────

    def _search_tavily(self, query: str, limit: int):
        payload, error = self.fetcher.post_json(
            "https://api.tavily.com/search",
            {
                "api_key": self.creds.tavily_api_key,
                "query": query,
                "max_results": limit,
                "search_depth": "basic",
                "include_answer": False,
                "days": self.cfg.discovery.lookback_days,
            },
        )
        if error:
            return [], error
        hits = []
        for rank, item in enumerate(payload.get("results", []), start=1):
            hits.append({
                "url": item.get("url", ""),
                "title": item.get("title"),
                "summary": item.get("content", "")[:800],
                "published_at": _parse_date(item.get("published_date")),
                "rank": rank,
            })
        return hits, None

    def _search_brave(self, query: str, limit: int):
        payload, error = self.fetcher.get_json(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": min(limit, 20), "freshness": "pm"},
            headers={
                "X-Subscription-Token": self.creds.brave_api_key,
                "Accept": "application/json",
            },
        )
        if error:
            return [], error
        hits = []
        for rank, item in enumerate(payload.get("web", {}).get("results", []), start=1):
            hits.append({
                "url": item.get("url", ""),
                "title": item.get("title"),
                "summary": item.get("description", ""),
                "published_at": _parse_date(item.get("age") or item.get("page_age")),
                "rank": rank,
            })
        return hits, None

    def _search_bing(self, query: str, limit: int):
        payload, error = self.fetcher.get_json(
            self.creds.bing_endpoint,
            params={"q": query, "count": min(limit, 50), "freshness": "Month",
                    "responseFilter": "Webpages", "mkt": "en-US"},
            headers={"Ocp-Apim-Subscription-Key": self.creds.bing_api_key},
        )
        if error:
            return [], error
        hits = []
        for rank, item in enumerate(payload.get("webPages", {}).get("value", []), start=1):
            hits.append({
                "url": item.get("url", ""),
                "title": item.get("name"),
                "summary": item.get("snippet", ""),
                "published_at": _parse_date(item.get("dateLastCrawled")),
                "rank": rank,
            })
        return hits, None

    def _search_google(self, query: str, limit: int):
        payload, error = self.fetcher.get_json(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": self.creds.google_cse_key,
                "cx": self.creds.google_cse_cx,
                "q": query,
                "num": min(limit, 10),
                "dateRestrict": f"d{self.cfg.discovery.lookback_days}",
            },
        )
        if error:
            return [], error
        hits = []
        for rank, item in enumerate(payload.get("items", []), start=1):
            meta = (item.get("pagemap", {}).get("metatags") or [{}])[0]
            hits.append({
                "url": item.get("link", ""),
                "title": item.get("title"),
                "summary": item.get("snippet", ""),
                "published_at": _parse_date(meta.get("article:published_time")),
                "rank": rank,
            })
        return hits, None

    def _search_openai(self, query: str, limit: int):
        """OpenAI Responses API with the hosted ``web_search`` tool."""
        try:
            from openai import OpenAI
        except ImportError:
            return [], "openai package not installed"

        client = OpenAI(api_key=self.creds.openai_api_key)
        instruction = (
            "Search the public web for this query and return ONLY a JSON object "
            '{"results":[{"url":"","title":"","summary":"","published_at":""}]} '
            f"with at most {limit} results. Use only real URLs returned by the "
            "search tool. Never invent a URL, title, or date. If a publication "
            'date is unknown, use an empty string. Query: ' + query
        )
        try:
            response = client.responses.create(
                model=self.cfg.ai.model,
                tools=[{"type": "web_search"}],
                input=instruction,
            )
            text = response.output_text or "{}"
        except Exception as exc:  # noqa: BLE001
            return [], f"{exc.__class__.__name__}: {exc}"

        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return [], "OpenAI web search returned non-JSON output"

        hits = []
        for rank, item in enumerate(data.get("results", [])[:limit], start=1):
            if not item.get("url"):
                continue
            hits.append({
                "url": item["url"],
                "title": item.get("title"),
                "summary": item.get("summary", ""),
                "published_at": _parse_date(item.get("published_at")),
                "rank": rank,
            })
        return hits, None

    def close(self) -> None:
        if self._own_fetcher:
            self.fetcher.close()
