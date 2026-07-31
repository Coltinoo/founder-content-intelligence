"""SQLAlchemy ORM models.

The schema is deliberately portable between SQLite (local dev) and Postgres
(Supabase). List/dict-valued columns are stored as JSON text via ``JSONList`` /
``JSONDict`` so both backends behave identically.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class JSONEncoded(TypeDecorator):
    """Portable JSON column. Works identically on SQLite and Postgres."""

    impl = Text
    cache_ok = True
    _default: Any = None

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None or value == "":
            return self._default() if callable(self._default) else self._default
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return self._default() if callable(self._default) else self._default


class JSONList(JSONEncoded):
    cache_ok = True
    _default = list


class JSONDict(JSONEncoded):
    cache_ok = True
    _default = dict


# ─────────────────────────────────────────────────────────────────────────────
# sources
# ─────────────────────────────────────────────────────────────────────────────

class Source(Base):
    """A single retrieved public document, with its raw and cleaned text."""

    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    source_type = Column(String(40), nullable=False, index=True)
    # podium_site | rss | web_search | youtube | manual | manual_transcript | ...
    source_url = Column(Text, nullable=False)
    canonical_url = Column(Text, nullable=False, index=True)
    source_domain = Column(String(255), index=True)
    title = Column(Text)
    author = Column(Text)
    published_at = Column(DateTime)
    discovered_at = Column(DateTime, default=utcnow, index=True)
    fetched_at = Column(DateTime)
    search_query = Column(Text)              # the query that first surfaced it
    raw_text = Column(Text)
    cleaned_text = Column(Text)
    content_hash = Column(String(64), index=True)
    status = Column(String(30), default="discovered", index=True)
    # discovered | fetched | extracted | error | skipped_robots | duplicate | needs_review
    fetch_error = Column(Text)
    metadata_json = Column(JSONDict, default=dict)
    # {podium_category, discovered_by_queries: [...], feed_name, industry_hint,
    #  duplicate_of, robots_decision, http_status, word_count, is_promotional, ...}

    signals = relationship(
        "ExtractedSignal", back_populates="source", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_sources_canonical_url"),
        Index("ix_sources_type_status", "source_type", "status"),
    )

    @property
    def has_publication_date(self) -> bool:
        return self.published_at is not None

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Source {self.id} {self.source_domain} {(self.title or '')[:50]!r}>"


# ─────────────────────────────────────────────────────────────────────────────
# extracted_signals
# ─────────────────────────────────────────────────────────────────────────────

class ExtractedSignal(Base):
    """Structured analysis of one source.

    Facts found in the source (claims, quotes, evidence passages) are kept
    strictly separate from AI interpretation (angles, relevance, POV).
    """

    __tablename__ = "extracted_signals"

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), index=True)

    # ── entities & taxonomy ────────────────────────────────────────────
    primary_entity = Column(Text)
    secondary_entities = Column(JSONList, default=list)
    industries = Column(JSONList, default=list)
    customer_segment = Column(Text)

    # ── themes ─────────────────────────────────────────────────────────
    primary_theme = Column(Text, index=True)
    secondary_themes = Column(JSONList, default=list)

    # ── FACTS (must be grounded in the source text) ────────────────────
    customer_problem = Column(Text)
    primary_claim = Column(Text)
    supporting_evidence = Column(JSONList, default=list)   # [{passage, char_start, char_end, verified_verbatim}]
    notable_quotes = Column(JSONList, default=list)        # [{quote, speaker, verified_verbatim}]
    numerical_claims = Column(JSONList, default=list)      # [{value, context, needs_verification}]

    # ── INTERPRETATION (AI-generated, labelled as such in the UI) ──────
    founder_relevance = Column(Float, default=0.0)     # 0-10
    podium_relevance = Column(Float, default=0.0)      # 0-10
    novelty_score = Column(Float, default=0.0)         # 0-10
    freshness_score = Column(Float, default=0.0)       # 0-10
    evidence_strength = Column(Float, default=0.0)     # 0-10
    business_impact = Column(Float, default=0.0)       # 0-10
    risk_score = Column(Float, default=0.0)            # 0-100 (higher = riskier)
    opportunity_score = Column(Float, default=0.0, index=True)  # 0-100
    score_breakdown = Column(JSONDict, default=dict)
    risk_breakdown = Column(JSONDict, default=dict)

    content_opportunity = Column(Text)
    potential_angle = Column(Text)
    recommended_format = Column(Text)

    # ── provenance & integrity ─────────────────────────────────────────
    is_familiar_narrative = Column(Boolean, default=False)
    is_promotional_source = Column(Boolean, default=False)
    is_summary_only = Column(Boolean, default=False)
    verification_notes = Column(JSONList, default=list)
    extraction_model = Column(String(80))    # e.g. "gpt-4o-mini" or "heuristic-v1"
    extraction_method = Column(String(30), default="heuristic")  # llm | heuristic
    extraction_error = Column(Text)
    extracted_at = Column(DateTime, default=utcnow, index=True)

    source = relationship("Source", back_populates="signals")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Signal {self.id} src={self.source_id} theme={self.primary_theme!r} score={self.opportunity_score}>"


# ─────────────────────────────────────────────────────────────────────────────
# themes
# ─────────────────────────────────────────────────────────────────────────────

class Theme(Base):
    __tablename__ = "themes"

    id = Column(Integer, primary_key=True)
    slug = Column(String(120), unique=True, index=True)
    name = Column(Text, nullable=False)
    description = Column(Text)

    source_count = Column(Integer, default=0)
    distinct_domain_count = Column(Integer, default=0)
    distinct_industry_count = Column(Integer, default=0)

    first_seen = Column(DateTime)
    last_seen = Column(DateTime)
    previous_period_count = Column(Integer, default=0)
    current_period_count = Column(Integer, default=0)
    growth_rate = Column(Float, default=0.0)

    average_relevance = Column(Float, default=0.0)         # podium relevance
    average_founder_relevance = Column(Float, default=0.0)
    average_evidence_strength = Column(Float, default=0.0)
    average_business_impact = Column(Float, default=0.0)
    recency_days = Column(Float)

    trend_status = Column(String(30), index=True)
    # emerging | rising | stable | declining | saturated | low_confidence
    trend_rationale = Column(Text)
    computed_at = Column(DateTime, default=utcnow)

    opportunities = relationship("ContentOpportunity", back_populates="theme")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Theme {self.slug} {self.trend_status} n={self.source_count}>"


# ─────────────────────────────────────────────────────────────────────────────
# content_opportunities
# ─────────────────────────────────────────────────────────────────────────────

OPPORTUNITY_STATUSES = [
    "new",
    "research_needed",
    "ready_for_brief",
    "drafting",
    "review",
    "approved",
    "archived",
]


class ContentOpportunity(Base):
    __tablename__ = "content_opportunities"

    id = Column(Integer, primary_key=True)
    theme_id = Column(Integer, ForeignKey("themes.id"), index=True)

    title = Column(Text, nullable=False)
    core_insight = Column(Text)
    why_now = Column(Text)
    why_podium = Column(Text)
    why_eric = Column(Text)
    target_audience = Column(Text)
    founder_point_of_view = Column(Text)
    hook = Column(Text)
    supporting_points = Column(JSONList, default=list)
    supporting_source_ids = Column(JSONList, default=list)
    evidence_passages = Column(JSONList, default=list)   # [{source_id, url, passage}]
    potential_objections = Column(JSONList, default=list)
    recommended_format = Column(Text)
    suggested_call_to_action = Column(Text)

    confidence_score = Column(Float, default=0.0)     # 0-100
    opportunity_score = Column(Float, default=0.0, index=True)
    score_breakdown = Column(JSONDict, default=dict)
    risk_score = Column(Float, default=0.0)
    risk_notes = Column(JSONList, default=list)
    verification_checklist = Column(JSONList, default=list)  # [{item, done}]

    generation_method = Column(String(30), default="heuristic")
    status = Column(String(30), default="new", index=True)
    reviewer_notes = Column(Text)
    created_at = Column(DateTime, default=utcnow, index=True)
    reviewed_at = Column(DateTime)

    theme = relationship("Theme", back_populates="opportunities")
    drafts = relationship(
        "ContentDraft", back_populates="opportunity", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Opportunity {self.id} {self.status} {self.opportunity_score:.0f} {self.title[:40]!r}>"


# ─────────────────────────────────────────────────────────────────────────────
# content_drafts
# ─────────────────────────────────────────────────────────────────────────────

DRAFT_FORMATS = [
    "linkedin_post",
    "short_form_video_outline",
    "long_form_essay_outline",
    "executive_talking_point",
    "podcast_discussion_point",
    "customer_story_angle",
    "engagement_comment",
    "internal_briefing_note",
]

APPROVAL_STATUSES = ["pending_review", "changes_requested", "approved", "rejected"]


class ContentDraft(Base):
    __tablename__ = "content_drafts"

    id = Column(Integer, primary_key=True)
    content_opportunity_id = Column(
        Integer, ForeignKey("content_opportunities.id", ondelete="CASCADE"), index=True
    )
    content_type = Column(String(50), nullable=False)
    draft_text = Column(Text)

    voice_score = Column(Float, default=0.0)       # 0-100 alignment to approved examples
    voice_notes = Column(JSONList, default=list)
    evidence_score = Column(Float, default=0.0)    # 0-100 share of claims traceable to a source
    unsupported_claims = Column(JSONList, default=list)
    verification_required = Column(JSONList, default=list)
    cited_source_ids = Column(JSONList, default=list)

    generation_method = Column(String(30), default="heuristic")
    approval_status = Column(String(30), default="pending_review", index=True)
    reviewer_notes = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    opportunity = relationship("ContentOpportunity", back_populates="drafts")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Draft {self.id} {self.content_type} {self.approval_status}>"


# ─────────────────────────────────────────────────────────────────────────────
# voice_examples
# ─────────────────────────────────────────────────────────────────────────────

class VoiceExample(Base):
    """Manually pasted, publicly available founder content.

    Nothing here is scraped. LinkedIn posts enter only by a human pasting the
    public text and URL.
    """

    __tablename__ = "voice_examples"

    id = Column(Integer, primary_key=True)
    title = Column(Text)
    source_url = Column(Text)
    pasted_text = Column(Text, nullable=False)
    date = Column(DateTime)
    content_type = Column(String(60))   # linkedin_post | interview | podcast | press_quote | keynote

    hook_style = Column(Text)
    sentence_style = Column(Text)
    recurring_themes = Column(JSONList, default=list)
    evidence_style = Column(Text)
    tone_notes = Column(Text)
    analysis_json = Column(JSONDict, default=dict)  # full metric payload
    analysed_at = Column(DateTime)

    approved_for_voice_library = Column(Boolean, default=False, index=True)
    added_by = Column(String(120), default="manual")
    created_at = Column(DateTime, default=utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<VoiceExample {self.id} {self.content_type} approved={self.approved_for_voice_library}>"


# ─────────────────────────────────────────────────────────────────────────────
# engagement_watchlist
# ─────────────────────────────────────────────────────────────────────────────

class EngagementWatchlistItem(Base):
    """Public conversations a human may want to review.

    The system never comments, likes, reposts, follows, or messages.
    """

    __tablename__ = "engagement_watchlist"

    id = Column(Integer, primary_key=True)
    person_or_company = Column(Text, nullable=False)
    profile_or_source_url = Column(Text)
    source_id = Column(Integer, ForeignKey("sources.id"), index=True)
    topic = Column(Text)
    recent_signal = Column(Text)
    why_relevant = Column(Text)
    podium_connection = Column(Text)
    suggested_response_angle = Column(Text)
    priority = Column(String(20), default="medium", index=True)  # high | medium | low
    risk_notes = Column(Text)
    discovered_at = Column(DateTime, default=utcnow, index=True)
    review_status = Column(String(30), default="unreviewed", index=True)
    # unreviewed | reviewed | dismissed | actioned_by_human

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Watchlist {self.id} {self.person_or_company!r} {self.priority}>"


# ─────────────────────────────────────────────────────────────────────────────
# run_log — observability for scheduled ingestion
# ─────────────────────────────────────────────────────────────────────────────

class RunLog(Base):
    __tablename__ = "run_log"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=utcnow, index=True)
    finished_at = Column(DateTime)
    trigger = Column(String(30), default="manual")   # manual | cli | schedule
    stages = Column(JSONDict, default=dict)          # {stage: {ok, count, errors[]}}
    sources_discovered = Column(Integer, default=0)
    sources_fetched = Column(Integer, default=0)
    sources_duplicate = Column(Integer, default=0)
    signals_extracted = Column(Integer, default=0)
    themes_updated = Column(Integer, default=0)
    opportunities_created = Column(Integer, default=0)
    errors = Column(JSONList, default=list)
    notes = Column(Text)


ALL_TABLES = [
    Source,
    ExtractedSignal,
    Theme,
    ContentOpportunity,
    ContentDraft,
    VoiceExample,
    EngagementWatchlistItem,
    RunLog,
]
