"""Structured extraction from a single source.

Two backends, one contract (:class:`ExtractionResult`).

Both enforce the same integrity guarantee at the *code* level, not just in the
prompt: before anything is returned, every quote and evidence passage is
re-checked against the source text with :func:`fcie.utils.text.is_verbatim`.
Passages that fail the check are dropped and recorded in ``verification_notes``.
That means a hallucinating model cannot get a fabricated quote into the database.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import load_config
from ..pipeline.scoring import compute_opportunity_score, compute_risk_score, freshness_score
from ..utils.text import (
    extract_numerical_claims,
    extract_quotes,
    is_verbatim,
    looks_like_prose,
    select_evidence_passages,
    sentences,
    truncate,
    word_count,
)
from ..utils.urls import domain_of
from .client import AIClient
from .prompts import load_prompt
from .taxonomy import (
    THEME_BY_SLUG,
    THEME_NAMES,
    contains_phrase,
    match_customer_segment,
    match_entities,
    match_industries,
    match_themes,
)

log = logging.getLogger(__name__)

FORMATS = [
    "linkedin_post", "short_form_video_outline", "long_form_essay_outline",
    "executive_talking_point", "podcast_discussion_point", "customer_story_angle",
    "engagement_comment", "internal_briefing_note",
]

# Keyword-evidence floors for theme assignment. `match_themes` scores 1.0 per
# ordinary keyword hit and 1.5 per strong keyword, capped at 4 hits each — so
# 4.0 means several genuine mentions, not one passing reference.
PRIMARY_THEME_MIN_SCORE = 4.0
SECONDARY_THEME_MIN_SCORE = 3.0


@dataclass
class ExtractionResult:
    """Everything the extractor produces for one source."""

    # taxonomy
    primary_entity: str | None = None
    secondary_entities: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    customer_segment: str | None = None
    primary_theme: str | None = None
    secondary_themes: list[str] = field(default_factory=list)

    # facts
    customer_problem: str | None = None
    primary_claim: str | None = None
    supporting_evidence: list[dict] = field(default_factory=list)
    notable_quotes: list[dict] = field(default_factory=list)
    numerical_claims: list[dict] = field(default_factory=list)

    # interpretation
    founder_relevance: float = 0.0
    podium_relevance: float = 0.0
    novelty_score: float = 0.0
    freshness_score: float = 0.0
    evidence_strength: float = 0.0
    business_impact: float = 0.0
    risk_score: float = 0.0
    opportunity_score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)
    risk_breakdown: dict = field(default_factory=dict)

    content_opportunity: str | None = None
    potential_angle: str | None = None
    recommended_format: str | None = None

    # provenance
    is_familiar_narrative: bool = False
    is_promotional_source: bool = False
    is_summary_only: bool = False   # publisher RSS abstract; full body unavailable
    verification_notes: list[str] = field(default_factory=list)
    extraction_model: str = "heuristic-v1"
    extraction_method: str = "heuristic"
    extraction_error: str | None = None
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
# Verbatim gate — applied to BOTH backends
# ─────────────────────────────────────────────────────────────────────────────

def enforce_verbatim(result: ExtractionResult, source_text: str) -> ExtractionResult:
    """Drop any quote/passage that is not actually present in the source.

    This is the anti-hallucination backstop. It runs unconditionally.
    """
    kept_quotes, dropped_quotes = [], 0
    for quote in result.notable_quotes or []:
        text = (quote or {}).get("quote", "")
        if text and is_verbatim(text, source_text):
            quote["verified_verbatim"] = True
            kept_quotes.append(quote)
        else:
            dropped_quotes += 1
    result.notable_quotes = kept_quotes

    kept_evidence, dropped_evidence = [], 0
    for item in result.supporting_evidence or []:
        passage = (item or {}).get("passage", "")
        if passage and is_verbatim(passage, source_text):
            item["verified_verbatim"] = True
            kept_evidence.append(item)
        else:
            dropped_evidence += 1
    result.supporting_evidence = kept_evidence

    kept_numbers, dropped_numbers = [], 0
    for claim in result.numerical_claims or []:
        context = (claim or {}).get("context", "")
        if context and is_verbatim(context, source_text):
            claim["verified_verbatim"] = True
            claim.setdefault("needs_verification", True)
            kept_numbers.append(claim)
        else:
            dropped_numbers += 1
    result.numerical_claims = kept_numbers

    if dropped_quotes:
        result.verification_notes.append(
            f"{dropped_quotes} proposed quote(s) were discarded: the text does not appear "
            "verbatim in the source."
        )
    if dropped_evidence:
        result.verification_notes.append(
            f"{dropped_evidence} proposed evidence passage(s) were discarded as non-verbatim."
        )
    if dropped_numbers:
        result.verification_notes.append(
            f"{dropped_numbers} numerical claim(s) were discarded: context not found in the source."
        )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic backend
# ─────────────────────────────────────────────────────────────────────────────

_PROBLEM_MARKERS = (
    "problem", "struggle", "challenge", "fail", "miss", "lose", "lost", "can't",
    "cannot", "difficult", "friction", "bottleneck", "pain point", "wait",
    "delay", "shortage", "churn", "drop off", "abandon", "never",
)
_CLAIM_MARKERS = (
    "percent", "%", "according to", "found that", "reported", "survey", "study",
    "data shows", "research", "announced", "launched", "grew", "increase",
    "decrease", "average", "median", "respondents",
)
_FAMILIAR_PHRASES = (
    "ai is transforming", "the future of work", "game changer", "game-changer",
    "revolutionizing", "revolutionising", "in today's fast-paced",
    "artificial intelligence is changing", "unlock the power",
)


class HeuristicExtractor:
    """Deterministic analyser. No credentials, fully reproducible.

    It cannot reason, so it does not pretend to: it slices verbatim evidence,
    matches a keyword taxonomy, and derives scores from countable properties of
    the text. Its interpretation fields are explicitly templated and labelled.
    """

    model_name = "heuristic-v1"

    def __init__(self, config=None):
        self.cfg = config or load_config()

    def extract(self, *, text: str, title: str | None, url: str,
                published_at: datetime | None, source_type: str,
                domain: str | None = None, metadata: dict | None = None) -> ExtractionResult:
        metadata = metadata or {}
        domain = domain or domain_of(url)
        result = ExtractionResult(extraction_model=self.model_name, extraction_method="heuristic")
        haystack = f"{title or ''}\n{text or ''}"

        # ── entities ────────────────────────────────────────────────────
        entities = match_entities(haystack)
        all_entities = entities["podium"] + entities["competitors"] + entities["ai_vendors"]
        result.primary_entity = (
            entities["podium"][0] if entities["podium"]
            else (all_entities[0] if all_entities else (metadata.get("feed_name") or domain))
        )
        result.secondary_entities = [e for e in all_entities if e != result.primary_entity][:8]
        result.industries = match_industries(haystack)
        if metadata.get("industry_hint") and metadata["industry_hint"] not in result.industries:
            result.industries.insert(0, metadata["industry_hint"])
        result.industries = result.industries[:3]
        result.customer_segment = match_customer_segment(haystack)

        # ── themes ──────────────────────────────────────────────────────
        # A theme needs real keyword evidence, not one incidental mention.
        # Assigning on any non-zero match made "AI implementation challenges"
        # absorb security incidents, dev-tooling posts, job listings and general
        # AI news — 25 sources with nothing in common, which cannot support a
        # coherent founder narrative. An unclassified source is more useful than
        # a miscategorised one, because miscategorisation corrupts trend counts.
        theme_matches = match_themes(haystack, top_n=4)
        strong = [m for m in theme_matches if m[1] >= PRIMARY_THEME_MIN_SCORE]
        if strong:
            result.primary_theme = strong[0][0].name
            result.secondary_themes = [
                t.name for t, score, _k in theme_matches[1:4]
                if score >= SECONDARY_THEME_MIN_SCORE
            ]
        matched_keywords: list[str] = []
        for _theme, _score, keywords in theme_matches:
            matched_keywords.extend(keywords)

        # ── facts (verbatim slices) ─────────────────────────────────────
        result.customer_problem = self._pick_sentence(text, _PROBLEM_MARKERS, matched_keywords)
        result.primary_claim = (
            self._pick_sentence(text, _CLAIM_MARKERS, matched_keywords)
            or self._first_substantive_sentence(text)
        )
        # Theme keywords are what makes a passage evidence *for this theme*;
        # the generic list is only a tie-breaker.
        result.supporting_evidence = select_evidence_passages(
            text,
            ["ai", "customer", "business", "lead", "revenue", "appointment", "call"],
            limit=5,
            priority_keywords=matched_keywords or None,
        )
        result.notable_quotes = extract_quotes(text, limit=5)
        result.numerical_claims = extract_numerical_claims(text, limit=6)

        # ── scores ──────────────────────────────────────────────────────
        # First-party content is promotional wherever it is hosted. Podium's job
        # postings live on job-boards.greenhouse.io but are still the company
        # describing itself, and must not be counted as independent corroboration.
        result.is_promotional_source = bool(
            metadata.get("is_promotional")
            or metadata.get("first_party")
            or domain in {"podium.com"}
            or (domain or "").endswith(".podium.com")
        )
        result.is_summary_only = bool(metadata.get("summary_only"))
        result.is_familiar_narrative = self._is_familiar(haystack, theme_matches)

        result.podium_relevance = self._podium_relevance(haystack, entities, theme_matches, result.industries)
        result.founder_relevance = self._founder_relevance(haystack, entities, result.industries, result.podium_relevance)
        result.evidence_strength = self._evidence_strength(result, text, source_type, domain)
        result.business_impact = self._business_impact(haystack, result)
        result.novelty_score = self._novelty(result, theme_matches)
        fresh, fresh_reason = freshness_score(published_at, config=self.cfg.scoring.get("freshness"))
        result.freshness_score = fresh

        breakdown = compute_opportunity_score(
            {
                "podium_relevance": result.podium_relevance,
                "founder_relevance": result.founder_relevance,
                "evidence_strength": result.evidence_strength,
                "freshness": result.freshness_score,
                "novelty": result.novelty_score,
                "business_impact": result.business_impact,
            },
            weights=self.cfg.scoring_weights or None,
            notes=[fresh_reason, f"Analyser: {self.model_name} (rule-based, no LLM)."],
        )
        result.opportunity_score = breakdown.total
        result.score_breakdown = breakdown.to_dict()

        risk = compute_risk_score(self._risk_factors(result, published_at, entities, domain), config=self.cfg.scoring)
        result.risk_score = risk.total
        result.risk_breakdown = risk.to_dict()

        # ── interpretation (clearly templated) ──────────────────────────
        theme_name = result.primary_theme or "this topic"
        result.content_opportunity = (
            f"[Inference] Use this source as evidence for a founder point of view on "
            f"{theme_name.lower()}"
            + (f" in {result.industries[0].lower()}" if result.industries and result.industries[0] != "Cross-industry" else "")
            + "."
        )
        result.potential_angle = self._angle(result, theme_matches)
        result.recommended_format = self._format(result)

        # ── verification notes ──────────────────────────────────────────
        result.verification_notes.extend(self._verification_notes(result, published_at, text, domain))

        return enforce_verbatim(result, text or "")

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _pick_sentence(text: str | None, markers: tuple[str, ...],
                       bonus_keywords: list[str] | None = None) -> str | None:
        best, best_score = None, 0.0
        bonus = [k.lower() for k in (bonus_keywords or [])]
        for sentence in sentences(text):
            words = sentence.split()
            if len(words) < 8 or len(words) > 70:
                continue
            # A CTA banner is not a statement of a customer's problem.
            if not looks_like_prose(sentence):
                continue
            low = sentence.lower()
            score = sum(1.5 for m in markers if m in low)
            if not score:
                continue
            score += sum(0.5 for k in bonus if k in low)
            score -= len(words) / 100.0
            if score > best_score:
                best, best_score = sentence.strip(), score
        return best

    @staticmethod
    def _first_substantive_sentence(text: str | None) -> str | None:
        for sentence in sentences(text):
            if 10 <= len(sentence.split()) <= 60 and looks_like_prose(sentence):
                return sentence.strip()
        return None

    @staticmethod
    def _is_familiar(text: str, theme_matches) -> bool:
        low = text.lower()
        if any(phrase in low for phrase in _FAMILIAR_PHRASES):
            return True
        # Broad theme coverage with shallow keyword evidence = generic coverage.
        return bool(theme_matches) and theme_matches[0][1] < 3.0 and len(theme_matches) >= 3

    def _podium_relevance(self, text: str, entities, theme_matches, industries) -> float:
        score = 0.0
        if entities["podium"]:
            score += 5.0
        if any(contains_phrase(text, t) for t in ("ai employee", "ai agent", "agentic")):
            score += 2.0
        if entities["competitors"]:
            score += min(len(entities["competitors"]) * 0.8, 2.0)
        core_industries = {"Automotive", "Home services", "Aesthetics & medspa", "Healthcare", "Retail"}
        if core_industries & set(industries):
            score += 2.0
        if any(contains_phrase(text, t) for t in ("local business", "small business", "smb")):
            score += 1.5
        if theme_matches:
            score += min(theme_matches[0][1] / 6.0, 2.0)
        if any(contains_phrase(text, t) for t in
               ("missed call", "lead response", "speed to lead", "follow-up", "follow up")):
            score += 1.5
        return round(min(score, 10.0), 2)

    def _founder_relevance(self, text: str, entities, industries, podium_relevance: float) -> float:
        score = podium_relevance * 0.5
        if contains_phrase(text, "eric rea"):
            score += 3.5
        if any(contains_phrase(text, t) for t in
               ("founder", "ceo", "co-founder", "started the company")):
            score += 1.0
        # Operating-domain topics a local-business SaaS founder can speak to.
        operator_topics = (
            "local business", "small business", "dealership", "home services",
            "medspa", "front desk", "lead", "revenue", "appointment", "customer follow",
            "staffing", "receptionist",
        )
        score += min(sum(0.6 for t in operator_topics if contains_phrase(text, t)), 3.0)
        # Deep-tech research is low founder relevance even when AI-related.
        if any(contains_phrase(text, t) for t in
               ("benchmark", "parameter count", "training run", "gpu cluster",
                "model weights", "arxiv", "inference cost per token")):
            score -= 2.0
        return round(max(0.0, min(score, 10.0)), 2)

    def _evidence_strength(self, result: ExtractionResult, text: str | None,
                           source_type: str, domain: str) -> float:
        score = 2.0
        score += min(len(result.supporting_evidence) * 0.8, 3.0)
        score += min(len(result.notable_quotes) * 0.7, 2.0)
        score += min(len(result.numerical_claims) * 0.5, 2.0)

        words = word_count(text)
        if words > 800:
            score += 1.0
        elif words < 200:
            score -= 1.5

        if result.is_promotional_source:
            score -= 2.5
        if source_type == "youtube":
            score -= 1.0   # title + description only, not a full transcript
        if source_type.startswith("manual"):
            score -= 0.5   # human-supplied, unverified by the system
        if result.is_summary_only:
            score -= 2.0   # publisher abstract, not the full argument
        return round(max(0.0, min(score, 10.0)), 2)

    @staticmethod
    def _business_impact(text: str, result: ExtractionResult) -> float:
        score = 3.0
        money_terms = ("revenue", "profit", "cost", "roi", "booked", "conversion",
                       "close rate", "lost sales", "pipeline", "churn")
        score += min(sum(0.8 for t in money_terms if contains_phrase(text, t)), 3.5)
        if result.numerical_claims:
            score += min(len(result.numerical_claims) * 0.4, 1.5)
        scale_terms = ("thousands of", "millions", "industry-wide", "nationwide",
                       "across the industry", "every business")
        score += min(sum(0.6 for t in scale_terms if contains_phrase(text, t)), 1.2)
        if any(contains_phrase(text, t) for t in
               ("missed call", "unanswered", "lost lead", "no follow")):
            score += 1.0
        return round(max(0.0, min(score, 10.0)), 2)

    @staticmethod
    def _novelty(result: ExtractionResult, theme_matches) -> float:
        score = 5.0
        if result.is_familiar_narrative:
            score -= 2.5
        if result.numerical_claims:
            score += min(len(result.numerical_claims) * 0.5, 2.0)
        if result.notable_quotes:
            score += 1.0
        if result.is_promotional_source:
            score -= 1.5
        if theme_matches and theme_matches[0][1] >= 8:
            score += 1.0   # deep, specific engagement with one theme
        return round(max(0.0, min(score, 10.0)), 2)

    @staticmethod
    def _angle(result: ExtractionResult, theme_matches) -> str:
        theme = THEME_BY_SLUG.get(
            next((t.slug for t, _s, _k in theme_matches), ""), None
        )
        if theme:
            return (
                f"[Inference] {theme.description} This source can be cited as evidence "
                f"that the pattern is visible in "
                f"{', '.join(result.industries) if result.industries else 'the market'}."
            )
        return "[Inference] No strong theme match — review manually before using this source."

    @staticmethod
    def _format(result: ExtractionResult) -> str:
        if result.notable_quotes and result.evidence_strength >= 6:
            return "linkedin_post"
        if result.numerical_claims and result.business_impact >= 6:
            return "short_form_video_outline"
        if result.evidence_strength >= 7:
            return "long_form_essay_outline"
        if result.is_promotional_source:
            return "internal_briefing_note"
        return "executive_talking_point"

    @staticmethod
    def _risk_factors(result: ExtractionResult, published_at, entities, domain) -> dict[str, str]:
        detected: dict[str, str] = {}
        if result.evidence_strength < 4:
            detected["weak_sourcing"] = (
                f"Evidence strength {result.evidence_strength}/10 with "
                f"{len(result.supporting_evidence)} verbatim passage(s)."
            )
        if result.numerical_claims:
            detected["unverified_numbers"] = (
                f"{len(result.numerical_claims)} figure(s) taken from the source; none "
                "independently verified."
            )
        if entities["competitors"]:
            detected["competitor_claims"] = (
                "Named competitors present: " + ", ".join(entities["competitors"][:4])
            )
        if result.is_promotional_source:
            detected["promotional_source"] = f"{domain} content is vendor marketing."
        if result.is_familiar_narrative:
            detected["overused_narrative"] = "Source restates a widely published storyline."
        if published_at is None:
            detected["missing_publication_date"] = "No publication date found in the source."
        return detected

    @staticmethod
    def _verification_notes(result: ExtractionResult, published_at, text, domain) -> list[str]:
        notes: list[str] = []
        if published_at is None:
            notes.append(
                "No publication date could be extracted — treat recency claims with caution "
                "and confirm the date manually before citing."
            )
        for claim in result.numerical_claims[:4]:
            notes.append(
                f"Verify the figure “{claim['value']}” against a primary source before "
                "publication; the surrounding context is preserved but the methodology is not stated here."
            )
        if result.is_promotional_source:
            notes.append(
                f"{domain} is a vendor page. Treat its claims as evidence of positioning, "
                "not as independent market evidence."
            )
        if result.is_summary_only:
            notes.append(
                f"Full article body was not accessible at {domain} (access restriction — not "
                "bypassed). This analysis rests on the publisher's own RSS summary, so it "
                "captures the headline argument but not its supporting detail. Read the "
                "original before citing it."
            )
        if not result.supporting_evidence:
            notes.append(
                "No evidence passage met the verbatim threshold — do not build a claim on this "
                "source alone."
            )
        if result.notable_quotes:
            notes.append(
                f"{len(result.notable_quotes)} quote(s) captured verbatim; confirm the speaker "
                "attribution against the original page before use."
            )
        return notes


# ─────────────────────────────────────────────────────────────────────────────
# LLM backend
# ─────────────────────────────────────────────────────────────────────────────

class LLMExtractor:
    """OpenAI-backed extractor driven by ``prompts/source_extraction.md``.

    Output is validated, coerced, and passed through the same verbatim gate as
    the heuristic path. On any failure the caller falls back to the heuristic
    extractor rather than losing the source.
    """

    def __init__(self, client: AIClient | None = None, config=None):
        self.cfg = config or load_config()
        self.client = client or AIClient()

    @property
    def available(self) -> bool:
        return self.client.available

    def extract(self, *, text: str, title: str | None, url: str,
                published_at: datetime | None, source_type: str,
                domain: str | None = None, metadata: dict | None = None) -> ExtractionResult:
        metadata = metadata or {}
        domain = domain or domain_of(url)
        prompt = load_prompt("source_extraction").render(
            title=title or "(untitled)",
            url=url,
            domain=domain,
            published=published_at.isoformat() if published_at else "NOT STATED IN SOURCE",
            source_type=source_type,
            search_query=metadata.get("search_query") or "n/a",
            text=truncate(text, self.cfg.ai.max_extraction_chars),
            theme_list="\n".join(f"- {name}" for name in THEME_NAMES),
        )
        response = self.client.complete_json(prompt, max_tokens=3500)

        if not response.ok:
            result = HeuristicExtractor(self.cfg).extract(
                text=text, title=title, url=url, published_at=published_at,
                source_type=source_type, domain=domain, metadata=metadata,
            )
            result.extraction_error = f"LLM extraction failed, used heuristic fallback: {response.error}"
            result.verification_notes.insert(0, result.extraction_error)
            return result

        result = self._coerce(response.data, published_at, domain)
        result.extraction_model = response.model or self.cfg.ai.model
        result.extraction_method = "llm"

        # Score with the same deterministic engine used by the heuristic path,
        # so LLM and heuristic rows remain directly comparable.
        fresh, fresh_reason = freshness_score(published_at, config=self.cfg.scoring.get("freshness"))
        result.freshness_score = fresh
        breakdown = compute_opportunity_score(
            {
                "podium_relevance": result.podium_relevance,
                "founder_relevance": result.founder_relevance,
                "evidence_strength": result.evidence_strength,
                "freshness": result.freshness_score,
                "novelty": result.novelty_score,
                "business_impact": result.business_impact,
            },
            weights=self.cfg.scoring_weights or None,
            notes=[fresh_reason, f"Component scores proposed by {result.extraction_model}; "
                                 "weighting applied deterministically."],
        )
        result.opportunity_score = breakdown.total
        result.score_breakdown = breakdown.to_dict()

        entities = match_entities(f"{title or ''}\n{text or ''}")
        risk = compute_risk_score(
            HeuristicExtractor._risk_factors(result, published_at, entities, domain),
            config=self.cfg.scoring,
        )
        result.risk_score = risk.total
        result.risk_breakdown = risk.to_dict()

        return enforce_verbatim(result, text or "")

    @staticmethod
    def _coerce(data: dict[str, Any], published_at, domain: str) -> ExtractionResult:
        def as_list(value) -> list:
            if isinstance(value, list):
                return [v for v in value if v not in (None, "")]
            return [value] if value else []

        def as_float(value, default=0.0) -> float:
            try:
                return max(0.0, min(10.0, float(value)))
            except (TypeError, ValueError):
                return default

        def as_str(value) -> str | None:
            if value in (None, "", "N/A", "n/a", "unknown", "TBD"):
                return None
            return str(value).strip()

        result = ExtractionResult()
        result.primary_entity = as_str(data.get("primary_entity")) or domain
        result.secondary_entities = [str(v) for v in as_list(data.get("secondary_entities"))][:10]
        result.industries = [str(v) for v in as_list(data.get("industries"))][:3] or ["Cross-industry"]
        result.customer_segment = as_str(data.get("customer_segment"))

        theme = as_str(data.get("primary_theme"))
        result.primary_theme = theme if theme in THEME_NAMES else None
        result.secondary_themes = [t for t in as_list(data.get("secondary_themes")) if t in THEME_NAMES][:3]

        result.customer_problem = as_str(data.get("customer_problem"))
        result.primary_claim = as_str(data.get("primary_claim"))

        # A live model sometimes answers "which claim does this support?" with the
        # *field name* from the schema ("primary_claim") rather than a summary.
        # Reject identifier-shaped answers at the boundary so they can never be
        # rendered as a bullet downstream.
        def as_supports(value) -> str | None:
            text = as_str(value)
            if not text or len(text.split()) < 4:
                return None
            if re.fullmatch(r"[a-z0-9_]+", text.strip()):
                return None
            return text

        for item in as_list(data.get("supporting_evidence")):
            if isinstance(item, dict) and item.get("passage"):
                result.supporting_evidence.append({
                    "passage": str(item["passage"]),
                    "supports": as_supports(item.get("supports")),
                    "verified_verbatim": False,   # proven by enforce_verbatim
                })
            elif isinstance(item, str):
                result.supporting_evidence.append({"passage": item, "supports": None,
                                                   "verified_verbatim": False})

        for item in as_list(data.get("notable_quotes")):
            if isinstance(item, dict) and item.get("quote"):
                result.notable_quotes.append({
                    "quote": str(item["quote"]),
                    "speaker": as_str(item.get("speaker")),
                    "verified_verbatim": False,
                })
            elif isinstance(item, str):
                result.notable_quotes.append({"quote": item, "speaker": None,
                                              "verified_verbatim": False})

        for item in as_list(data.get("numerical_claims")):
            if isinstance(item, dict) and item.get("value"):
                result.numerical_claims.append({
                    "value": str(item["value"]),
                    "context": str(item.get("context", "")),
                    "needs_verification": True,
                    "verified_verbatim": False,
                })

        result.podium_relevance = as_float(data.get("podium_relevance"))
        result.founder_relevance = as_float(data.get("founder_relevance"))
        result.novelty_score = as_float(data.get("novelty_score"))
        result.evidence_strength = as_float(data.get("evidence_strength"))
        result.business_impact = as_float(data.get("business_impact"))

        result.is_familiar_narrative = bool(data.get("is_familiar_narrative"))
        result.is_promotional_source = bool(data.get("is_promotional_source"))

        result.content_opportunity = as_str(data.get("content_opportunity"))
        result.potential_angle = as_str(data.get("potential_angle"))
        fmt = as_str(data.get("recommended_format"))
        result.recommended_format = fmt if fmt in FORMATS else "executive_talking_point"

        result.verification_notes = [str(v) for v in as_list(data.get("verification_notes"))]
        if published_at is None:
            result.verification_notes.append(
                "No publication date in the source — confirm the date before citing recency."
            )
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Facade
# ─────────────────────────────────────────────────────────────────────────────

class Extractor:
    """Chooses the LLM backend when available, otherwise the heuristic one."""

    def __init__(self, client: AIClient | None = None, config=None, force_heuristic: bool = False):
        self.cfg = config or load_config()
        self.client = client or AIClient()
        self.force_heuristic = force_heuristic
        self.heuristic = HeuristicExtractor(self.cfg)
        self.llm = LLMExtractor(self.client, self.cfg)

    @property
    def backend(self) -> str:
        return "llm" if (self.llm.available and not self.force_heuristic) else "heuristic"

    @property
    def backend_note(self) -> str:
        if self.backend == "llm":
            return f"LLM extraction via {self.cfg.ai.model}. Verbatim gate active."
        return self.client.setup_message

    def extract(self, **kwargs) -> ExtractionResult:
        if self.backend == "llm":
            return self.llm.extract(**kwargs)
        return self.heuristic.extract(**kwargs)
