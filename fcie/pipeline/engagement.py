"""Engagement watchlist.

Surfaces public conversations a human may want to review. The system never
comments, likes, reposts, follows, connects, or messages — it produces a queue
and stops. Every item points at a source URL we already hold; no profile URL is
ever constructed or looked up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..ai.client import AIClient
from ..ai.prompts import load_prompt
from ..config import load_config
from ..db import session_scope
from ..models import EngagementWatchlistItem, ExtractedSignal, Source, Theme
from ..utils.text import truncate

log = logging.getLogger(__name__)

# Platforms whose public conversations must never be automated against.
NO_AUTOMATION_NOTE = (
    "Review only. Do not automate any comment, like, repost, follow, connection, "
    "or message. A human decides and acts."
)


@dataclass
class EngagementReport:
    created: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    backend: str = "heuristic-v1"

    def as_dict(self) -> dict:
        return {"created": self.created, "skipped": self.skipped,
                "rejected": len(self.rejected),
                "errors": self.errors[:20], "backend": self.backend}


# Pages that are not conversations. A watchlist is a list of *people and
# discussions worth joining*; a job posting, a pricing page or the company's own
# site is none of those. Twenty-four loosely-related rows are worse than five
# real ones, because the reader stops trusting the queue.
_NEVER_ENGAGE_DOMAINS = {
    "podium.com", "job-boards.greenhouse.io", "boards.greenhouse.io",
    "lever.co", "workday.com", "myworkdayjobs.com", "indeed.com",
    "glassdoor.com", "ziprecruiter.com",
}
_NEVER_ENGAGE_PATH_MARKERS = (
    "/jobs/", "/job/", "/careers", "/pricing", "/legal", "/privacy", "/terms",
    "/login", "/signup", "/demo", "/product/", "/solutions/", "/integrations",
    "/press-kit", "/newsroom",
    # Social profile and company pages are destinations, not discussions.
    "/company/", "/school/", "/showcase/",
)

# Social platforms are the exception to the domain rule above. linkedin.com used
# to sit in that set, described as a company/job-board domain — true when the
# only LinkedIn URLs in the corpus were company pages and job ads, and wrong now
# that the social channel surfaces public posts. A post is the single most likely
# thing worth a reply, so the test is the URL shape rather than the host.
_SOCIAL_HOSTS = ("linkedin.com", "x.com", "twitter.com")
_SOCIAL_CONVERSATION_MARKERS = ("/posts/", "/pulse/", "/status/", "/feed/update/")
# Minimum relevance for a conversation to be worth a founder's limited attention.
_MIN_ENGAGEMENT_RELEVANCE = 6.0


def _not_an_engagement_target(source: Source, signal: ExtractedSignal) -> str | None:
    """Return a reason to exclude, or None if this is a genuine conversation."""
    domain = (source.source_domain or "").lower()
    url = (source.canonical_url or "").lower()

    for blocked in _NEVER_ENGAGE_DOMAINS:
        if domain == blocked or domain.endswith("." + blocked):
            return f"{blocked} is a company/job-board domain, not a conversation"

    # On a social platform, only an actual post or article is a conversation.
    # A profile or a company page is somewhere to go, not something to reply to.
    if any(domain == h or domain.endswith("." + h) for h in _SOCIAL_HOSTS):
        if not any(marker in url for marker in _SOCIAL_CONVERSATION_MARKERS):
            return "social profile or landing page rather than a post"
    if domain.endswith(".podium.com"):
        return "Podium's own property"
    if any(marker in url for marker in _NEVER_ENGAGE_PATH_MARKERS):
        return "job listing, pricing or product page rather than a discussion"
    if signal.is_promotional_source:
        return "vendor marketing — engaging reads as a vendor spat"
    if (signal.podium_relevance or 0) < _MIN_ENGAGEMENT_RELEVANCE:
        return (f"relevance {signal.podium_relevance or 0:.0f}/10 is below the "
                f"{_MIN_ENGAGEMENT_RELEVANCE:.0f} bar for engagement")
    if not (source.author or "").strip() and not source.published_at:
        return "no named author and no publication date — not attributable to anyone"
    return None


def build_watchlist(*, limit: int = 6, lookback_days: int | None = None,
                    force_heuristic: bool = False) -> EngagementReport:
    """Build a short queue of genuine conversations.

    The cap is deliberately small. Five relevant items a founder's associate
    actually works through beats twenty-four they scroll past.
    """
    cfg = load_config()
    report = EngagementReport()
    lookback = lookback_days or cfg.discovery.lookback_days
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback)

    with session_scope() as session:
        rising = {
            t.name for t in session.execute(
                select(Theme).where(Theme.trend_status.in_(["rising", "emerging"]))
            ).scalars().all()
        }
        rows = session.execute(
            select(Source, ExtractedSignal)
            .join(ExtractedSignal, ExtractedSignal.source_id == Source.id)
            .where(ExtractedSignal.podium_relevance >= 4.0)
            # Relevance first, not opportunity_score. The pre-filter used to
            # take the top `limit * 4` rows by opportunity_score, which is
            # dominated by long articles — a social post is a search snippet, so
            # it scores low on evidence strength and never entered the pool at
            # all. Engagement is about whether a conversation is worth joining,
            # which is relevance, not article quality. The pool is also much
            # wider now; `_not_an_engagement_target` and the relevance bar below
            # do the real filtering, and this only has to not exclude things
            # before they are considered.
            .order_by(ExtractedSignal.podium_relevance.desc(),
                      ExtractedSignal.opportunity_score.desc())
            .limit(max(limit * 30, 120))
        ).all()

        candidates = []
        for source, signal in rows:
            effective = source.published_at or source.discovered_at
            if effective and effective < cutoff:
                continue
            rejection = _not_an_engagement_target(source, signal)
            if rejection:
                report.rejected.append(f"{source.source_domain}: {rejection}")
                continue
            candidates.append({
                "source": source, "signal": signal,
                "is_rising": (signal.primary_theme in rising)
                             or bool(rising & set(signal.secondary_themes or [])),
            })

        # Rank by how much of a real conversation this is, not just by score.
        candidates.sort(
            key=lambda c: (
                not c["is_rising"],
                not bool(c["source"].author),          # a named author beats a page
                -(c["signal"].podium_relevance or 0),
            )
        )

        client = AIClient()
        use_llm = client.available and not force_heuristic
        report.backend = client.model if use_llm else "heuristic-v1"

        llm_items = {}
        if use_llm and candidates:
            llm_items = _llm_watchlist(client, candidates[:limit], rising)

        existing_urls = {
            row[0] for row in session.execute(
                select(EngagementWatchlistItem.profile_or_source_url)
            ).all()
        }

        for candidate in candidates[:limit]:
            source, signal = candidate["source"], candidate["signal"]
            if source.canonical_url in existing_urls:
                report.skipped += 1
                continue

            llm = llm_items.get(source.id, {})
            entity = (
                llm.get("person_or_company")
                or source.author
                or (source.metadata_json or {}).get("feed_name")
                or source.source_domain
            )
            topic = llm.get("topic") or signal.primary_theme or "Unclassified"
            recent = llm.get("recent_signal") or truncate(
                signal.primary_claim or signal.customer_problem or source.title or "", 260
            )
            why = llm.get("why_relevant") or (
                f"Podium relevance {signal.podium_relevance}/10, founder relevance "
                f"{signal.founder_relevance}/10, evidence strength {signal.evidence_strength}/10."
                + (" This theme is currently rising." if candidate["is_rising"] else "")
            )
            connection = llm.get("podium_connection") or _connection(signal)
            angle = llm.get("suggested_response_angle") or _angle(signal, source)
            priority = llm.get("priority") or _priority(signal, candidate["is_rising"])

            risk_bits = [NO_AUTOMATION_NOTE]
            if llm.get("risk_notes"):
                risk_bits.insert(0, str(llm["risk_notes"]))
            if signal.is_promotional_source:
                risk_bits.insert(0, "Source is vendor marketing — engaging may read as a vendor spat.")
            if (signal.secondary_entities or []) and signal.risk_score >= 40:
                risk_bits.insert(0, f"Risk score {signal.risk_score}/100; named third parties present.")

            session.add(EngagementWatchlistItem(
                person_or_company=str(entity),
                profile_or_source_url=source.canonical_url,
                source_id=source.id,
                topic=topic,
                recent_signal=recent,
                why_relevant=why,
                podium_connection=connection,
                suggested_response_angle=angle,
                priority=priority,
                risk_notes=" ".join(risk_bits),
                discovered_at=datetime.now(timezone.utc).replace(tzinfo=None),
                review_status="unreviewed",
            ))
            report.created += 1

    return report


def _connection(signal: ExtractedSignal) -> str:
    industries = signal.industries or []
    core = {"Automotive", "Home services", "Aesthetics & medspa", "Healthcare", "Retail"}
    if core & set(industries):
        return f"Directly in Podium's served industries: {', '.join(sorted(core & set(industries)))}."
    if (signal.podium_relevance or 0) >= 7:
        return "Directly relevant to Podium's category (AI agents for local-business revenue)."
    return "Adjacent only — the connection is thematic, not a direct market overlap."


def _angle(signal: ExtractedSignal, source: Source) -> str:
    problem = signal.customer_problem or signal.primary_claim
    if problem:
        return (
            "Add the operator's view: ask what the piece measured and over what period. "
            f"The claim to press on is “{truncate(problem, 160)}”. "
            "No pitch, no link — a distinction or a real question only."
        )
    return (
        "Only worth engaging if a specific operational point can be added. Otherwise skip — "
        "a generic reply costs credibility."
    )


def _priority(signal: ExtractedSignal, is_rising: bool) -> str:
    score = (signal.podium_relevance or 0) + (signal.founder_relevance or 0)
    if is_rising and score >= 14 and (signal.freshness_score or 0) >= 6:
        return "high"
    if score >= 11:
        return "medium"
    return "low"


def _llm_watchlist(client: AIClient, candidates: list[dict], rising: set[str]) -> dict[int, dict]:
    source_lines = "\n".join(
        f"  [{c['source'].id}] {c['source'].title or '(untitled)'} — {c['source'].source_domain} — "
        f"author: {c['source'].author or 'not stated'} — theme: {c['signal'].primary_theme or 'none'} — "
        f"claim: {truncate(c['signal'].primary_claim or '', 180)} — url: {c['source'].canonical_url}"
        for c in candidates
    )
    prompt = load_prompt("engagement_recommendation").render(
        source_lines=source_lines,
        theme_lines="\n".join(f"  - {t}" for t in sorted(rising)) or "  (none rising)",
    )
    response = client.complete_json(prompt, max_tokens=2500)
    if not response.ok:
        return {}
    out: dict[int, dict] = {}
    valid_ids = {c["source"].id for c in candidates}
    for item in response.data.get("watchlist", []):
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        if source_id in valid_ids:
            out[source_id] = item
    return out


def set_review_status(item_id: int, status: str, ) -> bool:
    if status not in {"unreviewed", "reviewed", "dismissed", "actioned_by_human"}:
        return False
    with session_scope() as session:
        item = session.get(EngagementWatchlistItem, item_id)
        if item is None:
            return False
        item.review_status = status
        session.add(item)
    return True
