"""Text cleaning, sentence handling, and verbatim-quote verification.

The verbatim helpers are the technical backbone of the anti-hallucination rules:
every quote and evidence passage stored in the database is checked against the
source text before it is written, and marked ``verified_verbatim`` accordingly.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

_MULTI_NEWLINE = re.compile(r"\n{3,}")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'“(])")
_NUMBER = re.compile(
    r"(?<![\w.])"
    r"(\$?\d[\d,]*\.?\d*\s?(?:%|percent|x|bn|billion|million|k\b|hours?|minutes?|days?|"
    r"seconds?|customers?|businesses?|dealerships?|locations?|leads?|calls?)?)",
    flags=re.IGNORECASE,
)
_QUOTE_PATTERN = re.compile(r"[“\"]([^”\"]{25,400})[”\"]")
_ATTRIBUTION = re.compile(
    r"(?:said|says|according to|explained|noted|told|adds|added)\s+"
    r"([A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){0,3})"
)

PROMOTIONAL_MARKERS = (
    "request a demo", "book a demo", "start free trial", "get started free",
    "talk to sales", "sign up today", "our platform helps", "trusted by",
    "schedule a demo", "contact sales", "see pricing", "watch the demo",
)


def normalize_unicode(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return text.replace(" ", " ").replace("\r\n", "\n").replace("\r", "\n")


def clean_text(text: str | None) -> str:
    """Collapse whitespace and drop obvious navigation noise. Non-destructive:
    the original stays in ``sources.raw_text``."""
    text = normalize_unicode(text)
    if not text:
        return ""
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        # Drop very short all-caps nav crumbs and lone menu words.
        if len(stripped) < 3:
            continue
        lines.append(_MULTI_SPACE.sub(" ", stripped))
    joined = "\n".join(lines)
    return _MULTI_NEWLINE.sub("\n\n", joined).strip()


def word_count(text: str | None) -> int:
    return len((text or "").split())


def truncate(text: str | None, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " …"


def sentences(text: str | None) -> list[str]:
    text = clean_text(text).replace("\n", " ")
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if len(s.strip()) > 2]


# ── Verbatim verification ───────────────────────────────────────────────────

def _loose(text: str) -> str:
    """Whitespace/quote-insensitive form for containment checks."""
    t = normalize_unicode(text).lower()
    t = t.replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def is_verbatim(passage: str | None, source_text: str | None) -> bool:
    """True when ``passage`` appears in ``source_text`` ignoring whitespace and
    curly/straight quote differences. Used to gate every stored quote."""
    if not passage or not source_text:
        return False
    p = _loose(passage).strip("\"'.,;: ")
    if len(p) < 12:
        return False
    return p in _loose(source_text)


def locate_passage(passage: str, source_text: str) -> tuple[int, int] | None:
    """Character offsets of ``passage`` in the ORIGINAL text, or None."""
    if not passage or not source_text:
        return None
    idx = source_text.find(passage)
    if idx >= 0:
        return idx, idx + len(passage)
    loose_source = _loose(source_text)
    loose_passage = _loose(passage)
    idx = loose_source.find(loose_passage)
    if idx < 0:
        return None
    # Approximate mapping back — good enough for a highlight anchor.
    ratio = len(source_text) / max(len(loose_source), 1)
    start = int(idx * ratio)
    return start, min(len(source_text), start + len(passage))


def extract_quotes(text: str | None, limit: int = 6) -> list[dict]:
    """Pull verbatim quoted passages out of ``text``.

    Quotes are *sliced from the source*, never paraphrased or reconstructed.
    Each result carries ``verified_verbatim`` proven by re-checking containment.
    """
    if not text:
        return []
    results: list[dict] = []
    seen: set[str] = set()
    for match in _QUOTE_PATTERN.finditer(text):
        quote = match.group(1).strip()
        key = _loose(quote)
        if key in seen or len(quote.split()) < 6:
            continue
        seen.add(key)
        window = text[max(0, match.start() - 160) : min(len(text), match.end() + 160)]
        attribution = _ATTRIBUTION.search(window)
        results.append(
            {
                "quote": quote,
                "speaker": attribution.group(1) if attribution else None,
                "char_start": match.start(1),
                "char_end": match.end(1),
                "verified_verbatim": is_verbatim(quote, text),
            }
        )
        if len(results) >= limit:
            break
    return results


def extract_numerical_claims(text: str | None, limit: int = 8) -> list[dict]:
    """Find numbers together with the sentence that gives them context.

    Statistics always keep their original sentence so they can never be
    re-presented out of context.
    """
    if not text:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for sentence in sentences(text):
        # A figure is only a claim inside a real sentence. Feature lists and nav
        # rows ("Reviews 22, Payments 30,") are not statistics.
        if not looks_like_prose(sentence):
            continue
        for match in _NUMBER.finditer(sentence):
            # The character class permits a trailing comma, so "22," can be
            # captured from a list. Trim punctuation before any other test.
            value = match.group(1).strip().rstrip(".,;:")
            if not value or not any(ch.isdigit() for ch in value):
                continue
            bare = value.replace(",", "").replace("$", "")
            # Ignore bare years and tiny integers with no unit.
            if re.fullmatch(r"(19|20)\d{2}", bare):
                continue
            if re.fullmatch(r"\d{1,2}", value):
                continue
            # A comma-grouped integer must be properly grouped ("1,200" yes;
            # "22," no) — otherwise it is list punctuation, not a figure.
            if "," in value and not re.fullmatch(r"\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?\s?\D*", value):
                continue
            key = f"{value}|{sentence[:60]}"
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "value": value,
                    "context": sentence.strip(),
                    "verified_verbatim": is_verbatim(sentence, text),
                    "needs_verification": True,  # every number needs a primary check
                }
            )
            if len(out) >= limit:
                return out
    return out


# Navigation, CTA and chrome text that survives body extraction on marketing
# pages. A passage containing any of these is not evidence of anything.
_CHROME_MARKERS = (
    "watch a demo", "watch demo", "book a demo", "request a demo", "schedule a demo",
    "get started", "start free", "sign up", "log in", "learn more", "read more",
    "see how it works", "talk to sales", "contact sales", "get pricing",
    "integrates with the tools", "works with your systems", "trusted by",
    "all rights reserved", "privacy policy", "terms of service", "cookie",
    "skip to content", "back to top", "share this", "subscribe",
    "follow us", "download the", "view all", "explore our", "browse",
)

# Fragment/heading patterns: a heading is not a claim.
_HEADING_LIKE = re.compile(r"^[A-Z0-9][A-Za-z0-9 &/,'’-]{0,60}$")
_HAS_TERMINAL_PUNCT = re.compile(r"[.!?][\"'”’)]?\s*$")


_VOWELS = set("aeiouy")
# Function words that appear in essentially any real English sentence.
_STOPWORDS = {
    "the", "and", "of", "to", "a", "in", "is", "that", "for", "it", "with", "on",
    "as", "are", "was", "at", "be", "by", "this", "from", "or", "an", "we", "you",
    "they", "has", "have", "their", "its", "but", "not", "can", "will", "more",
}


def looks_like_gibberish(sentence: str) -> bool:
    """Detect scrambled or obfuscated text.

    Some publishers serve character-substituted body text to clients they do not
    recognise ("Gfh ifkgzgg hcfapv rmr rukbtc ahb phehadg"). It is verbatim in
    the fetched document, so the verbatim gate passes it — but quoting it as
    evidence would be absurd. Two independent signals: words with no vowel at
    all, and a total absence of English function words.
    """
    words = [w.strip(".,;:!?\"'()").lower() for w in (sentence or "").split()]
    words = [w for w in words if w.isalpha() and len(w) > 1]
    if len(words) < 8:
        return False

    vowelless = sum(1 for w in words if not (_VOWELS & set(w)))
    if vowelless / len(words) > 0.15:
        return True
    if not any(w in _STOPWORDS for w in words):
        return True
    return False


def looks_like_prose(sentence: str) -> bool:
    """True when a sentence reads like an actual claim rather than page chrome.

    Body extraction on marketing sites leaks nav labels, CTA buttons and
    all-caps banners. Those are grammatically shaped like sentences but assert
    nothing, and quoting them as evidence is worse than having no evidence.
    """
    stripped = sentence.strip()
    words = stripped.split()
    if len(words) < 6:
        return False
    low = stripped.lower()

    if any(marker in low for marker in _CHROME_MARKERS):
        return False
    if not _HAS_TERMINAL_PUNCT.search(stripped):
        return False
    if _HEADING_LIKE.match(stripped):
        return False
    if looks_like_gibberish(stripped):
        return False

    # Shouty banner text ("#1 AI OPERATING SYSTEM FOR HOME SERVICES").
    shouty = sum(1 for w in words if len(w) > 2 and w.isupper())
    if shouty >= 3 or shouty / len(words) > 0.3:
        return False

    # Title-Case Navigation Strings capitalise nearly every word.
    capitalised = sum(1 for w in words[1:] if w[:1].isupper())
    if capitalised / max(len(words) - 1, 1) > 0.6:
        return False

    # Needs at least a few ordinary lowercase words to be a real sentence.
    if sum(1 for w in words if w.islower() and len(w) > 2) < 3:
        return False
    return True


def select_evidence_passages(
    text: str | None,
    keywords: list[str],
    limit: int = 5,
    min_words: int = 10,
    *,
    priority_keywords: list[str] | None = None,
) -> list[dict]:
    """Return the sentences that best support ``keywords``, verbatim.

    ``priority_keywords`` (the matched theme vocabulary) are weighted far more
    heavily than the generic fallback list, so a sentence that merely contains
    the word "revenue" cannot outrank one that actually discusses the theme.
    Page chrome is rejected outright by :func:`looks_like_prose`.
    """
    if not text:
        return []
    keys = [k.lower() for k in keywords if k]
    priority = [k.lower() for k in (priority_keywords or []) if k]
    scored: list[tuple[float, str]] = []

    for sentence in sentences(text):
        words = sentence.split()
        if len(words) < min_words or len(words) > 90:
            continue
        if not looks_like_prose(sentence):
            continue
        low = sentence.lower()

        priority_hits = sum(1 for k in priority if k in low)
        generic_hits = sum(1 for k in keys if k in low)
        if not (priority_hits or generic_hits):
            continue

        score = priority_hits * 4.0 + generic_hits * 1.0
        if priority and not priority_hits:
            # Generic-keyword-only matches are weak evidence for this theme.
            score -= 2.0
        if _NUMBER.search(sentence):
            score += 1.5
        if any(m in low for m in PROMOTIONAL_MARKERS):
            score -= 2.5
        score -= len(words) / 120.0
        scored.append((score, sentence.strip()))

    scored = [pair for pair in scored if pair[0] > 0]

    scored.sort(key=lambda pair: pair[0], reverse=True)
    out: list[dict] = []
    seen: set[str] = set()
    for _score, sentence in scored:
        key = _loose(sentence)[:80]
        if key in seen:
            continue
        seen.add(key)
        span = locate_passage(sentence, text)
        out.append(
            {
                "passage": sentence,
                "char_start": span[0] if span else None,
                "char_end": span[1] if span else None,
                "verified_verbatim": is_verbatim(sentence, text),
            }
        )
        if len(out) >= limit:
            break
    return out


def looks_promotional(text: str | None, domain: str = "") -> bool:
    """Flag vendor marketing so its evidence weight can be discounted."""
    if not text:
        return False
    low = text.lower()
    hits = sum(1 for marker in PROMOTIONAL_MARKERS if marker in low)
    return hits >= 2 or (hits >= 1 and word_count(text) < 400)


def to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def naive_utc(dt: datetime | None) -> datetime | None:
    """SQLite stores naive datetimes; normalise everything to naive UTC."""
    dt = to_utc(dt)
    return dt.replace(tzinfo=None) if dt else None
