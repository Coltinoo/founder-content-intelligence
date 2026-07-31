"""Human-readable formatting helpers.

Small, but they decide whether the product reads like software or like a
spreadsheet dump. "8 public source(s) across 5 domain(s)" is the latter.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Industry and label strings are stored in a canonical form that does not always
# survive .lower() / .title() intact.
_CASING = {
    "b2b saas": "B2B SaaS",
    "saas": "SaaS",
    "ai": "AI",
    "hvac": "HVAC",
    "smb": "SMB",
    "cx": "CX",
    "roi": "ROI",
    "aesthetics & medspa": "aesthetics & medspa",
    "local business (general)": "local business",
    "cross-industry": "cross-industry",
    "home services": "home services",
    "automotive": "automotive",
    "healthcare": "healthcare",
    "retail": "retail",
    "professional services": "professional services",
}


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """``3, "source"`` → ``"sources"``. No "(s)"."""
    if count == 1:
        return singular
    return plural or (singular + "s")


def count_label(count: int, singular: str, plural: str | None = None) -> str:
    """``3, "source"`` → ``"3 sources"``."""
    return f"{count:,} {pluralize(count, singular, plural)}"


def industry_phrase(industries: list[str], limit: int = 2) -> str:
    """``["Automotive","Home services"]`` → ``"automotive and home services"``.

    Returns an empty string when there is nothing worth naming, so callers can
    concatenate without producing a dangling "in ".
    """
    names = [
        _CASING.get(i.strip().lower(), i.strip().lower())
        for i in (industries or [])
        if i and i.strip().lower() not in ("cross-industry", "")
    ]
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    unique = [n for n in names if not (n in seen or seen.add(n))][:limit]
    if not unique:
        return ""
    if len(unique) == 1:
        return unique[0]
    return " and ".join(unique)


def humanize_label(text: str | None) -> str:
    """``"short_form_video_outline"`` → ``"Short-form video outline"``."""
    if not text:
        return "—"
    words = str(text).replace("_", " ").replace("-", " ").strip()
    if not words:
        return "—"
    fixed = _CASING.get(words.lower())
    if fixed:
        return fixed[0].upper() + fixed[1:]
    out = words[0].upper() + words[1:]
    for low, proper in (("ai", "AI"), ("saas", "SaaS"), ("roi", "ROI"),
                        ("hvac", "HVAC"), ("smb", "SMB"), ("cx", "CX")):
        out = " ".join(proper if w.lower() == low else w for w in out.split())
    return out


def relative_time(value: datetime | None) -> str:
    """``"3 days ago"``, or ``"no date"`` when the source never carried one."""
    if value is None:
        return "no date"
    if isinstance(value, str):
        return value[:10]
    reference = datetime.now(timezone.utc)
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    delta = reference - moment
    seconds = delta.total_seconds()
    if seconds < 0:
        return "just now"
    if seconds < 3600:
        minutes = max(int(seconds // 60), 1)
        return f"{count_label(minutes, 'min')} ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{count_label(hours, 'hour')} ago"
    days = int(seconds // 86400)
    if days < 31:
        return "today" if days == 0 else f"{count_label(days, 'day')} ago"
    months = days // 30
    if months < 12:
        return f"{count_label(months, 'month')} ago"
    return f"{count_label(days // 365, 'year')} ago"


def truncate_words(text: str | None, limit: int) -> str:
    words = (text or "").split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(".,;:") + "…"


def strip_inference_prefix(text: str | None) -> str:
    """Remove the ``[Inference — …]`` marker for display in prose contexts.

    The marker exists so a reviewer can see the seam between evidence and
    interpretation. Where the UI already renders that distinction visually
    (an amber-ruled block labelled as interpretation), repeating it inline is
    noise.
    """
    import re

    return re.sub(r"^\s*\[Inference[^\]]*\]\s*", "", text or "").strip()
