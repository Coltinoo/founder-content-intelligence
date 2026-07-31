"""Trend detection.

Themes are aggregations of extracted signals. Every statistic is computed
deterministically from the database; the LLM (when configured) only writes the
*rationale* around numbers it is forbidden to change.

Trend status rules — a single source is never a trend:

    low_confidence  fewer than `min_sources_for_trend` sources, OR fewer than
                    `min_domains_for_trend` distinct domains
    emerging        first appeared inside the current period and growing
    rising          current period ≥ 1.5× previous period, and ≥3 sources
    declining       current period ≤ 0.6× previous period
    saturated       high volume, low average novelty — the story is well covered
    stable          everything else
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..ai.client import AIClient
from ..ai.prompts import load_prompt
from ..ai.taxonomy import THEMES, THEME_BY_SLUG
from ..config import load_config
from ..db import session_scope
from ..models import ExtractedSignal, Source, Theme
from ..utils.hashing import slugify

log = logging.getLogger(__name__)

TREND_STATUSES = ["emerging", "rising", "stable", "declining", "saturated", "low_confidence"]


@dataclass
class ThemeStats:
    slug: str
    name: str
    description: str
    source_ids: list[int] = field(default_factory=list)
    domains: set[str] = field(default_factory=set)
    industries: set[str] = field(default_factory=set)
    dates: list[datetime] = field(default_factory=list)
    relevance: list[float] = field(default_factory=list)
    founder_relevance: list[float] = field(default_factory=list)
    evidence: list[float] = field(default_factory=list)
    impact: list[float] = field(default_factory=list)
    novelty: list[float] = field(default_factory=list)
    current_count: int = 0
    previous_count: int = 0

    @property
    def source_count(self) -> int:
        return len(self.source_ids)

    @staticmethod
    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    def averages(self) -> dict[str, float]:
        return {
            "relevance": self._avg(self.relevance),
            "founder_relevance": self._avg(self.founder_relevance),
            "evidence": self._avg(self.evidence),
            "impact": self._avg(self.impact),
            "novelty": self._avg(self.novelty),
        }


@dataclass
class TrendReport:
    themes_updated: int = 0
    rising: list[str] = field(default_factory=list)
    emerging: list[str] = field(default_factory=list)
    low_confidence: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "themes_updated": self.themes_updated,
            "rising": self.rising,
            "emerging": self.emerging,
            "low_confidence": self.low_confidence,
            "errors": self.errors[:20],
        }


def run_trend_analysis(*, write_rationale: bool = True, progress=None) -> TrendReport:
    cfg = load_config()
    report = TrendReport()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    current_start = now - timedelta(days=cfg.trends.current_period_days)
    previous_start = current_start - timedelta(days=cfg.trends.previous_period_days)

    def emit(message: str) -> None:
        log.info(message)
        if progress:
            try:
                progress(message)
            except Exception:  # noqa: BLE001
                pass

    # ── gather ──────────────────────────────────────────────────────────
    with session_scope() as session:
        rows = session.execute(
            select(
                ExtractedSignal.source_id,
                ExtractedSignal.primary_theme,
                ExtractedSignal.secondary_themes,
                ExtractedSignal.podium_relevance,
                ExtractedSignal.founder_relevance,
                ExtractedSignal.evidence_strength,
                ExtractedSignal.business_impact,
                ExtractedSignal.novelty_score,
                Source.source_domain,
                Source.published_at,
                Source.discovered_at,
                ExtractedSignal.industries,
            ).join(Source, Source.id == ExtractedSignal.source_id)
        ).all()

    if not rows:
        emit("No extracted signals yet — run discovery and extraction first.")
        return report

    buckets: dict[str, ThemeStats] = {}

    def bucket_for(theme_name: str) -> ThemeStats | None:
        theme_def = next((t for t in THEMES if t.name == theme_name), None)
        slug = theme_def.slug if theme_def else slugify(theme_name)
        if slug not in buckets:
            buckets[slug] = ThemeStats(
                slug=slug,
                name=theme_def.name if theme_def else theme_name,
                description=theme_def.description if theme_def else
                            "Theme observed in the corpus but not in the seed taxonomy.",
            )
        return buckets[slug]

    for row in rows:
        (source_id, primary, secondary, relevance, founder_rel, evidence,
         impact, novelty, domain, published, discovered, industries) = row

        theme_names = [primary] if primary else []
        theme_names += [t for t in (secondary or []) if t]

        effective_date = published or discovered
        for position, theme_name in enumerate(dict.fromkeys(theme_names)):
            stats = bucket_for(theme_name)
            if source_id not in stats.source_ids:
                stats.source_ids.append(source_id)
            if domain:
                stats.domains.add(domain)
            for industry in (industries or []):
                stats.industries.add(industry)
            if effective_date:
                stats.dates.append(effective_date)
                if effective_date >= current_start:
                    stats.current_count += 1
                elif effective_date >= previous_start:
                    stats.previous_count += 1
            # Secondary themes contribute at reduced weight to the averages.
            weight = 1.0 if position == 0 else 0.5
            stats.relevance.append((relevance or 0) * weight)
            stats.founder_relevance.append((founder_rel or 0) * weight)
            stats.evidence.append((evidence or 0) * weight)
            stats.impact.append((impact or 0) * weight)
            stats.novelty.append((novelty or 0) * weight)

    # ── classify + persist ──────────────────────────────────────────────
    client = AIClient() if write_rationale else None

    for slug, stats in buckets.items():
        averages = stats.averages()
        growth = _growth_rate(stats.current_count, stats.previous_count)
        status, reason = classify_trend(
            source_count=stats.source_count,
            distinct_domains=len(stats.domains),
            current_count=stats.current_count,
            previous_count=stats.previous_count,
            growth_rate=growth,
            avg_novelty=averages["novelty"],
            first_seen=min(stats.dates) if stats.dates else None,
            current_start=current_start,
            config=cfg,
        )

        rationale = reason
        if client and client.available and stats.source_count >= cfg.trends.min_sources_for_trend:
            llm_rationale = _llm_rationale(client, stats, averages, growth, status,
                                           cfg, now)
            if llm_rationale:
                rationale = f"{reason}\n\n{llm_rationale}"

        with session_scope() as session:
            theme = session.execute(
                select(Theme).where(Theme.slug == slug)
            ).scalar_one_or_none()
            if theme is None:
                theme = Theme(slug=slug, name=stats.name)
                session.add(theme)

            theme.name = stats.name
            theme.description = stats.description
            theme.source_count = stats.source_count
            theme.distinct_domain_count = len(stats.domains)
            theme.distinct_industry_count = len(stats.industries)
            theme.first_seen = min(stats.dates) if stats.dates else None
            theme.last_seen = max(stats.dates) if stats.dates else None
            theme.previous_period_count = stats.previous_count
            theme.current_period_count = stats.current_count
            theme.growth_rate = growth
            theme.average_relevance = averages["relevance"]
            theme.average_founder_relevance = averages["founder_relevance"]
            theme.average_evidence_strength = averages["evidence"]
            theme.average_business_impact = averages["impact"]
            theme.recency_days = (
                round((now - max(stats.dates)).total_seconds() / 86400.0, 1)
                if stats.dates else None
            )
            theme.trend_status = status
            theme.trend_rationale = rationale
            theme.computed_at = now
            session.add(theme)

        report.themes_updated += 1
        if status == "rising":
            report.rising.append(stats.name)
        elif status == "emerging":
            report.emerging.append(stats.name)
        elif status == "low_confidence":
            report.low_confidence.append(stats.name)

    emit(f"Trend analysis complete: {report.themes_updated} theme(s); "
         f"{len(report.rising)} rising, {len(report.emerging)} emerging.")
    return report


def _growth_rate(current: int, previous: int) -> float:
    if previous == 0:
        return float(current) if current else 0.0
    return round((current - previous) / previous, 3)


def classify_trend(
    *,
    source_count: int,
    distinct_domains: int,
    current_count: int,
    previous_count: int,
    growth_rate: float,
    avg_novelty: float,
    first_seen: datetime | None,
    current_start: datetime,
    config=None,
) -> tuple[str, str]:
    """Deterministic trend labelling. Returns ``(status, plain-English reason)``."""
    cfg = config or load_config()
    min_sources = cfg.trends.min_sources_for_trend
    min_domains = cfg.trends.min_domains_for_trend

    if source_count < min_sources:
        return "low_confidence", (
            f"Only {source_count} source(s) — below the {min_sources}-source floor. "
            "A single source is never reported as a trend."
        )
    if distinct_domains < min_domains:
        return "low_confidence", (
            f"{source_count} source(s) but only {distinct_domains} distinct domain(s). "
            "One publisher repeating itself is not corroboration."
        )

    if first_seen and first_seen >= current_start and current_count >= min_sources:
        return "emerging", (
            f"First observed inside the current period, already at {current_count} "
            f"source(s) across {distinct_domains} domain(s)."
        )

    if source_count >= 6 and avg_novelty < 4.0:
        return "saturated", (
            f"{source_count} sources but average novelty of only {avg_novelty}/10 — "
            "the narrative is well covered and mostly repetitive."
        )

    if current_count >= 3 and growth_rate >= 0.5:
        return "rising", (
            f"{current_count} source(s) this period vs {previous_count} last period "
            f"({growth_rate:+.0%}), across {distinct_domains} domains."
        )

    if previous_count >= 2 and growth_rate <= -0.4:
        return "declining", (
            f"Down to {current_count} source(s) from {previous_count} "
            f"({growth_rate:+.0%})."
        )

    return "stable", (
        f"{current_count} source(s) this period vs {previous_count} last period — "
        "no meaningful change in volume."
    )


def _llm_rationale(client: AIClient, stats: ThemeStats, averages: dict,
                   growth: float, status: str, cfg, now) -> str | None:
    """Ask the model to interpret — never to compute — the theme statistics."""
    with session_scope() as session:
        rows = session.execute(
            select(Source.id, Source.title, Source.source_domain, Source.published_at)
            .where(Source.id.in_(stats.source_ids[:12]))
        ).all()
    source_lines = "\n".join(
        f"  [{r[0]}] {r[1] or '(untitled)'} — {r[2]} — "
        f"{r[3].date().isoformat() if r[3] else 'no date'}"
        for r in rows
    )

    prompt = load_prompt("trend_analysis").render(
        theme_name=stats.name,
        theme_description=stats.description,
        source_count=stats.source_count,
        distinct_domains=len(stats.domains),
        distinct_industries=len(stats.industries),
        current_count=stats.current_count,
        previous_count=stats.previous_count,
        current_days=cfg.trends.current_period_days,
        previous_days=cfg.trends.previous_period_days,
        growth_rate=f"{growth:+.0%}",
        avg_relevance=averages["relevance"],
        avg_founder_relevance=averages["founder_relevance"],
        avg_evidence=averages["evidence"],
        avg_impact=averages["impact"],
        recency_days=round((now - max(stats.dates)).total_seconds() / 86400.0, 1) if stats.dates else "unknown",
        trend_status=status,
        source_lines=source_lines,
    )
    response = client.complete_json(prompt, max_tokens=900)
    if not response.ok:
        return None

    data = response.data
    parts = [data.get("rationale", "").strip()]
    if data.get("what_is_actually_new"):
        parts.append(f"**What is new:** {data['what_is_actually_new']}")
    if data.get("counter_evidence"):
        parts.append(f"**Counter-evidence:** {data['counter_evidence']}")
    caveats = data.get("caveats") or []
    if caveats:
        parts.append("**Caveats:** " + "; ".join(str(c) for c in caveats[:4]))
    if data.get("confidence"):
        parts.append(f"_Model confidence: {data['confidence']}_")
    text = "\n\n".join(p for p in parts if p)
    return text or None


def get_theme_sources(theme_name: str, limit: int = 50) -> list[dict]:
    """Every source supporting a theme, primary assignments first."""
    with session_scope() as session:
        rows = session.execute(
            select(
                Source.id, Source.title, Source.canonical_url, Source.source_domain,
                Source.published_at, Source.source_type,
                ExtractedSignal.primary_theme, ExtractedSignal.secondary_themes,
                ExtractedSignal.podium_relevance, ExtractedSignal.evidence_strength,
                ExtractedSignal.opportunity_score, ExtractedSignal.customer_problem,
                ExtractedSignal.supporting_evidence, ExtractedSignal.notable_quotes,
                ExtractedSignal.extraction_method,
            ).join(ExtractedSignal, ExtractedSignal.source_id == Source.id)
        ).all()

    matches = []
    for row in rows:
        is_primary = row[6] == theme_name
        is_secondary = theme_name in (row[7] or [])
        if not (is_primary or is_secondary):
            continue
        matches.append({
            "source_id": row[0],
            "title": row[1],
            "url": row[2],
            "domain": row[3],
            "published_at": row[4],
            "source_type": row[5],
            "assignment": "primary" if is_primary else "secondary",
            "podium_relevance": row[8],
            "evidence_strength": row[9],
            "opportunity_score": row[10],
            "customer_problem": row[11],
            "evidence": row[12] or [],
            "quotes": row[13] or [],
            "extraction_method": row[14],
        })

    matches.sort(key=lambda m: (m["assignment"] != "primary", -(m["opportunity_score"] or 0)))
    return matches[:limit]
