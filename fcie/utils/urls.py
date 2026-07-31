"""URL normalisation and canonicalisation.

Canonical URLs are the primary deduplication key: the same article discovered
through three different search queries must resolve to one row in ``sources``.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Tracking parameters that never change the identity of a document.
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "gclid", "gclsrc", "dclid", "fbclid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "ref", "ref_src", "referrer", "source", "spm", "yclid",
    "_hsenc", "_hsmi", "hsCtaTracking", "vero_id", "wickedid", "sc_cid",
    "campaign_id", "ad_id", "adgroupid", "cmpid", "amp", "at_medium",
    # Paid-search / ad-platform parameters. Search APIs return the *ad* landing
    # URL, so one page comes back as ?device=c, ?m_bt=0, ?gad_source=1 … and
    # without these each variant looks like a distinct source.
    "device", "m_bt", "matchtype", "network", "creative", "keyword",
    "placement", "adposition", "gad_source", "gad_campaignid", "gbraid",
    "wbraid", "srsltid", "mkt_tok", "trk", "trkCampaign", "sfmc_id",
    "s_kwcid", "ef_id", "gclid_src", "li_fat_id", "twclid", "ttclid",
    "epik", "irclickid", "rdt_cid",
}

# Query params that DO change identity and must be preserved.
SIGNIFICANT_PARAMS = {"v", "id", "p", "page", "q", "story", "article", "post"}

DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_url(url: str | None) -> str:
    """Return a stable, comparable form of ``url``.

    - lowercases scheme and host, strips ``www.``
    - upgrades a bare host to https
    - drops the fragment
    - removes tracking parameters, sorts the rest
    - strips a trailing slash (except on the site root)
    - strips default ports and ``index.html``-style suffixes
    """
    if not url:
        return ""
    url = url.strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if "://" not in url:
        url = "https://" + url

    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    if scheme not in ("http", "https"):
        # mailto:, javascript:, etc. — return unchanged, caller will reject it
        return url

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    netloc = host
    if parts.port and str(parts.port) != DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{parts.port}"

    path = parts.path or "/"
    for index_name in ("/index.html", "/index.htm", "/index.php", "/default.aspx"):
        if path.lower().endswith(index_name):
            path = path[: -len(index_name)] + "/"
            break
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_pairs))

    # Everything is https for comparison purposes; http/https duplicates of the
    # same document are extremely common and are not distinct sources.
    return urlunsplit(("https", netloc, path, query, ""))


def canonicalize(url: str | None, declared_canonical: str | None = None) -> str:
    """Prefer a page's own ``<link rel=canonical>`` when it is on the same host."""
    normalized = normalize_url(url)
    if not declared_canonical:
        return normalized
    declared = normalize_url(declared_canonical)
    if not declared:
        return normalized
    if domain_of(declared) and domain_of(declared) == domain_of(normalized):
        return declared
    return normalized


def domain_of(url: str | None) -> str:
    """Registrable-ish host, without ``www.``. Empty string when unparseable."""
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def registrable_domain(url: str | None) -> str:
    """Last two labels of the host — good enough for grouping public sites."""
    host = domain_of(url)
    if not host:
        return ""
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    # Handle common two-part public suffixes without a full PSL dependency.
    two_part_suffixes = {"co.uk", "com.au", "co.nz", "co.jp", "com.br", "co.za"}
    if ".".join(labels[-2:]) in two_part_suffixes and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")


def is_http_url(url: str | None) -> bool:
    """True only for http/https. A bare host is assumed https; any other explicit
    scheme (``mailto:``, ``javascript:``, ``tel:``) is rejected."""
    if not url:
        return False
    url = url.strip()
    match = _SCHEME_RE.match(url)
    if match:
        return match.group(1).lower() in ("http", "https")
    return bool(url) and not url.startswith(("/", "#", "?"))


def is_allowed(url: str, allowed_domains: set[str], blocked_domains: set[str] | None = None) -> bool:
    """Allowlist check used before any first-party crawl request."""
    host = domain_of(url)
    if not host:
        return False
    blocked = blocked_domains or set()
    for b in blocked:
        b = b.lower().lstrip(".")
        if b.startswith("www."):
            b = b[4:]
        if host == b or host.endswith("." + b):
            return False
    for a in allowed_domains:
        a = a.lower().lstrip(".")
        if a.startswith("www."):
            a = a[4:]
        if host == a or host.endswith("." + a):
            return True
    return False


def same_site(a: str, b: str) -> bool:
    return bool(registrable_domain(a)) and registrable_domain(a) == registrable_domain(b)


def youtube_video_id(url: str) -> str | None:
    """Extract a YouTube video id from watch / youtu.be / shorts / embed URLs."""
    if not url:
        return None
    parts = urlsplit(url if "://" in url else "https://" + url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if host == "youtu.be":
        vid = parts.path.lstrip("/").split("/")[0]
        return vid or None
    if "youtube.com" not in host:
        return None
    if parts.path == "/watch":
        return dict(parse_qsl(parts.query)).get("v")
    for prefix in ("/shorts/", "/embed/", "/live/", "/v/"):
        if parts.path.startswith(prefix):
            return parts.path[len(prefix):].split("/")[0] or None
    return None
