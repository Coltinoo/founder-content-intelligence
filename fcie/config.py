"""Configuration loading.

Layering, lowest precedence first:
    1. YAML files in ``config/``
    2. ``FCIE_*`` environment variables (and ``.env``)

YAML files are the editable surface exposed by the Settings page; env vars are
for secrets and deployment overrides. No secret is ever read from YAML.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env", override=False)

# Backstop against unbounded network waits. Any library that reaches the network
# through a raw socket without its own timeout (urllib, and therefore
# feedparser's built-in fetcher) would otherwise be able to hang a scheduled run
# indefinitely. Connectors use httpx with explicit timeouts; this catches the
# rest. Generous, because it is a last resort rather than the real limit.
if socket.getdefaulttimeout() is None:
    socket.setdefaulttimeout(45.0)


# ── YAML helpers ────────────────────────────────────────────────────────────

def _read_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def write_yaml(name: str, payload: dict[str, Any]) -> None:
    """Persist a config file (used by the Settings page)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = CONFIG_DIR / name
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
    load_config.cache_clear()


def _secret(name: str) -> str | None:
    """Read a credential from the environment, falling back to Streamlit secrets.

    Streamlit Community Cloud normally exports top-level ``secrets.toml`` entries
    as environment variables, but that is a convenience rather than a contract —
    it does not apply to nested sections, and relying on it silently degrades the
    deployed app to "not configured" if it ever changes. Checking ``st.secrets``
    directly makes deployment behave the same as local ``.env``.

    Safe outside Streamlit: import and access are both guarded, so the CLI,
    tests and scheduled runs are unaffected.
    """
    value = os.getenv(name)
    if value and value.strip():
        return value.strip()
    try:
        import streamlit as st

        raw = st.secrets.get(name)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - no streamlit, no secrets file, bare runtime
        return None
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _env_bool(name: str, default: bool) -> bool:
    raw = _secret(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = _secret(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = _secret(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# ── Credential surface ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Credentials:
    """Which optional integrations are actually available.

    Nothing here raises when a key is missing. Callers check the ``has_*``
    properties and surface a setup message instead of failing silently.
    """

    openai_api_key: str | None = None
    tavily_api_key: str | None = None
    brave_api_key: str | None = None
    bing_api_key: str | None = None
    bing_endpoint: str = "https://api.bing.microsoft.com/v7.0/search"
    google_cse_key: str | None = None
    google_cse_cx: str | None = None
    youtube_api_key: str | None = None
    database_url: str | None = None

    @classmethod
    def from_env(cls) -> "Credentials":
        g = _secret

        return cls(
            openai_api_key=g("OPENAI_API_KEY"),
            tavily_api_key=g("TAVILY_API_KEY"),
            brave_api_key=g("BRAVE_SEARCH_API_KEY"),
            bing_api_key=g("BING_SEARCH_API_KEY"),
            bing_endpoint=g("BING_SEARCH_ENDPOINT") or cls.bing_endpoint,
            google_cse_key=g("GOOGLE_CSE_API_KEY"),
            google_cse_cx=g("GOOGLE_CSE_CX"),
            youtube_api_key=g("YOUTUBE_API_KEY"),
            database_url=g("FCIE_DATABASE_URL"),
        )

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_youtube_api(self) -> bool:
        return bool(self.youtube_api_key)

    @property
    def search_provider(self) -> str | None:
        """First configured search provider, in preference order."""
        if self.tavily_api_key:
            return "tavily"
        if self.brave_api_key:
            return "brave"
        if self.bing_api_key:
            return "bing"
        if self.google_cse_key and self.google_cse_cx:
            return "google_cse"
        if self.openai_api_key and _env_bool("FCIE_OPENAI_WEB_SEARCH", False):
            return "openai_web_search"
        return None

    @property
    def uses_postgres(self) -> bool:
        return bool(self.database_url and "postgres" in self.database_url)


# ── Main config object ──────────────────────────────────────────────────────

@dataclass
class CrawlConfig:
    delay_seconds: float = 2.0
    request_timeout: int = 25
    respect_robots: bool = True
    max_sources_per_run: int = 60
    max_pages_per_podium_section: int = 12
    user_agent: str = "FounderContentIntelligenceEngine/0.1 (independent candidate project)"


@dataclass
class AIConfig:
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    max_extraction_chars: int = 14000
    enable_llm: bool = True


@dataclass
class DiscoveryConfig:
    lookback_days: int = 45
    search_results_per_query: int = 8
    rss_items_per_feed: int = 15
    youtube_results_per_query: int = 6


@dataclass
class TrendConfig:
    current_period_days: int = 21
    previous_period_days: int = 21
    min_sources_for_trend: int = 2
    min_domains_for_trend: int = 2


@dataclass
class PipelineConfig:
    min_opportunity_score: int = 55
    max_opportunities_per_run: int = 12


def is_admin() -> bool:
    """True when write controls may be shown.

    **Fail-safe by design: read-only unless `FCIE_ADMIN=1` is explicitly set.**
    The public demo and the operator's laptop run the same code, so the default
    has to be the safe one — a deployment that forgets to configure anything
    must not expose Delete, Reprocess or Approve to anonymous visitors. Turning
    writes *on* is a deliberate act; leaving them off is the accident-proof path.
    """
    return _env_bool("FCIE_ADMIN", False)


def read_only_notice() -> str:
    return (
        "Read-only demo. Controls that would change stored data — running "
        "discovery, regenerating briefs, approving drafts, editing settings — "
        "are hidden here. The full version has them; this deployment is a "
        "public showcase."
    )


@dataclass
class AppConfig:
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    trends: TrendConfig = field(default_factory=TrendConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    scoring: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, Any] = field(default_factory=dict)
    queries: dict[str, Any] = field(default_factory=dict)
    feeds: dict[str, Any] = field(default_factory=dict)
    credentials: Credentials = field(default_factory=Credentials.from_env)

    # ── convenience accessors ───────────────────────────────────────────
    @property
    def allowed_domains(self) -> set[str]:
        return {d.lower().lstrip(".") for d in self.sources.get("allowed_domains", [])}

    @property
    def blocked_domains(self) -> set[str]:
        return {d.lower().lstrip(".") for d in self.sources.get("blocked_domains", [])}

    @property
    def first_party_domains(self) -> set[str]:
        """Domains the company owns. See the note in config/sources.yaml."""
        return {d.lower().lstrip(".") for d in self.sources.get("first_party_domains", [])}

    @property
    def social_discovery(self) -> dict[str, Any]:
        """Public-social discovery settings. See the note in config/sources.yaml."""
        return self.sources.get("social_discovery", {}) or {}

    @property
    def podium_sections(self) -> list[dict[str, Any]]:
        return self.sources.get("podium_sections", [])

    @property
    def youtube_channels(self) -> list[dict[str, Any]]:
        return self.sources.get("youtube_channels", [])

    @property
    def enabled_queries(self) -> list[dict[str, Any]]:
        return [q for q in self.queries.get("queries", []) if q.get("enabled", True)]

    @property
    def enabled_feeds(self) -> list[dict[str, Any]]:
        return [f for f in self.feeds.get("feeds", []) if f.get("enabled", True)]

    @property
    def categories(self) -> list[str]:
        return self.queries.get("categories", [])

    @property
    def industries(self) -> list[str]:
        return self.queries.get("industries", [])

    @property
    def scoring_weights(self) -> dict[str, float]:
        return self.scoring.get("weights", {})

    def integration_status(self) -> list[dict[str, str]]:
        """Human-readable readiness of every optional integration.

        Rendered on the Executive Dashboard and Settings page so a missing key
        is always visible rather than a silent no-op.
        """
        c = self.credentials
        rows = [
            {
                "integration": "Database",
                "status": "Supabase Postgres" if c.uses_postgres else "Local SQLite",
                "detail": c.database_url.split("@")[-1] if c.uses_postgres else str(DATA_DIR / "fcie.db"),
                "ready": "yes",
            },
            {
                "integration": "OpenAI (extraction, briefs, drafts)",
                "status": "Configured" if c.has_openai else "Not configured",
                "detail": (
                    f"model={self.ai.model}"
                    if c.has_openai
                    else "Falling back to the deterministic heuristic analyser. Set OPENAI_API_KEY for LLM extraction."
                ),
                "ready": "yes" if c.has_openai else "fallback",
            },
            {
                "integration": "Web search",
                "status": (c.search_provider or "Not configured"),
                "detail": (
                    "Recurring queries will run."
                    if c.search_provider
                    else "Set TAVILY_API_KEY, BRAVE_SEARCH_API_KEY, BING_SEARCH_API_KEY, or GOOGLE_CSE_API_KEY+GOOGLE_CSE_CX. Search-engine result pages are never scraped."
                ),
                "ready": "yes" if c.search_provider else "no",
            },
            {
                "integration": "YouTube",
                "status": "Data API" if c.has_youtube_api else "Public channel RSS fallback",
                "detail": (
                    "Keyword video discovery enabled."
                    if c.has_youtube_api
                    else "No YOUTUBE_API_KEY: keyword search is unavailable; ingesting public per-channel Atom feeds instead."
                ),
                "ready": "yes" if c.has_youtube_api else "fallback",
            },
            {
                "integration": "RSS feeds",
                "status": f"{len(self.enabled_feeds)} enabled",
                "detail": "No credentials required.",
                "ready": "yes" if self.enabled_feeds else "no",
            },
            {
                "integration": "Podium first-party crawl",
                "status": f"{len(self.podium_sections)} sections",
                "detail": "Allowlisted domains only, robots.txt respected.",
                "ready": "yes" if self.podium_sections else "no",
            },
        ]
        return rows


@lru_cache(maxsize=1)
def load_config() -> AppConfig:
    settings = _read_yaml("settings.yaml")
    crawl_y = settings.get("crawl", {})
    ai_y = settings.get("ai", {})
    disc_y = settings.get("discovery", {})
    trend_y = settings.get("trends", {})
    pipe_y = settings.get("pipeline", {})

    crawl = CrawlConfig(
        delay_seconds=_env_float("FCIE_CRAWL_DELAY_SECONDS", crawl_y.get("delay_seconds", 2.0)),
        request_timeout=_env_int("FCIE_REQUEST_TIMEOUT", crawl_y.get("request_timeout", 25)),
        respect_robots=_env_bool("FCIE_RESPECT_ROBOTS", crawl_y.get("respect_robots", True)),
        max_sources_per_run=_env_int("FCIE_MAX_SOURCES_PER_RUN", crawl_y.get("max_sources_per_run", 60)),
        max_pages_per_podium_section=crawl_y.get("max_pages_per_podium_section", 12),
        user_agent=_secret("FCIE_USER_AGENT") or crawl_y.get("user_agent", CrawlConfig.user_agent),
    )
    ai = AIConfig(
        model=_secret("FCIE_OPENAI_MODEL") or ai_y.get("model", "gpt-4o-mini"),
        temperature=ai_y.get("temperature", 0.2),
        max_extraction_chars=ai_y.get("max_extraction_chars", 14000),
        enable_llm=ai_y.get("enable_llm", True),
    )

    return AppConfig(
        crawl=crawl,
        ai=ai,
        discovery=DiscoveryConfig(**{k: v for k, v in disc_y.items() if k in DiscoveryConfig.__dataclass_fields__}),
        trends=TrendConfig(**{k: v for k, v in trend_y.items() if k in TrendConfig.__dataclass_fields__}),
        pipeline=PipelineConfig(**{k: v for k, v in pipe_y.items() if k in PipelineConfig.__dataclass_fields__}),
        scoring=_read_yaml("scoring.yaml"),
        sources=_read_yaml("sources.yaml"),
        queries=_read_yaml("queries.yaml"),
        feeds=_read_yaml("feeds.yaml"),
        credentials=Credentials.from_env(),
    )


def reload_config() -> AppConfig:
    load_config.cache_clear()
    return load_config()
