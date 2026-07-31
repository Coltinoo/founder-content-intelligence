"""HTML → structured article. trafilatura first, BeautifulSoup as backstop."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from .text import clean_text, looks_promotional, word_count
from .urls import canonicalize, domain_of, normalize_url

log = logging.getLogger(__name__)

try:  # trafilatura is optional at import time so tests run without it
    import trafilatura
    from trafilatura.settings import use_config as _traf_config

    _TRAF_CFG = _traf_config()
    _TRAF_CFG.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
    HAS_TRAFILATURA = True
except Exception:  # pragma: no cover
    trafilatura = None
    _TRAF_CFG = None
    HAS_TRAFILATURA = False


@dataclass
class ParsedArticle:
    url: str
    canonical_url: str = ""
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    text: str = ""
    excerpt: str = ""
    site_name: str | None = None
    language: str | None = None
    links: list[str] = field(default_factory=list)
    extractor: str = "none"
    is_promotional: bool = False
    metadata: dict = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return word_count(self.text)


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        dt = date_parser.parse(str(value), fuzzy=False)
        # Reject nonsense years that fuzzy parsers sometimes produce.
        if dt.year < 1995 or dt.year > datetime.now().year + 1:
            return None
        return dt
    except (ValueError, TypeError, OverflowError):
        return None


def _first(*values):
    for v in values:
        if v:
            return v
    return None


def _jsonld_metadata(soup: BeautifulSoup) -> dict:
    """Pull headline/author/date out of schema.org JSON-LD when present."""
    out: dict = {}
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if "@graph" in item and isinstance(item["@graph"], list):
                items.extend(x for x in item["@graph"] if isinstance(x, dict))
                continue
            itype = str(item.get("@type", "")).lower()
            if not any(t in itype for t in ("article", "newsarticle", "blogposting",
                                            "webpage", "videoobject", "jobposting")):
                continue
            out.setdefault("title", item.get("headline") or item.get("name"))
            out.setdefault("published", item.get("datePublished") or item.get("uploadDate")
                           or item.get("datePosted"))
            author = item.get("author")
            if isinstance(author, dict):
                out.setdefault("author", author.get("name"))
            elif isinstance(author, list) and author:
                first = author[0]
                out.setdefault("author", first.get("name") if isinstance(first, dict) else str(first))
            elif isinstance(author, str):
                out.setdefault("author", author)
            out.setdefault("description", item.get("description"))
    return {k: v for k, v in out.items() if v}


def _meta(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def parse_html(html: str, url: str, *, collect_links: bool = False) -> ParsedArticle:
    """Extract readable text plus metadata from a fetched HTML document."""
    article = ParsedArticle(url=url, canonical_url=normalize_url(url))
    if not html:
        return article

    soup = BeautifulSoup(html, "lxml")
    jsonld = _jsonld_metadata(soup)

    declared_canonical = None
    link_tag = soup.find("link", attrs={"rel": lambda v: v and "canonical" in (v if isinstance(v, list) else [v])})
    if link_tag and link_tag.get("href"):
        declared_canonical = link_tag["href"]
    article.canonical_url = canonicalize(url, declared_canonical)

    article.title = _first(
        jsonld.get("title"),
        _meta(soup, "og:title", "twitter:title"),
        soup.title.get_text(strip=True) if soup.title else None,
        soup.h1.get_text(strip=True) if soup.h1 else None,
    )
    article.author = _first(
        jsonld.get("author"),
        _meta(soup, "article:author", "author", "byl", "twitter:creator"),
    )
    article.published_at = _parse_date(
        _first(
            jsonld.get("published"),
            _meta(soup, "article:published_time", "datePublished", "publish-date",
                  "og:published_time", "date", "DC.date.issued"),
            (soup.find("time").get("datetime") if soup.find("time") else None),
        )
    )
    article.site_name = _meta(soup, "og:site_name") or domain_of(url)
    article.excerpt = _first(jsonld.get("description"),
                             _meta(soup, "og:description", "description", "twitter:description")) or ""
    html_tag = soup.find("html")
    article.language = html_tag.get("lang") if html_tag else None

    # ── body text ───────────────────────────────────────────────────────
    text = ""
    if HAS_TRAFILATURA:
        try:
            text = trafilatura.extract(
                html,
                url=url,
                include_comments=False,
                include_tables=True,
                favor_precision=True,
                config=_TRAF_CFG,
            ) or ""
            if text:
                article.extractor = "trafilatura"
        except Exception as exc:  # pragma: no cover
            log.debug("trafilatura failed for %s: %s", url, exc)

    if len(text.split()) < 60:
        fallback = _soup_text(soup)
        if len(fallback.split()) > len(text.split()):
            text = fallback
            article.extractor = "beautifulsoup"

    article.text = clean_text(text)
    article.is_promotional = looks_promotional(article.text, domain_of(url))

    if collect_links:
        article.links = _collect_links(soup, url)

    article.metadata = {
        "extractor": article.extractor,
        "word_count": article.word_count,
        "declared_canonical": declared_canonical,
        "has_publication_date": article.published_at is not None,
        "language": article.language,
    }
    return article


def _soup_text(soup: BeautifulSoup) -> str:
    """Readable-text fallback: drop chrome, prefer <main>/<article>."""
    work = BeautifulSoup(str(soup), "lxml")
    for tag in work(["script", "style", "noscript", "nav", "header", "footer",
                     "form", "aside", "iframe", "svg", "button"]):
        tag.decompose()
    for selector in ("[role=navigation]", "[aria-hidden=true]", ".cookie-banner",
                     ".newsletter-signup", ".breadcrumbs"):
        for tag in work.select(selector):
            tag.decompose()

    container = work.find("article") or work.find("main") or work.body or work
    blocks: list[str] = []
    for element in container.find_all(["h1", "h2", "h3", "p", "li", "blockquote", "td"]):
        chunk = element.get_text(" ", strip=True)
        if len(chunk.split()) >= 4:
            blocks.append(chunk)
    if not blocks:
        return container.get_text(" ", strip=True)

    # Drop duplicated nav strings that repeat verbatim across the page.
    seen: set[str] = set()
    deduped = []
    for block in blocks:
        key = block.lower()[:100]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(block)
    return "\n\n".join(deduped)


_SKIP_LINK_PATTERNS = re.compile(
    r"(/privacy|/terms|/legal|/cookie|/login|/signin|/sign-in|/signup|/sign-up|"
    r"/demo|/pricing|/contact|/careers/apply|\.pdf$|\.zip$|/cdn-cgi/|#)",
    flags=re.IGNORECASE,
)


def _collect_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """In-domain content links worth following during a section crawl."""
    from urllib.parse import urljoin

    base_domain = domain_of(base_url)
    found: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        if domain_of(absolute) != base_domain:
            continue
        if _SKIP_LINK_PATTERNS.search(absolute):
            continue
        normalized = normalize_url(absolute)
        if normalized in seen or normalized == normalize_url(base_url):
            continue
        seen.add(normalized)
        found.append(normalized)
    return found
