"""Content opportunity and brief generation.

A theme with enough corroboration becomes a :class:`ContentOpportunity` — the
primary product output. Every supporting point carries source ids and a verbatim
evidence passage; points that cannot be evidenced are dropped, not softened.

Both backends produce the same structure. The heuristic backend composes the
brief from real extracted material (verbatim passages, matched themes, computed
statistics) using explicit templates, and labels its inference fields as such.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select

from ..ai.client import AIClient
from ..ai.prompts import load_prompt
from ..ai.taxonomy import THEMES, contains_phrase
from ..config import load_config
from ..db import session_scope
from ..models import ContentDraft, ContentOpportunity, ExtractedSignal, Source, Theme
from ..utils.format import (
    count_label,
    growth_phrase,
    industry_phrase,
    truncate_words,
)
from ..utils.text import truncate
from .scoring import compute_confidence, compute_opportunity_score, compute_risk_score

log = logging.getLogger(__name__)

PROMOTABLE_STATUSES = {"emerging", "rising", "stable", "saturated"}


@dataclass
class OpportunityReport:
    created: int = 0
    updated: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    opportunity_ids: list[int] = field(default_factory=list)
    backend: str = "heuristic"

    def as_dict(self) -> dict:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped[:20],
            "errors": self.errors[:20],
            "backend": self.backend,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Evidence assembly
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ThemeEvidence:
    theme: dict
    sources: list[dict] = field(default_factory=list)
    passages: list[dict] = field(default_factory=list)
    quotes: list[dict] = field(default_factory=list)
    numbers: list[dict] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)

    @property
    def distinct_domains(self) -> list[str]:
        return sorted({s["domain"] for s in self.sources if s["domain"]})

    @property
    def distinct_industries(self) -> list[str]:
        out: set[str] = set()
        for source in self.sources:
            out.update(source.get("industries") or [])
        return sorted(out)

    def dominant_industries(self, limit: int = 2) -> list[str]:
        """Industries ranked by how many sources mention them.

        Alphabetical order would put "Aesthetics & medspa" first on every theme
        regardless of whether the evidence is actually about medspas — which
        makes every brief title look identical and misdescribes the corpus.
        """
        counts: dict[str, int] = {}
        for source in self.sources:
            for industry in (source.get("industries") or []):
                if industry == "Cross-industry":
                    continue
                counts[industry] = counts.get(industry, 0) + 1
        ranked = sorted(counts, key=lambda i: (-counts[i], i))
        # Only report an industry that shows up in a meaningful share of sources.
        floor = max(2, len(self.sources) // 5)
        return [i for i in ranked if counts[i] >= floor][:limit]

    @property
    def has_dated_sources(self) -> bool:
        return any(s.get("published_at") for s in self.sources)


def collect_theme_evidence(theme_name: str, *, limit: int = 25) -> ThemeEvidence:
    """Pull every stored fact backing a theme, with source attribution intact."""
    with session_scope() as session:
        theme_row = session.execute(
            select(Theme).where(Theme.name == theme_name)
        ).scalar_one_or_none()
        theme_payload = {
            "id": theme_row.id if theme_row else None,
            "name": theme_name,
            "description": theme_row.description if theme_row else "",
            "trend_status": theme_row.trend_status if theme_row else "unknown",
            "source_count": theme_row.source_count if theme_row else 0,
            "current_period_count": theme_row.current_period_count if theme_row else 0,
            "previous_period_count": theme_row.previous_period_count if theme_row else 0,
            "growth_rate": theme_row.growth_rate if theme_row else 0.0,
            "avg_relevance": theme_row.average_relevance if theme_row else 0.0,
            "avg_founder_relevance": theme_row.average_founder_relevance if theme_row else 0.0,
            "avg_evidence": theme_row.average_evidence_strength if theme_row else 0.0,
            "avg_impact": theme_row.average_business_impact if theme_row else 0.0,
            "rationale": theme_row.trend_rationale if theme_row else "",
            "distinct_domain_count": theme_row.distinct_domain_count if theme_row else 0,
            "distinct_industry_count": theme_row.distinct_industry_count if theme_row else 0,
        }

        rows = session.execute(
            select(Source, ExtractedSignal)
            .join(ExtractedSignal, ExtractedSignal.source_id == Source.id)
            .order_by(ExtractedSignal.opportunity_score.desc())
        ).all()

    evidence = ThemeEvidence(theme=theme_payload)
    for source, signal in rows:
        is_primary = signal.primary_theme == theme_name
        is_secondary = theme_name in (signal.secondary_themes or [])
        if not (is_primary or is_secondary):
            continue
        if len(evidence.sources) >= limit:
            break

        evidence.sources.append({
            "id": source.id,
            "title": source.title or "(untitled)",
            "url": source.canonical_url,
            "domain": source.source_domain,
            "author": source.author,
            "published_at": source.published_at,
            "source_type": source.source_type,
            "assignment": "primary" if is_primary else "secondary",
            "industries": signal.industries or [],
            "podium_relevance": signal.podium_relevance,
            "founder_relevance": signal.founder_relevance,
            "evidence_strength": signal.evidence_strength,
            "business_impact": signal.business_impact,
            "novelty": signal.novelty_score,
            "freshness": signal.freshness_score,
            "opportunity_score": signal.opportunity_score,
            "is_promotional": signal.is_promotional_source,
            "is_familiar": signal.is_familiar_narrative,
            "extraction_method": signal.extraction_method,
        })

        for passage in (signal.supporting_evidence or []):
            if passage.get("passage") and passage.get("verified_verbatim"):
                evidence.passages.append({
                    "source_id": source.id,
                    "url": source.canonical_url,
                    "domain": source.source_domain,
                    "title": source.title,
                    "passage": passage["passage"],
                    "supports": passage.get("supports"),
                })
        for quote in (signal.notable_quotes or []):
            if quote.get("quote") and quote.get("verified_verbatim"):
                evidence.quotes.append({
                    "source_id": source.id,
                    "url": source.canonical_url,
                    "quote": quote["quote"],
                    "speaker": quote.get("speaker"),
                })
        for number in (signal.numerical_claims or []):
            if number.get("value"):
                evidence.numbers.append({
                    "source_id": source.id,
                    "url": source.canonical_url,
                    "value": number["value"],
                    "context": number.get("context", ""),
                })
        if signal.customer_problem:
            evidence.problems.append({"source_id": source.id, "text": signal.customer_problem,
                                      "url": source.canonical_url})
        if signal.primary_claim:
            evidence.claims.append({"source_id": source.id, "text": signal.primary_claim,
                                    "url": source.canonical_url})

    _rank_evidence(evidence)
    return evidence


# Vendor-marketing tells that make a passage useless as market evidence even
# though it is verbatim and on-topic.
_MARKETING_TELLS = (
    "awarded", "highlighted by", "named to", "recognized as", "recognised as",
    "ranked #", "#1 ai", "our platform", "our ai employee", "we help businesses",
    "join us", "we're looking for", "we are looking for", "you'll be", "the role",
    "reply to get", "text us", "% off your",
)


def _passage_quality(passage: dict, promotional_ids: set[int],
                     theme_keywords: tuple[str, ...] = (),
                     negative_keywords: tuple[str, ...] = ()) -> float:
    """Higher is better.

    Topical fit is weighted *above* independence. Ranking on independence alone
    surfaced an AWS earnings line from a tech outlet ahead of a directly relevant
    vendor passage — technically independent, and completely off-theme. A
    passage has to be about the theme before its provenance matters.
    """
    text = passage.get("passage", "")
    low = text.lower()
    score = 0.0

    # A keyword hit in the wrong sense ("after-hours trading") is not topical.
    if any(contains_phrase(low, kw) for kw in negative_keywords):
        return -10.0

    topical = sum(1 for kw in theme_keywords if contains_phrase(low, kw))
    if theme_keywords:
        if not topical:
            score -= 8.0      # off-theme: disqualifying, whatever the source
        else:
            score += min(topical, 3) * 4.0

    if passage.get("source_id") not in promotional_ids:
        score += 3.0          # independent corroboration, once relevance is met
    if any(tell in low for tell in _MARKETING_TELLS):
        score -= 4.0
    if re.search(r"\d", text):
        score += 1.5          # a figure is harder evidence
    words = len(text.split())
    if 12 <= words <= 45:
        score += 1.0          # quotable length
    return score


def _quote_quality(quote: dict, promotional_ids: set[int],
                   theme_keywords: tuple[str, ...] = (),
                   negative_keywords: tuple[str, ...] = ()) -> float:
    text = quote.get("quote", "")
    low = text.lower()

    # A quote in the wrong sense is worse than no quote — it becomes the hook.
    if any(contains_phrase(low, kw) for kw in negative_keywords):
        return -10.0

    score = 0.0
    # Off-theme is a heavy penalty, not an early exit: the remaining signals
    # still decide the ordering *among* off-theme quotes, so an attributed,
    # substantive quote outranks a marketing fragment either way.
    if theme_keywords and not any(contains_phrase(low, kw) for kw in theme_keywords):
        score -= 5.0

    if quote.get("speaker"):
        score += 3.0          # attributed quotes are far more usable
    if re.search(r"\d", text):
        score += 2.0
    if any(tell in low for tell in _MARKETING_TELLS):
        score -= 5.0
    words = len(text.split())
    if words < 8:
        score -= 3.0          # a fragment is not a quote
    elif 10 <= words <= 45:
        score += 1.5
    if quote.get("source_id") not in promotional_ids:
        score += 1.0
    return score


def _theme_keywords(theme_name: str) -> tuple[str, ...]:
    theme = next((t for t in THEMES if t.name == theme_name), None)
    if theme is None:
        return ()
    return tuple(dict.fromkeys(theme.strong_keywords + theme.keywords))


def _theme_negatives(theme_name: str) -> tuple[str, ...]:
    theme = next((t for t in THEMES if t.name == theme_name), None)
    return theme.negative_keywords if theme else ()


def _rank_evidence(evidence: ThemeEvidence) -> None:
    """Order evidence so the most on-theme, best-sourced material leads.

    Without this a brief opens with whatever the highest-scoring *source*
    happened to yield first — which, in a corpus containing a vendor's own
    marketing pages, is often a call-to-action or a sample promotional SMS.
    """
    promotional_ids = {s["id"] for s in evidence.sources if s.get("is_promotional")}
    theme_name = evidence.theme.get("name", "")
    keywords = _theme_keywords(theme_name)
    negatives = _theme_negatives(theme_name)

    def quality(passage: dict) -> float:
        return _passage_quality(passage, promotional_ids, keywords, negatives)

    evidence.passages.sort(key=lambda p: -quality(p))
    # Drop passages that are simply not about this theme rather than ranking
    # them last — an off-theme quote in a brief is a credibility problem.
    if keywords:
        on_theme = [p for p in evidence.passages if quality(p) > 0]
        if on_theme:
            evidence.passages = on_theme

    evidence.quotes.sort(
        key=lambda q: -_quote_quality(q, promotional_ids, keywords, negatives)
    )

    # Numbers get the same treatment: a figure quoted out of its subject is the
    # easiest way to mislead, and the hook falls back to a number when no quote
    # clears the bar. "$4 billion of OpenAI investment" is not evidence about
    # local-business agents.
    def number_rank(number: dict) -> tuple:
        context = (number.get("context") or "").lower()
        off_theme = bool(keywords) and not any(contains_phrase(context, k) for k in keywords)
        wrong_sense = any(contains_phrase(context, k) for k in negatives)
        return (wrong_sense, off_theme, number["source_id"] in promotional_ids,
                -len(number.get("context", "")))

    evidence.numbers.sort(key=number_rank)
    on_theme_numbers = [
        n for n in evidence.numbers
        if not number_rank(n)[0] and not number_rank(n)[1]
    ]
    evidence.numbers = on_theme_numbers or []

    # Problem statements are the final hook fallback, so they need the same
    # filter — otherwise an off-theme sentence reaches the top of a post simply
    # by being last in the chain.
    def text_rank(item: dict) -> tuple:
        body = (item.get("text") or "").lower()
        off_theme = bool(keywords) and not any(contains_phrase(body, k) for k in keywords)
        wrong_sense = any(contains_phrase(body, k) for k in negatives)
        return (wrong_sense, off_theme, item["source_id"] in promotional_ids)

    for attr in ("problems", "claims"):
        items = getattr(evidence, attr)
        items.sort(key=text_rank)
        on_theme = [i for i in items if not text_rank(i)[0] and not text_rank(i)[1]]
        setattr(evidence, attr, on_theme or [])


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic brief builder
# ─────────────────────────────────────────────────────────────────────────────

class HeuristicBriefBuilder:
    """Compose a brief from real extracted material using explicit templates.

    It never writes a factual sentence that is not backed by a stored verbatim
    passage, and every inference is prefixed so a reviewer can see the seam
    between evidence and interpretation.
    """

    method = "heuristic-v1"

    def build(self, evidence: ThemeEvidence) -> dict:
        theme = evidence.theme
        name = theme["name"]
        theme_def = next((t for t in THEMES if t.name == name), None)
        description = theme_def.description if theme_def else theme.get("description", "")

        domains = evidence.distinct_domains
        industries = evidence.dominant_industries(limit=3)
        dated = [s for s in evidence.sources if s.get("published_at")]
        dated.sort(key=lambda s: s["published_at"], reverse=True)

        supporting_points = self._supporting_points(evidence)
        title = self._title(name, description, evidence)

        core_insight = self._core_insight(evidence, description, domains, industries)
        why_now = self._why_now(theme, dated, domains)
        why_podium = self._why_podium(name, industries, evidence)
        why_eric = self._why_eric(industries)

        return {
            "title": title,
            "core_insight": core_insight,
            "why_now": why_now,
            "why_podium": why_podium,
            "why_eric": why_eric,
            "target_audience": self._audience(industries),
            "founder_point_of_view": self._point_of_view(name, description, evidence),
            "hook": self._hook(evidence, name),
            "supporting_points": supporting_points,
            "potential_objections": self._objections(evidence, domains),
            "recommended_format": self._format(evidence),
            "suggested_call_to_action": self._cta(name),
            "verification_checklist": self._checklist(evidence),
            "risk_notes": [],
            "confidence_note": self._confidence_note(evidence, domains),
            "generation_method": self.method,
        }

    # ── components ──────────────────────────────────────────────────────

    @staticmethod
    def _title(name: str, description: str, evidence: ThemeEvidence) -> str:
        """A short, arguable claim — nothing else.

        This used to append the industry list and the source/domain counts,
        producing titles like "Framing AI as absorbing tasks and workflows
        rather than eliminating roles in b2b saas and local business (general)
        and home services — 8 public source(s) across 5 domain(s)". Unreadable,
        and the counts belong on a metadata line where they can be *scanned*
        rather than read. The title's only job is to state the argument.
        """
        claim = (description or name).strip().rstrip(".")
        if not claim:
            return name

        # Keep it to one clause: the first sentence, and no trailing subordinate
        # clause that turns a headline into a paragraph.
        claim = claim.split(". ")[0].strip().rstrip(".")
        if len(claim.split()) > 14:
            claim = truncate_words(claim, 14)

        return claim[0].upper() + claim[1:] if claim else name

    @staticmethod
    def _core_insight(evidence: ThemeEvidence, description: str,
                      domains: list[str], industries: list[str]) -> str:
        parts = [description.rstrip(".") + "." if description else ""]

        scope = ""
        phrase = industry_phrase(industries, limit=3)
        if phrase:
            scope = f", spanning {phrase}"
        independent = [s for s in evidence.sources if not s.get("is_promotional")]
        parts.append(
            f"Across {count_label(len(evidence.sources), 'public source')} from "
            f"{count_label(len(domains), 'distinct domain')}{scope}, "
            f"{count_label(len(evidence.passages), 'verbatim passage')} touch on this "
            f"pattern — {len(independent)} of them independent of any vendor."
        )
        if evidence.problems:
            parts.append(
                "The most concrete problem statement found in the sources: "
                f"“{truncate(evidence.problems[0]['text'], 260)}” "
                f"(source #{evidence.problems[0]['source_id']})."
            )
        return " ".join(p for p in parts if p)

    @staticmethod
    def _why_now(theme: dict, dated: list[dict], domains: list[str]) -> str:
        status = theme.get("trend_status", "unknown")
        current = theme.get("current_period_count", 0)
        previous = theme.get("previous_period_count", 0)
        growth = theme.get("growth_rate", 0.0)

        line = (
            f"Trend status is **{status}**: {count_label(current, 'source')} in the current period "
            f"against {previous} in the previous period"
        )
        line += f" ({growth:+.0%} change)." if previous else "."

        if dated:
            newest = dated[0]
            line += (
                f" The most recent dated source is “{truncate(newest['title'], 90)}” "
                f"({newest['domain']}, {newest['published_at'].date().isoformat()})."
            )
        else:
            line += " No source in this cluster carries a publication date — recency cannot be asserted."

        if len(domains) < 2:
            line += " [Caution] All evidence comes from a single domain; this is not corroboration."
        return line

    @staticmethod
    def _why_podium(name: str, industries: list[str], evidence: ThemeEvidence) -> str:
        avg_relevance = evidence.theme.get("avg_relevance", 0.0)
        text = (
            f"Podium sells AI agents to local businesses whose revenue depends on answering and "
            f"following up on inbound demand. This theme ({name.lower()}) scores {avg_relevance}/10 "
            f"average Podium relevance across the cluster."
        )
        if industries:
            text += f" The sources touch {', '.join(industries[:3]).lower()} — served by Podium's industry pages."
        first_party = [s for s in evidence.sources if s["domain"] == "podium.com"]
        if first_party:
            text += (
                f" {count_label(len(first_party), 'supporting source')} are Podium's own public pages, "
                "which show positioning rather than independent market evidence."
            )
        return text

    @staticmethod
    def _why_eric(industries: list[str]) -> str:
        return (
            "[Inference — based on the public record only] Eric Rea is the co-founder and CEO of "
            "Podium, a company whose public positioning is built around local-business "
            "communication and revenue operations"
            + (f", including {', '.join(industries[:2]).lower()}" if industries else "")
            + ". That gives a founder in this seat direct commercial standing to discuss this "
            "problem. This system makes no claim about what he has said, thinks, or would endorse — "
            "no statement here has been written or approved by him."
        )

    @staticmethod
    def _audience(industries: list[str]) -> str:
        if industries:
            return (
                f"Owners and operators in {', '.join(industries[:3]).lower()}, plus the "
                "B2B SaaS operators and investors who sell into them."
            )
        return "Local-business owners and operators, and the B2B SaaS leaders selling to them."

    @staticmethod
    def _point_of_view(name: str, description: str, evidence: ThemeEvidence) -> str:
        return (
            f"[Inference — this is the argument, not a source finding] {description} "
            f"The evidence collected here suggests the constraint is operational rather than "
            f"technological: the pattern shows up across {len(evidence.distinct_domains)} independent "
            f"independent domains and {count_label(len(evidence.sources), 'source')}, pointing to a structural gap in "
            f"how local businesses handle demand rather than an isolated tooling failure. "
            f"A founder writing on this should argue the operational case and let the cited "
            f"sources carry the factual load."
        )

    @staticmethod
    def _hook(evidence: ThemeEvidence, name: str) -> str:
        """Open with the strongest genuinely quotable material — or nothing.

        Evidence is already quality-ranked, but a weak best-quote is worse than
        no quote: opening a founder post with a sample marketing SMS destroys
        credibility. So a quote must clear a bar before it is used as a hook.
        """
        promotional_ids = {s["id"] for s in evidence.sources if s.get("is_promotional")}

        theme_name = evidence.theme.get("name", "")
        keywords = _theme_keywords(theme_name)
        negatives = _theme_negatives(theme_name)

        if evidence.quotes:
            quote = evidence.quotes[0]
            if _quote_quality(quote, promotional_ids, keywords, negatives) >= 2.0:
                attribution = f" — {quote['speaker']}" if quote.get("speaker") else ""
                return (f"“{truncate(quote['quote'], 180)}”{attribution} "
                        f"(source #{quote['source_id']})")

        if evidence.numbers:
            number = evidence.numbers[0]
            if number["source_id"] not in promotional_ids or len(evidence.numbers) == 1:
                return (
                    f"{number['value']} — from “{truncate(number['context'], 150)}” "
                    f"(source #{number['source_id']}; verify before use)."
                )

        # Prefer a problem statement from an independent source.
        for problem in evidence.problems:
            if problem["source_id"] not in promotional_ids:
                return truncate(problem["text"], 190)
        if evidence.problems:
            return truncate(evidence.problems[0]["text"], 190)

        return (f"{name}: a pattern visible across {count_label(len(evidence.sources), 'public source')} "
                f"from {count_label(len(evidence.distinct_domains), 'domain')}.")

    @staticmethod
    def _usable_supports(supports: str | None) -> str | None:
        """Return the model's `supports` note only if it is actually a summary.

        The extraction schema asks what a passage supports; a live model
        sometimes echoes the *field name* instead ("primary_claim"), which then
        rendered as a bullet reading "primary_claim." — no meaning, no verbatim
        match, and an evidence score of zero. Anything that looks like an
        identifier or is too short to be a claim is discarded in favour of the
        passage itself.
        """
        text = (supports or "").strip()
        if len(text.split()) < 4:
            return None
        if re.fullmatch(r"[a-z0-9_]+", text):       # snake_case identifier
            return None
        if text.lower().replace(" ", "_") in {
            "primary_claim", "customer_problem", "supporting_evidence",
            "notable_quotes", "numerical_claims", "content_opportunity",
        }:
            return None
        return text

    @classmethod
    def _point_text(cls, passage: dict) -> str:
        return cls._usable_supports(passage.get("supports")) or truncate(passage["passage"], 200)

    @staticmethod
    def _supporting_points(evidence: ThemeEvidence, target: int = 5) -> list[dict]:
        """Every point carries a source id and a verbatim passage. No exceptions.

        ``evidence.passages`` arrives quality-ranked (independent sources first),
        so taking them in order naturally leads with non-vendor evidence.
        """
        points: list[dict] = []
        used_sources: set[int] = set()
        # Boilerplate repeats verbatim across pages of the same site (every job
        # posting carries the same company paragraph). Three bullets quoting one
        # sentence three times is not three points.
        seen_passages: set[str] = set()

        def key(passage: dict) -> str:
            return " ".join(passage["passage"].lower().split())[:120]

        def add(passage: dict) -> None:
            points.append({
                "point": HeuristicBriefBuilder._point_text(passage),
                "evidence_source_ids": [passage["source_id"]],
                "evidence_passage": passage["passage"],
                "evidence_url": passage["url"],
                "evidence_domain": passage["domain"],
            })
            seen_passages.add(key(passage))
            used_sources.add(passage["source_id"])

        # Prefer breadth: one passage per source before reusing any source.
        for passage in evidence.passages:
            if len(points) >= target:
                break
            if passage["source_id"] in used_sources or key(passage) in seen_passages:
                continue
            add(passage)

        if len(points) < 3:
            for passage in evidence.passages:
                if len(points) >= target:
                    break
                if key(passage) in seen_passages:
                    continue
                add(passage)
        return points

    @staticmethod
    def _objections(evidence: ThemeEvidence, domains: list[str]) -> list[dict]:
        objections = [{
            "objection": "This is a vendor-friendly framing — of course an AI company says "
                         "businesses are missing revenue.",
            "response": (
                f"Fair. {len([s for s in evidence.sources if s['is_promotional']])} of "
                f"{count_label(len(evidence.sources), 'supporting source')} are vendor marketing and are "
                "flagged as such in the source library. The argument should stand on the "
                "non-vendor sources or be narrowed."
            ),
        }]
        if len(domains) < 3:
            objections.append({
                "objection": f"Only {count_label(len(domains), 'distinct domain')} support this. That is thin.",
                "response": "Correct — this brief should be treated as a hypothesis to test with "
                            "more sources or first-party data, not a settled finding.",
            })
        else:
            objections.append({
                "objection": "Every vendor claims the problem their product solves is the "
                             "industry's biggest problem.",
                "response": (
                    f"The pattern here appears across {len(domains)} independent domains "
                    "rather than one vendor's blog, which is the minimum bar for treating it "
                    "as a market signal rather than positioning."
                ),
            })
        if evidence.numbers:
            objections.append({
                "objection": "The numbers cited come from interested parties.",
                "response": "Agreed — every figure in this brief is flagged for verification "
                            "and should be replaced with a primary source or dropped.",
            })
        return objections

    @staticmethod
    def _format(evidence: ThemeEvidence) -> str:
        if evidence.quotes and len(evidence.distinct_domains) >= 3:
            return "linkedin_post"
        if evidence.numbers:
            return "short_form_video_outline"
        if len(evidence.sources) >= 6:
            return "long_form_essay_outline"
        return "executive_talking_point"

    @staticmethod
    def _cta(name: str) -> str:
        return (
            f"Ask the reader to audit their own operation against this pattern "
            f"({name.lower()}) this week, and to report what they find — an invitation to "
            "compare notes, not a product pitch."
        )

    @staticmethod
    def _checklist(evidence: ThemeEvidence) -> list[dict]:
        items = [
            {"item": "Open every cited source URL and confirm the passage still appears on the page.",
             "why": "Pages get edited and removed; a broken citation destroys credibility.", "done": False},
            {"item": "Confirm the publication date of each cited source.",
             "why": "Recency claims are the easiest thing to get wrong.", "done": False},
        ]
        for number in evidence.numbers[:4]:
            items.append({
                "item": f"Verify “{number['value']}” against a primary source "
                        f"(currently from source #{number['source_id']}).",
                "why": "The source states the figure but not its methodology or sample.",
                "done": False,
            })
        for quote in evidence.quotes[:3]:
            items.append({
                "item": f"Confirm the speaker attribution for: “{truncate(quote['quote'], 90)}”",
                "why": "Misattributing a quote is a reputational and legal risk.",
                "done": False,
            })
        promotional = [s for s in evidence.sources if s["is_promotional"]]
        if promotional:
            items.append({
                "item": f"Decide whether the {count_label(len(promotional), 'vendor-marketing source')} should be "
                        "cited publicly at all.",
                "why": "Citing marketing copy as market evidence is the fastest way to lose an argument.",
                "done": False,
            })
        items.append({
            "item": "Confirm no sentence implies Eric Rea wrote, reviewed, or approved this draft.",
            "why": "This is an independent prototype with no affiliation or endorsement.",
            "done": False,
        })
        return items

    @staticmethod
    def _confidence_note(evidence: ThemeEvidence, domains: list[str]) -> str:
        if len(domains) <= 1:
            return (
                "Weak evidence base: a single domain. Treat this as a prompt for further "
                "research rather than a publishable position."
            )
        if len(evidence.passages) < 3:
            return (
                f"Thin evidence: only {count_label(len(evidence.passages), 'verbatim passage')} survived the "
                "verbatim check. The argument needs more sourcing before publication."
            )
        return (
            f"Moderate evidence base: {count_label(len(evidence.passages), 'verbatim passage')} from "
            f"{count_label(len(domains), 'distinct domain')} across {count_label(len(evidence.sources), 'source')}. "
            "Strong enough to argue from; every number still needs primary verification."
        )


# ─────────────────────────────────────────────────────────────────────────────
# LLM brief builder
# ─────────────────────────────────────────────────────────────────────────────

_MIN_PASSAGE_OVERLAP = 40


def _normalise_passage(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _match_stored_passage(passage: str, candidates: list[dict]) -> dict | None:
    """Find the stored verbatim passage an LLM-cited passage refers to.

    Matching used to require an exact string hit or an 80-character prefix.
    Models reflow whitespace, trim a trailing clause, or quote from the middle
    of a passage, so well-evidenced points were being dropped for cosmetic
    reasons — most briefs came out with two supporting points when the model
    had supplied five.

    Loosening the *match* does not loosen the verbatim guarantee: the caller
    writes ``matched["passage"]`` — the text as stored from the source — never
    the model's rendering of it. The only failure mode a looser match creates
    is attaching a point to the wrong passage, so require a substantial overlap
    rather than an incidental one.
    """
    needle = _normalise_passage(passage)
    if len(needle) < _MIN_PASSAGE_OVERLAP:
        return None
    for candidate in candidates:
        haystack = _normalise_passage(candidate.get("passage", ""))
        if not haystack:
            continue
        if needle in haystack or (
            len(haystack) >= _MIN_PASSAGE_OVERLAP and haystack in needle
        ):
            return candidate
    return None


class LLMBriefBuilder:
    def __init__(self, client: AIClient, config=None):
        self.client = client
        self.cfg = config or load_config()

    def build(self, evidence: ThemeEvidence, voice_guide: str = "") -> dict | None:
        theme = evidence.theme
        prompt = load_prompt("brief_generation").render(
            theme_name=theme["name"],
            theme_description=theme.get("description", ""),
            trend_status=theme.get("trend_status", "unknown"),
            source_count=len(evidence.sources),
            distinct_domains=len(evidence.distinct_domains),
            distinct_industries=len(evidence.distinct_industries),
            source_lines="\n".join(
                f"  [{s['id']}] {s['title']} — {s['domain']} — "
                f"{s['published_at'].date().isoformat() if s['published_at'] else 'no date'}"
                f"{' (vendor marketing)' if s['is_promotional'] else ''}"
                for s in evidence.sources[:20]
            ),
            evidence_lines="\n".join(
                f"  [src {p['source_id']}] {p['passage']}" for p in evidence.passages[:25]
            ) or "  (none survived the verbatim check)",
            quote_lines="\n".join(
                f"  [src {q['source_id']}] “{q['quote']}”"
                f"{' — ' + q['speaker'] if q.get('speaker') else ''}"
                for q in evidence.quotes[:12]
            ) or "  (none)",
            number_lines="\n".join(
                f"  [src {n['source_id']}] {n['value']} — {n['context']}"
                for n in evidence.numbers[:12]
            ) or "  (none)",
            voice_guide=voice_guide or "(no approved voice examples yet)",
        )
        response = self.client.complete_json(prompt, max_tokens=4000)
        if not response.ok:
            log.warning("LLM brief generation failed: %s", response.error)
            return None

        data = response.data
        valid_ids = {s["id"] for s in evidence.sources}
        passage_index = {p["passage"]: p for p in evidence.passages}

        # Enforce the evidence contract in code: drop any point whose source id
        # we do not hold, or whose passage is not one of our verbatim passages.
        points = []
        for item in data.get("supporting_points", []):
            if not isinstance(item, dict):
                continue
            ids = [i for i in (item.get("evidence_source_ids") or []) if i in valid_ids]
            passage = item.get("evidence_passage") or ""
            matched = passage_index.get(passage) or _match_stored_passage(
                passage, evidence.passages
            )
            if not ids or not matched:
                continue
            points.append({
                "point": str(item.get("point", "")).strip(),
                "evidence_source_ids": ids,
                "evidence_passage": matched["passage"],
                "evidence_url": matched["url"],
                "evidence_domain": matched["domain"],
            })

        if not points:
            log.warning("LLM brief had no evidence-backed supporting points; falling back.")
            return None

        return {
            "title": str(data.get("title") or theme["name"]).strip(),
            "core_insight": data.get("core_insight"),
            "why_now": data.get("why_now"),
            "why_podium": data.get("why_podium"),
            "why_eric": data.get("why_eric"),
            "target_audience": data.get("target_audience"),
            "founder_point_of_view": data.get("founder_point_of_view"),
            "hook": data.get("hook"),
            "supporting_points": points,
            "potential_objections": [
                o for o in data.get("potential_objections", []) if isinstance(o, dict)
            ],
            "recommended_format": data.get("recommended_format") or "linkedin_post",
            "suggested_call_to_action": data.get("suggested_call_to_action"),
            "verification_checklist": [
                {"item": c.get("item"), "why": c.get("why"), "done": False}
                for c in data.get("verification_checklist", []) if isinstance(c, dict)
            ],
            "risk_notes": [str(r) for r in data.get("risk_notes", [])],
            "confidence_note": data.get("confidence_note"),
            "generation_method": self.cfg.ai.model,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def reconcile_opportunity_statuses() -> int:
    """Return opportunities marked ``drafting`` that have no drafts to
    ``ready_for_brief``.

    ``drafting`` is set when a draft is written, so the two can only disagree
    if drafts were removed underneath it. That is not reachable through the UI
    — there is no delete control — but it is reachable through the scripts, and
    the kanban board then shows a card sitting in *Drafting* reading
    "0 draft(s)", which is the board contradicting itself. Cheap to check on
    every run, so check it rather than trusting that nobody touches the tables.
    """
    moved = 0
    with session_scope() as session:
        stranded = session.execute(
            select(ContentOpportunity).where(ContentOpportunity.status == "drafting")
        ).scalars().all()
        for opportunity in stranded:
            drafts = session.scalar(
                select(func.count(ContentDraft.id))
                .where(ContentDraft.content_opportunity_id == opportunity.id)
            ) or 0
            if drafts == 0:
                opportunity.status = "ready_for_brief"
                session.add(opportunity)
                moved += 1
    if moved:
        log.info("Reconciled %d opportunity status(es) from drafting to ready_for_brief.",
                 moved)
    return moved


def generate_opportunities(
    *,
    theme_names: list[str] | None = None,
    max_opportunities: int | None = None,
    force_regenerate: bool = False,
    force_heuristic: bool = False,
    progress=None,
) -> OpportunityReport:
    cfg = load_config()
    client = AIClient()
    use_llm = client.available and not force_heuristic
    report = OpportunityReport(backend=cfg.ai.model if use_llm else "heuristic-v1")
    limit = max_opportunities or cfg.pipeline.max_opportunities_per_run
    reconcile_opportunity_statuses()

    def emit(message: str) -> None:
        log.info(message)
        if progress:
            try:
                progress(message)
            except Exception:  # noqa: BLE001
                pass

    with session_scope() as session:
        query = select(Theme).order_by(Theme.average_relevance.desc(), Theme.source_count.desc())
        if theme_names:
            query = query.where(Theme.name.in_(theme_names))
        themes = [
            {"name": t.name, "status": t.trend_status, "count": t.source_count,
             "domains": t.distinct_domain_count}
            for t in session.execute(query).scalars().all()
        ]

    if not themes:
        report.skipped.append("No themes have been computed yet — run trend analysis first.")
        return report

    voice_guide = _voice_guide_text()

    for theme in themes:
        # The cap limits how many briefs we *write*, not how many themes we
        # examine. Breaking out early would leave a previously-generated brief
        # unreviewed and still ranking on numbers that no longer hold.
        at_capacity = len(report.opportunity_ids) >= limit

        if not theme_names:
            if theme["status"] not in PROMOTABLE_STATUSES:
                reason = (
                    f"{theme['name']}: status '{theme['status']}' — not promoted "
                    f"({count_label(theme['count'], 'source')}, {count_label(theme['domains'], 'domain')})."
                )
                if _retire_stale_opportunity(theme["name"], reason):
                    reason += " Existing brief archived as stale."
                report.skipped.append(reason)
                continue

        evidence = collect_theme_evidence(theme["name"])
        if not evidence.sources:
            report.skipped.append(f"{theme['name']}: no supporting sources found.")
            continue
        if not evidence.passages:
            report.skipped.append(
                f"{theme['name']}: no verbatim evidence passage survived verification — "
                "a brief cannot be evidenced."
            )
            continue

        brief = None
        if use_llm:
            try:
                brief = LLMBriefBuilder(client, cfg).build(evidence, voice_guide)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{theme['name']}: LLM brief failed — {exc}")
        if brief is None:
            brief = HeuristicBriefBuilder().build(evidence)

        score, risk, confidence = _score_brief(evidence, brief)
        if score.total < cfg.pipeline.min_opportunity_score and not theme_names:
            reason = (
                f"{theme['name']}: opportunity score {score.total:.0f} is below the "
                f"{cfg.pipeline.min_opportunity_score} threshold."
            )
            # Do not silently leave a previously-generated brief in place. If the
            # evidence base has weakened, the stale brief is worse than none — it
            # would keep ranking on numbers that no longer hold.
            retired = _retire_stale_opportunity(theme["name"], reason)
            if retired:
                reason += " Existing brief archived as stale."
            report.skipped.append(reason)
            continue

        if at_capacity:
            report.skipped.append(
                f"{theme['name']}: clears the threshold, but the {limit}-brief cap for this "
                "run is already reached — it will be generated on the next run."
            )
            continue

        opportunity_id, created = _persist_opportunity(
            theme_name=theme["name"], brief=brief, evidence=evidence,
            score=score, risk=risk, confidence=confidence,
            force_regenerate=force_regenerate,
        )
        if opportunity_id is None:
            report.skipped.append(f"{theme['name']}: existing opportunity left untouched.")
            continue

        report.opportunity_ids.append(opportunity_id)
        if created:
            report.created += 1
        else:
            report.updated += 1
        emit(f"  {'created' if created else 'updated'}: {brief['title'][:80]} "
             f"(score {score.total:.0f})")

    emit(f"Opportunities: {report.created} created, {report.updated} updated, "
         f"{len(report.skipped)} skipped.")
    return report


def _retire_stale_opportunity(theme_name: str, reason: str) -> bool:
    """Archive a brief whose theme no longer clears the promotion threshold.

    Returns True when something was archived. Human-approved briefs are left
    alone — a person signed off on those, and the system does not overrule a
    human decision. They are annotated instead.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_scope() as session:
        theme = session.execute(select(Theme).where(Theme.name == theme_name)).scalar_one_or_none()
        if theme is None:
            return False
        existing = session.execute(
            select(ContentOpportunity)
            .where(ContentOpportunity.theme_id == theme.id)
            .where(ContentOpportunity.status != "archived")
        ).scalars().all()
        if not existing:
            return False

        note = f"[auto] Evidence base weakened on {now.date().isoformat()}: {reason}"
        archived = False
        for opportunity in existing:
            opportunity.reviewer_notes = "\n".join(
                filter(None, [opportunity.reviewer_notes, note])
            )
            if opportunity.status == "approved":
                # Flag, do not overrule a human sign-off.
                session.add(opportunity)
                continue
            opportunity.status = "archived"
            opportunity.reviewed_at = now
            session.add(opportunity)
            archived = True
        return archived


def _score_brief(evidence: ThemeEvidence, brief: dict):
    sources = evidence.sources
    def avg(key: str) -> float:
        values = [s.get(key) or 0 for s in sources]
        return sum(values) / len(values) if values else 0.0

    score = compute_opportunity_score(
        {
            "podium_relevance": avg("podium_relevance"),
            "founder_relevance": avg("founder_relevance"),
            "evidence_strength": avg("evidence_strength"),
            "freshness": avg("freshness"),
            "novelty": avg("novelty"),
            "business_impact": avg("business_impact"),
        },
        notes=[
            f"Averaged across {count_label(len(sources), 'supporting source')}.",
            f"{count_label(len(evidence.distinct_domains), 'distinct domain')}; "
            f"{count_label(len(evidence.passages), 'verbatim passage')}.",
        ],
    )

    promotional = [s for s in sources if s["is_promotional"]]
    familiar = [s for s in sources if s["is_familiar"]]
    detected: dict[str, str] = {}
    if len(evidence.distinct_domains) < 2:
        detected["weak_sourcing"] = f"Only {count_label(len(evidence.distinct_domains), 'distinct domain')}."
    elif len(promotional) > len(sources) / 2:
        detected["weak_sourcing"] = (
            f"{len(promotional)} of {len(sources)} sources are vendor marketing."
        )
    if evidence.numbers:
        detected["unverified_numbers"] = f"{count_label(len(evidence.numbers), 'figure')} require verification."
    if promotional:
        detected["promotional_source"] = f"{count_label(len(promotional), 'vendor-marketing source')} in the cluster."
    if len(familiar) >= max(2, len(sources) // 2):
        detected["overused_narrative"] = f"{count_label(len(familiar), 'source')} restate a familiar narrative."
    if not evidence.has_dated_sources:
        detected["missing_publication_date"] = "No supporting source carries a publication date."
    competitor_mentions = [
        s for s in sources if s["domain"] not in {"podium.com"} and s.get("is_promotional")
    ]
    if competitor_mentions:
        detected["competitor_claims"] = (
            f"{count_label(len(competitor_mentions), 'source')} are third-party vendor content that may "
            "make competitive claims."
        )
    if len(brief.get("supporting_points", [])) < 3:
        detected["no_original_insight"] = (
            f"Only {count_label(len(brief.get('supporting_points', [])), 'evidenced supporting point')}."
        )

    risk = compute_risk_score(detected)
    confidence, reasons = compute_confidence(
        distinct_domains=len(evidence.distinct_domains),
        evidence_passage_count=len(evidence.passages),
        avg_evidence_strength=avg("evidence_strength"),
        source_count=len(sources),
        has_dated_sources=evidence.has_dated_sources,
    )
    score.notes.extend(reasons)
    return score, risk, confidence


def _persist_opportunity(*, theme_name, brief, evidence, score, risk, confidence,
                         force_regenerate) -> tuple[int | None, bool]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_scope() as session:
        theme = session.execute(select(Theme).where(Theme.name == theme_name)).scalar_one_or_none()
        existing = None
        if theme is not None:
            existing = session.execute(
                select(ContentOpportunity)
                .where(ContentOpportunity.theme_id == theme.id)
                .order_by(ContentOpportunity.created_at.desc())
            ).scalars().first()

        if existing is not None and not force_regenerate:
            # Refresh scores only; never overwrite a human-reviewed brief.
            if existing.status in {"approved", "review", "archived"}:
                return None, False
            target, created = existing, False
        elif existing is not None and force_regenerate:
            target, created = existing, False
        else:
            target = ContentOpportunity(theme_id=theme.id if theme else None)
            session.add(target)
            created = True

        risk_notes = list(brief.get("risk_notes") or [])
        risk_notes.extend(f"{f['label']}: {f['reason']}" for f in risk.factors)

        target.title = brief["title"]
        target.core_insight = brief.get("core_insight")
        target.why_now = brief.get("why_now")
        target.why_podium = brief.get("why_podium")
        target.why_eric = brief.get("why_eric")
        target.target_audience = brief.get("target_audience")
        target.founder_point_of_view = brief.get("founder_point_of_view")
        target.hook = brief.get("hook")
        target.supporting_points = brief.get("supporting_points", [])
        target.supporting_source_ids = [s["id"] for s in evidence.sources]
        target.evidence_passages = evidence.passages[:30]
        target.potential_objections = brief.get("potential_objections", [])
        target.recommended_format = brief.get("recommended_format")
        target.suggested_call_to_action = brief.get("suggested_call_to_action")
        target.confidence_score = confidence
        target.opportunity_score = score.total
        target.score_breakdown = score.to_dict()
        target.risk_score = risk.total
        target.risk_notes = risk_notes
        target.verification_checklist = brief.get("verification_checklist", [])
        target.generation_method = brief.get("generation_method", "heuristic-v1")
        if created:
            target.status = "ready_for_brief"
            target.created_at = now

        session.flush()
        return target.id, created


def _voice_guide_text() -> str:
    """Compact voice guide for prompt injection. Empty when nothing is approved."""
    from .voice import build_voice_guide

    guide = build_voice_guide()
    if not guide.get("approved_example_count"):
        return ""
    lines = [
        f"Derived from {count_label(guide['approved_example_count'], 'approved public example')}.",
        f"Tone: {guide.get('tone', 'not established')}",
        f"Median sentence length: {guide.get('median_sentence_words', 'n/a')} words",
        f"Median paragraph length: {guide.get('median_paragraph_sentences', 'n/a')} sentences",
    ]
    if guide.get("recurring_themes"):
        lines.append("Recurring themes: " + ", ".join(guide["recurring_themes"][:6]))
    if guide.get("example_hooks"):
        lines.append("Observed hooks: " + " | ".join(guide["example_hooks"][:3]))
    if guide.get("coverage_warning"):
        lines.append("WARNING: " + guide["coverage_warning"])
    return "\n".join(lines)
