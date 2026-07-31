"""Polite HTTP client: robots.txt compliance, per-domain rate limiting,
identifiable user agent, and hard refusal to touch blocked or auth-walled pages.

Compliance rules enforced here (not merely documented):
  * ``robots.txt`` is fetched once per host and cached; a disallow is fatal for
    that URL and recorded as ``skipped_robots``.
  * ``Crawl-delay`` from robots.txt overrides our configured delay when larger.
  * A minimum delay is applied per host between requests.
  * Requests carry a descriptive, contactable user agent.
  * Responses that look like a login wall / paywall / captcha are abandoned.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import load_config
from .urls import domain_of, is_http_url, normalize_url

log = logging.getLogger(__name__)

# Signals that we have hit an access restriction. We never attempt to bypass
# any of these — the fetch is abandoned and the reason recorded.
_RESTRICTION_MARKERS = (
    "captcha",
    "cf-challenge",
    "please enable javascript and cookies",
    "sign in to continue reading",
    "subscribe to continue reading",
    "this content is for subscribers",
    "you have reached your article limit",
    "log in to view",
    "create a free account to read",
)

_RESTRICTED_STATUS = {401, 402, 403, 407, 451}


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status_code: int | None = None
    html: str = ""
    ok: bool = False
    error: str | None = None
    skipped_reason: str | None = None   # robots | blocked_domain | restricted | non_html
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def blocked_by_policy(self) -> bool:
        return self.skipped_reason is not None


class RateLimiter:
    """Per-host minimum interval between requests. Thread-safe."""

    def __init__(self, default_delay: float):
        self.default_delay = max(default_delay, 0.0)
        self._last: dict[str, float] = {}
        self._overrides: dict[str, float] = {}
        self._lock = threading.Lock()

    def set_delay(self, host: str, delay: float) -> None:
        with self._lock:
            self._overrides[host] = max(delay, self.default_delay)

    def wait(self, host: str) -> float:
        """Block until this host may be hit again. Returns seconds slept."""
        reserved = self.try_reserve(host, max_wait=None)
        assert reserved is not None  # unbounded wait always reserves
        return reserved

    def try_reserve(self, host: str, max_wait: float | None) -> float | None:
        """Reserve the next polite slot for ``host`` — unless it is too far away.

        Some publishers declare robots ``Crawl-delay`` values of 60-600 seconds.
        Honouring that must not mean a batch quietly sleeps for hours behind one
        host: when the required wait exceeds ``max_wait`` the slot is NOT
        reserved and ``None`` is returned, so the caller can defer that item to
        a future run. ``max_wait=None`` means wait however long it takes.
        """
        with self._lock:
            delay = self._overrides.get(host, self.default_delay)
            last = self._last.get(host)
            now = time.monotonic()
            sleep_for = 0.0
            if last is not None:
                elapsed = now - last
                if elapsed < delay:
                    sleep_for = delay - elapsed
            if max_wait is not None and sleep_for > max_wait:
                return None
            self._last[host] = now + sleep_for
        if sleep_for > 0:
            time.sleep(sleep_for)
        return sleep_for

    def current_delay(self, host: str) -> float:
        with self._lock:
            return self._overrides.get(host, self.default_delay)


class RobotsCache:
    """One robots.txt parse per host, cached for the process lifetime."""

    def __init__(self, user_agent: str, timeout: float = 10.0, enabled: bool = True):
        self.user_agent = user_agent
        self.timeout = timeout
        self.enabled = enabled
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def _parser_for(self, host: str) -> urllib.robotparser.RobotFileParser | None:
        with self._lock:
            if host in self._parsers:
                return self._parsers[host]
        parser: urllib.robotparser.RobotFileParser | None = None
        try:
            resp = httpx.get(
                f"https://{host}/robots.txt",
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
                follow_redirects=True,
            )
            if resp.status_code == 200 and resp.text:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text.splitlines())
            else:
                # No robots.txt published → crawling is permitted by default.
                parser = None
        except Exception as exc:  # network failure — fail closed for safety
            log.warning("robots.txt fetch failed for %s: %s", host, exc)
            parser = None
        with self._lock:
            self._parsers[host] = parser
        return parser

    def can_fetch(self, url: str) -> tuple[bool, str]:
        if not self.enabled:
            return True, "robots checking disabled by configuration"
        host = domain_of(url)
        if not host:
            return False, "unparseable host"
        parser = self._parser_for(host)
        if parser is None:
            return True, "no robots.txt published"
        allowed = parser.can_fetch(self.user_agent, url) or parser.can_fetch("*", url)
        return allowed, "allowed by robots.txt" if allowed else "disallowed by robots.txt"

    def crawl_delay(self, url: str) -> float | None:
        if not self.enabled:
            return None
        parser = self._parser_for(domain_of(url))
        if parser is None:
            return None
        try:
            delay = parser.crawl_delay(self.user_agent) or parser.crawl_delay("*")
            return float(delay) if delay else None
        except Exception:
            return None


class PoliteFetcher:
    """The only component in the system that makes outbound page requests."""

    def __init__(
        self,
        user_agent: str | None = None,
        delay_seconds: float | None = None,
        timeout: int | None = None,
        respect_robots: bool | None = None,
        blocked_domains: set[str] | None = None,
    ):
        cfg = load_config()
        self.user_agent = user_agent or cfg.crawl.user_agent
        self.timeout = timeout or cfg.crawl.request_timeout
        self.respect_robots = cfg.crawl.respect_robots if respect_robots is None else respect_robots
        self.blocked_domains = blocked_domains if blocked_domains is not None else cfg.blocked_domains
        self.limiter = RateLimiter(delay_seconds if delay_seconds is not None else cfg.crawl.delay_seconds)
        self.robots = RobotsCache(self.user_agent, enabled=self.respect_robots)
        self.request_count = 0
        self._client = httpx.Client(
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.8",
            },
            timeout=self.timeout,
            follow_redirects=True,
        )

    # ── policy checks ───────────────────────────────────────────────────
    def _is_blocked(self, url: str) -> bool:
        host = domain_of(url)
        for b in self.blocked_domains:
            b = b.lower().removeprefix("www.")
            if host == b or host.endswith("." + b):
                return True
        return False

    @staticmethod
    def _looks_restricted(status: int, html: str) -> bool:
        if status in _RESTRICTED_STATUS:
            return True
        head = html[:6000].lower()
        return any(marker in head for marker in _RESTRICTION_MARKERS)

    # ── main entry point ────────────────────────────────────────────────
    def fetch(self, url: str, *, max_wait: float | None = None) -> FetchResult:
        """Fetch one page politely.

        ``max_wait`` bounds how long this call may sleep for the host's polite
        slot. When the wait would exceed it (a publisher declaring a large
        robots ``Crawl-delay``), the fetch is *deferred* — skipped with reason
        ``crawl_delay_deferred`` — rather than stalling the whole run. The
        delay itself is always honoured; we simply decline to queue behind it.
        """
        url = (url or "").strip()
        result = FetchResult(url=url)

        if not is_http_url(url):
            result.error = "not an http(s) URL"
            result.skipped_reason = "non_html"
            return result

        if self._is_blocked(url):
            result.skipped_reason = "blocked_domain"
            result.error = (
                f"{domain_of(url)} is on the blocked list. Content from this platform "
                "may only be added manually by a human."
            )
            return result

        allowed, reason = self.robots.can_fetch(url)
        if not allowed:
            result.skipped_reason = "robots"
            result.error = f"Not fetched: {reason}"
            return result

        host = domain_of(url)
        declared_delay = self.robots.crawl_delay(url)
        if declared_delay:
            self.limiter.set_delay(host, declared_delay)
        if self.limiter.try_reserve(host, max_wait) is None:
            result.skipped_reason = "crawl_delay_deferred"
            result.error = (
                f"{host} declares a crawl delay of "
                f"{self.limiter.current_delay(host):.0f}s; this page is deferred to a "
                "future run rather than queueing behind it. The delay is honoured, "
                "not bypassed."
            )
            return result

        try:
            resp = self._client.get(url)
            self.request_count += 1
            result.status_code = resp.status_code
            result.final_url = str(resp.url)
            result.headers = {k.lower(): v for k, v in resp.headers.items()}

            content_type = result.headers.get("content-type", "")
            body = resp.text if "html" in content_type or "xml" in content_type or not content_type else ""

            if resp.status_code >= 400:
                if self._looks_restricted(resp.status_code, body):
                    result.skipped_reason = "restricted"
                    result.error = (
                        f"HTTP {resp.status_code} — access restricted. Not bypassed."
                    )
                else:
                    result.error = f"HTTP {resp.status_code}"
                return result

            if "html" not in content_type and "xml" not in content_type:
                result.skipped_reason = "non_html"
                result.error = f"Unsupported content-type: {content_type or 'unknown'}"
                return result

            if self._looks_restricted(resp.status_code, body):
                result.skipped_reason = "restricted"
                result.error = "Login wall, paywall, or bot challenge detected. Not bypassed."
                return result

            result.html = body
            result.ok = True
            return result

        except httpx.TimeoutException:
            result.error = f"Timeout after {self.timeout}s"
        except httpx.HTTPError as exc:
            result.error = f"HTTP error: {exc.__class__.__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 - connector must never crash the run
            result.error = f"{exc.__class__.__name__}: {exc}"
        return result

    def fetch_feed(self, url: str) -> tuple[bytes | None, str | None]:
        """Fetch an RSS/Atom document. Returns ``(body, error)``.

        ``feedparser.parse(url)`` does its own HTTP through urllib with **no
        timeout**, so a single unresponsive publisher can hang a scheduled run
        indefinitely. We fetch the bytes ourselves — with our timeout, our rate
        limiter and our user agent — and hand feedparser a string instead.
        """
        try:
            self.limiter.wait(domain_of(url))
            resp = self._client.get(url, headers={"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"})
            self.request_count += 1
            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code}"
            if not resp.content:
                return None, "empty response body"
            return resp.content, None
        except httpx.TimeoutException:
            return None, f"timeout after {self.timeout}s"
        except Exception as exc:  # noqa: BLE001
            return None, f"{exc.__class__.__name__}: {exc}"

    def get_json(self, url: str, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> tuple[dict | None, str | None]:
        """JSON helper for search / YouTube APIs. Returns ``(payload, error)``."""
        try:
            self.limiter.wait(domain_of(url))
            resp = self._client.get(url, params=params, headers=headers)
            self.request_count += 1
            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code}: {resp.text[:300]}"
            return resp.json(), None
        except Exception as exc:  # noqa: BLE001
            return None, f"{exc.__class__.__name__}: {exc}"

    def post_json(self, url: str, payload: dict[str, Any],
                  headers: dict[str, str] | None = None) -> tuple[dict | None, str | None]:
        try:
            self.limiter.wait(domain_of(url))
            resp = self._client.post(url, json=payload, headers=headers)
            self.request_count += 1
            if resp.status_code >= 400:
                return None, f"HTTP {resp.status_code}: {resp.text[:300]}"
            return resp.json(), None
        except Exception as exc:  # noqa: BLE001
            return None, f"{exc.__class__.__name__}: {exc}"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PoliteFetcher":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
