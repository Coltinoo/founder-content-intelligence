"""Read-only query helpers for the dashboard.

Kept out of the Streamlit pages so the UI stays presentational and the data
access is testable on its own.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from sqlalchemy import func, select

from .db import session_scope
from .models import (
    ContentDraft,
    ContentOpportunity,
    EngagementWatchlistItem,
    ExtractedSignal,
    RunLog,
    Source,
    Theme,
    VoiceExample,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── counters ────────────────────────────────────────────────────────────────

def dashboard_counters() -> dict[str, Any]:
    cutoff_24h = _now() - timedelta(hours=24)
    cutoff_7d = _now() - timedelta(days=7)
    with session_scope() as session:
        total = session.scalar(select(func.count(Source.id))) or 0
        last_24h = session.scalar(
            select(func.count(Source.id)).where(Source.discovered_at >= cutoff_24h)
        ) or 0
        last_7d = session.scalar(
            select(func.count(Source.id)).where(Source.discovered_at >= cutoff_7d)
        ) or 0
        extracted = session.scalar(select(func.count(ExtractedSignal.id))) or 0
        needs_review = session.scalar(
            select(func.count(Source.id)).where(
                Source.status.in_(["needs_review", "error"])
            )
        ) or 0
        policy_skipped = session.scalar(
            select(func.count(Source.id)).where(Source.status.like("skipped_%"))
        ) or 0
        themes = session.scalar(select(func.count(Theme.id))) or 0
        rising = session.scalar(
            select(func.count(Theme.id)).where(Theme.trend_status.in_(["rising", "emerging"]))
        ) or 0
        opportunities = session.scalar(select(func.count(ContentOpportunity.id))) or 0
        drafts_pending = session.scalar(
            select(func.count(ContentDraft.id)).where(ContentDraft.approval_status == "pending_review")
        ) or 0
        drafts_approved = session.scalar(
            select(func.count(ContentDraft.id)).where(ContentDraft.approval_status == "approved")
        ) or 0
        domains = session.scalar(select(func.count(func.distinct(Source.source_domain)))) or 0
        voice_examples = session.scalar(
            select(func.count(VoiceExample.id)).where(VoiceExample.approved_for_voice_library.is_(True))
        ) or 0
        watchlist = session.scalar(
            select(func.count(EngagementWatchlistItem.id))
            .where(EngagementWatchlistItem.review_status == "unreviewed")
        ) or 0
        last_run = session.execute(
            select(RunLog).order_by(RunLog.started_at.desc()).limit(1)
        ).scalar_one_or_none()
        last_run_payload = None
        if last_run is not None:
            last_run_payload = {
                "id": last_run.id,
                "started_at": last_run.started_at,
                "finished_at": last_run.finished_at,
                "trigger": last_run.trigger,
                "stored": last_run.sources_fetched,
                "duplicates": last_run.sources_duplicate,
                "signals": last_run.signals_extracted,
                "themes": last_run.themes_updated,
                "opportunities": last_run.opportunities_created,
                "errors": list(last_run.errors or []),
                "notes": last_run.notes,
            }

    return {
        "total_sources": total,
        "sources_24h": last_24h,
        "sources_7d": last_7d,
        "extracted_signals": extracted,
        "needs_review": needs_review,
        "policy_skipped": policy_skipped,
        "themes": themes,
        "rising_themes": rising,
        "opportunities": opportunities,
        "drafts_pending": drafts_pending,
        "drafts_approved": drafts_approved,
        "distinct_domains": domains,
        "voice_examples": voice_examples,
        "watchlist_unreviewed": watchlist,
        "last_run": last_run_payload,
    }


# ── sources ─────────────────────────────────────────────────────────────────

def sources_dataframe(
    *,
    search: str = "",
    source_types: list[str] | None = None,
    domains: list[str] | None = None,
    industries: list[str] | None = None,
    themes: list[str] | None = None,
    statuses: list[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 500,
) -> pd.DataFrame:
    with session_scope() as session:
        rows = session.execute(
            select(Source, ExtractedSignal)
            .outerjoin(ExtractedSignal, ExtractedSignal.source_id == Source.id)
            .order_by(Source.discovered_at.desc())
            .limit(limit * 3)
        ).all()

    records = []
    for source, signal in rows:
        record = {
            "id": source.id,
            "title": source.title or "(untitled)",
            "domain": source.source_domain,
            "source_type": source.source_type,
            "status": source.status,
            "published_at": source.published_at,
            "discovered_at": source.discovered_at,
            "url": source.canonical_url,
            "author": source.author,
            "search_query": source.search_query,
            "word_count": (source.metadata_json or {}).get("word_count", 0),
            "fetch_error": source.fetch_error,
            "theme": signal.primary_theme if signal else None,
            "secondary_themes": (signal.secondary_themes or []) if signal else [],
            "industries": (signal.industries or []) if signal else [],
            "podium_relevance": signal.podium_relevance if signal else None,
            "founder_relevance": signal.founder_relevance if signal else None,
            "evidence_strength": signal.evidence_strength if signal else None,
            "opportunity_score": signal.opportunity_score if signal else None,
            "risk_score": signal.risk_score if signal else None,
            "extraction_method": signal.extraction_method if signal else None,
            "evidence_count": len(signal.supporting_evidence or []) if signal else 0,
            "quote_count": len(signal.notable_quotes or []) if signal else 0,
            "has_signal": signal is not None,
            "is_promotional": signal.is_promotional_source if signal else None,
            "rediscovered": (source.metadata_json or {}).get("rediscovery_count", 0),
        }
        records.append(record)

    frame = pd.DataFrame(records)
    if frame.empty:
        return frame

    if search:
        needle = search.lower()
        mask = (
            frame["title"].fillna("").str.lower().str.contains(needle)
            | frame["domain"].fillna("").str.lower().str.contains(needle)
            | frame["url"].fillna("").str.lower().str.contains(needle)
            | frame["search_query"].fillna("").str.lower().str.contains(needle)
        )
        frame = frame[mask]
    if source_types:
        frame = frame[frame["source_type"].isin(source_types)]
    if domains:
        frame = frame[frame["domain"].isin(domains)]
    if statuses:
        frame = frame[frame["status"].isin(statuses)]
    if themes:
        frame = frame[frame.apply(
            lambda r: r["theme"] in themes or bool(set(r["secondary_themes"] or []) & set(themes)),
            axis=1,
        )]
    if industries:
        frame = frame[frame["industries"].apply(
            lambda values: bool(set(values or []) & set(industries))
        )]
    if since is not None:
        frame = frame[
            (frame["published_at"].fillna(frame["discovered_at"]) >= pd.Timestamp(since))
        ]
    if until is not None:
        frame = frame[
            (frame["published_at"].fillna(frame["discovered_at"]) <= pd.Timestamp(until))
        ]
    return frame.head(limit)


def source_detail(source_id: int) -> dict | None:
    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None:
            return None
        signal = session.execute(
            select(ExtractedSignal).where(ExtractedSignal.source_id == source_id)
        ).scalar_one_or_none()
        return {
            "source": {
                "id": source.id,
                "title": source.title,
                "url": source.canonical_url,
                "source_url": source.source_url,
                "domain": source.source_domain,
                "author": source.author,
                "published_at": source.published_at,
                "discovered_at": source.discovered_at,
                "fetched_at": source.fetched_at,
                "source_type": source.source_type,
                "status": source.status,
                "fetch_error": source.fetch_error,
                "search_query": source.search_query,
                "cleaned_text": source.cleaned_text,
                "content_hash": source.content_hash,
                "metadata": dict(source.metadata_json or {}),
            },
            "signal": None if signal is None else {
                "id": signal.id,
                "primary_entity": signal.primary_entity,
                "secondary_entities": signal.secondary_entities or [],
                "industries": signal.industries or [],
                "customer_segment": signal.customer_segment,
                "primary_theme": signal.primary_theme,
                "secondary_themes": signal.secondary_themes or [],
                "customer_problem": signal.customer_problem,
                "primary_claim": signal.primary_claim,
                "supporting_evidence": signal.supporting_evidence or [],
                "notable_quotes": signal.notable_quotes or [],
                "numerical_claims": signal.numerical_claims or [],
                "podium_relevance": signal.podium_relevance,
                "founder_relevance": signal.founder_relevance,
                "novelty_score": signal.novelty_score,
                "freshness_score": signal.freshness_score,
                "evidence_strength": signal.evidence_strength,
                "business_impact": signal.business_impact,
                "opportunity_score": signal.opportunity_score,
                "risk_score": signal.risk_score,
                "score_breakdown": signal.score_breakdown or {},
                "risk_breakdown": signal.risk_breakdown or {},
                "content_opportunity": signal.content_opportunity,
                "potential_angle": signal.potential_angle,
                "recommended_format": signal.recommended_format,
                "verification_notes": signal.verification_notes or [],
                "extraction_model": signal.extraction_model,
                "extraction_method": signal.extraction_method,
                "extraction_error": signal.extraction_error,
                "extracted_at": signal.extracted_at,
                "is_promotional": signal.is_promotional_source,
                "is_familiar": signal.is_familiar_narrative,
                "is_summary_only": signal.is_summary_only,
            },
        }


def top_signals(limit: int = 10) -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(Source, ExtractedSignal)
            .join(ExtractedSignal, ExtractedSignal.source_id == Source.id)
            .order_by(ExtractedSignal.opportunity_score.desc())
            .limit(limit)
        ).all()
    return [
        {
            "source_id": s.id, "title": s.title or "(untitled)", "url": s.canonical_url,
            "domain": s.source_domain, "published_at": s.published_at,
            "theme": sig.primary_theme, "score": sig.opportunity_score,
            "risk": sig.risk_score, "podium_relevance": sig.podium_relevance,
            "evidence_strength": sig.evidence_strength,
            "extraction_method": sig.extraction_method,
            "problem": sig.customer_problem,
        }
        for s, sig in rows
    ]


def filter_options() -> dict[str, list]:
    with session_scope() as session:
        domains = [r[0] for r in session.execute(
            select(Source.source_domain).distinct().order_by(Source.source_domain)
        ).all() if r[0]]
        types = [r[0] for r in session.execute(
            select(Source.source_type).distinct().order_by(Source.source_type)
        ).all() if r[0]]
        statuses = [r[0] for r in session.execute(
            select(Source.status).distinct()
        ).all() if r[0]]
        themes = [r[0] for r in session.execute(
            select(ExtractedSignal.primary_theme).distinct()
        ).all() if r[0]]
        industry_lists = [r[0] for r in session.execute(
            select(ExtractedSignal.industries)
        ).all() if r[0]]
    industries = sorted({i for lst in industry_lists for i in (lst or [])})
    return {
        "domains": sorted(domains), "source_types": sorted(types),
        "statuses": sorted(statuses), "themes": sorted(themes), "industries": industries,
    }


# ── themes ──────────────────────────────────────────────────────────────────

def themes_dataframe(min_sources: int = 1) -> pd.DataFrame:
    with session_scope() as session:
        themes = session.execute(
            select(Theme).order_by(Theme.source_count.desc())
        ).scalars().all()
        records = [
            {
                "id": t.id, "name": t.name, "slug": t.slug, "description": t.description,
                "trend_status": t.trend_status, "source_count": t.source_count,
                "domains": t.distinct_domain_count, "industries": t.distinct_industry_count,
                "current_period": t.current_period_count, "previous_period": t.previous_period_count,
                "growth_rate": t.growth_rate, "avg_relevance": t.average_relevance,
                "avg_founder_relevance": t.average_founder_relevance,
                "avg_evidence": t.average_evidence_strength,
                "avg_impact": t.average_business_impact,
                "first_seen": t.first_seen, "last_seen": t.last_seen,
                "recency_days": t.recency_days, "rationale": t.trend_rationale,
            }
            for t in themes
        ]
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    return frame[frame["source_count"] >= min_sources]


# ── opportunities & drafts ──────────────────────────────────────────────────

def opportunities_list(statuses: list[str] | None = None) -> list[dict]:
    with session_scope() as session:
        query = select(ContentOpportunity).order_by(ContentOpportunity.opportunity_score.desc())
        if statuses:
            query = query.where(ContentOpportunity.status.in_(statuses))
        rows = session.execute(query).scalars().all()
        out = []
        for opportunity in rows:
            theme = session.get(Theme, opportunity.theme_id) if opportunity.theme_id else None
            draft_count = session.scalar(
                select(func.count(ContentDraft.id))
                .where(ContentDraft.content_opportunity_id == opportunity.id)
            ) or 0
            out.append({
                "id": opportunity.id,
                "title": opportunity.title,
                "theme": theme.name if theme else None,
                "trend_status": theme.trend_status if theme else None,
                "status": opportunity.status,
                "score": opportunity.opportunity_score,
                "confidence": opportunity.confidence_score,
                "risk": opportunity.risk_score,
                "format": opportunity.recommended_format,
                "source_count": len(opportunity.supporting_source_ids or []),
                "evidence_count": len(opportunity.evidence_passages or []),
                "points": len(opportunity.supporting_points or []),
                "drafts": draft_count,
                "created_at": opportunity.created_at,
                "generation_method": opportunity.generation_method,
            })
    return out


def opportunity_detail(opportunity_id: int) -> dict | None:
    with session_scope() as session:
        opportunity = session.get(ContentOpportunity, opportunity_id)
        if opportunity is None:
            return None
        theme = session.get(Theme, opportunity.theme_id) if opportunity.theme_id else None
        drafts = session.execute(
            select(ContentDraft)
            .where(ContentDraft.content_opportunity_id == opportunity_id)
            .order_by(ContentDraft.created_at.desc())
        ).scalars().all()
        source_ids = list(opportunity.supporting_source_ids or [])
        sources = []
        if source_ids:
            rows = session.execute(
                select(Source, ExtractedSignal)
                .outerjoin(ExtractedSignal, ExtractedSignal.source_id == Source.id)
                .where(Source.id.in_(source_ids))
            ).all()
            sources = [
                {
                    "id": s.id, "title": s.title or "(untitled)", "url": s.canonical_url,
                    "domain": s.source_domain, "published_at": s.published_at,
                    "source_type": s.source_type, "author": s.author,
                    "is_promotional": sig.is_promotional_source if sig else None,
                    "evidence_strength": sig.evidence_strength if sig else None,
                    "extraction_method": sig.extraction_method if sig else None,
                }
                for s, sig in rows
            ]

        return {
            "opportunity": {
                "id": opportunity.id, "title": opportunity.title,
                "core_insight": opportunity.core_insight, "why_now": opportunity.why_now,
                "why_podium": opportunity.why_podium, "why_eric": opportunity.why_eric,
                "target_audience": opportunity.target_audience,
                "founder_point_of_view": opportunity.founder_point_of_view,
                "hook": opportunity.hook,
                "supporting_points": opportunity.supporting_points or [],
                "evidence_passages": opportunity.evidence_passages or [],
                "potential_objections": opportunity.potential_objections or [],
                "recommended_format": opportunity.recommended_format,
                "suggested_call_to_action": opportunity.suggested_call_to_action,
                "confidence_score": opportunity.confidence_score,
                "opportunity_score": opportunity.opportunity_score,
                "score_breakdown": opportunity.score_breakdown or {},
                "risk_score": opportunity.risk_score,
                "risk_notes": opportunity.risk_notes or [],
                "verification_checklist": opportunity.verification_checklist or [],
                "status": opportunity.status,
                "reviewer_notes": opportunity.reviewer_notes,
                "created_at": opportunity.created_at,
                "generation_method": opportunity.generation_method,
                "supporting_source_ids": source_ids,
            },
            "theme": None if theme is None else {
                "name": theme.name, "trend_status": theme.trend_status,
                "source_count": theme.source_count, "rationale": theme.trend_rationale,
                "growth_rate": theme.growth_rate,
            },
            "sources": sources,
            "drafts": [
                {
                    "id": d.id, "content_type": d.content_type, "draft_text": d.draft_text,
                    "voice_score": d.voice_score, "voice_notes": d.voice_notes or [],
                    "evidence_score": d.evidence_score,
                    "unsupported_claims": d.unsupported_claims or [],
                    "verification_required": d.verification_required or [],
                    "cited_source_ids": d.cited_source_ids or [],
                    "approval_status": d.approval_status, "reviewer_notes": d.reviewer_notes,
                    "generation_method": d.generation_method,
                    "created_at": d.created_at, "updated_at": d.updated_at,
                }
                for d in drafts
            ],
        }


def set_opportunity_status(opportunity_id: int, status: str, notes: str = "") -> bool:
    from .models import OPPORTUNITY_STATUSES

    if status not in OPPORTUNITY_STATUSES:
        return False
    with session_scope() as session:
        opportunity = session.get(ContentOpportunity, opportunity_id)
        if opportunity is None:
            return False
        opportunity.status = status
        if notes:
            opportunity.reviewer_notes = notes
        if status in {"approved", "archived"}:
            opportunity.reviewed_at = _now()
        session.add(opportunity)
    return True


def update_checklist(opportunity_id: int, checklist: list[dict]) -> bool:
    with session_scope() as session:
        opportunity = session.get(ContentOpportunity, opportunity_id)
        if opportunity is None:
            return False
        opportunity.verification_checklist = checklist
        session.add(opportunity)
    return True


# ── watchlist & voice ───────────────────────────────────────────────────────

def watchlist_items(statuses: list[str] | None = None) -> list[dict]:
    with session_scope() as session:
        query = select(EngagementWatchlistItem).order_by(
            EngagementWatchlistItem.discovered_at.desc()
        )
        if statuses:
            query = query.where(EngagementWatchlistItem.review_status.in_(statuses))
        items = session.execute(query).scalars().all()
        return [
            {
                "id": i.id, "person_or_company": i.person_or_company,
                "url": i.profile_or_source_url, "source_id": i.source_id,
                "topic": i.topic, "recent_signal": i.recent_signal,
                "why_relevant": i.why_relevant, "podium_connection": i.podium_connection,
                "suggested_response_angle": i.suggested_response_angle,
                "priority": i.priority, "risk_notes": i.risk_notes,
                "discovered_at": i.discovered_at, "review_status": i.review_status,
            }
            for i in items
        ]


def voice_examples(approved_only: bool = False) -> list[dict]:
    with session_scope() as session:
        query = select(VoiceExample).order_by(VoiceExample.created_at.desc())
        if approved_only:
            query = query.where(VoiceExample.approved_for_voice_library.is_(True))
        return [
            {
                "id": e.id, "title": e.title, "source_url": e.source_url,
                "pasted_text": e.pasted_text, "date": e.date,
                "content_type": e.content_type, "hook_style": e.hook_style,
                "sentence_style": e.sentence_style,
                "recurring_themes": e.recurring_themes or [],
                "evidence_style": e.evidence_style, "tone_notes": e.tone_notes,
                "analysis": dict(e.analysis_json or {}),
                "approved": e.approved_for_voice_library,
                "created_at": e.created_at,
            }
            for e in session.execute(query).scalars().all()
        ]


def set_voice_approval(example_id: int, approved: bool) -> bool:
    with session_scope() as session:
        example = session.get(VoiceExample, example_id)
        if example is None:
            return False
        example.approved_for_voice_library = approved
        session.add(example)
    return True


def delete_voice_example(example_id: int) -> bool:
    with session_scope() as session:
        example = session.get(VoiceExample, example_id)
        if example is None:
            return False
        session.delete(example)
    return True


def recent_runs(limit: int = 10) -> list[dict]:
    with session_scope() as session:
        runs = session.execute(
            select(RunLog).order_by(RunLog.started_at.desc()).limit(limit)
        ).scalars().all()
        return [
            {
                "id": r.id, "started_at": r.started_at, "finished_at": r.finished_at,
                "trigger": r.trigger, "stored": r.sources_fetched,
                "duplicates": r.sources_duplicate, "signals": r.signals_extracted,
                "themes": r.themes_updated, "opportunities": r.opportunities_created,
                "errors": len(r.errors or []), "notes": r.notes,
                "stages": dict(r.stages or {}),
            }
            for r in runs
        ]
