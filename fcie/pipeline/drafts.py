"""Draft generation and the evidence audit that gates it.

Every draft stays linked to its opportunity and, through it, to the source
evidence. Before a draft is stored it is audited sentence by sentence against
the verbatim evidence available; unsupported sentences are recorded rather than
quietly kept, and the resulting ``evidence_score`` is computed, not estimated.

Nothing is ever published. Drafts land in ``pending_review``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from ..ai.client import AIClient
from ..ai.prompts import load_prompt
from ..db import session_scope
from ..models import ContentDraft, ContentOpportunity, Source
from ..utils.text import sentences, truncate, word_count
from .opportunities import _voice_guide_text
from .voice import build_voice_guide

log = logging.getLogger(__name__)

BANNED_PHRASES = (
    "game-changer", "game changer", "revolutionize", "revolutionise", "unlock",
    "in today's fast-paced", "the future of", "10x", "let that sink in",
    "here's the kicker", "paradigm shift", "supercharge", "seismic shift",
)

OPINION_MARKERS = (
    "i think", "i believe", "my view", "in my experience", "the way i see it",
    "should", "must", "needs to", "i'd argue", "we should", "the real question",
    "here's the thing", "worth asking", "my read",
)

FUTURE_MARKERS = ("will ", "going to ", "expect ", "predict", "by 2026", "by 2027", "soon")

# Words that carry no evidential weight. Without removing them, a sentence of
# mostly connective tissue can "match" any passage, and a short factual sentence
# is dominated by them.
_AUDIT_STOPWORDS = {
    "that", "this", "with", "from", "they", "them", "their", "there", "these",
    "those", "have", "has", "had", "been", "being", "which", "when", "what",
    "your", "you", "our", "and", "but", "for", "not", "are", "were", "was",
    "into", "than", "then", "also", "just", "more", "most", "much", "only",
    "over", "such", "some", "same", "still", "even", "here", "will", "would",
    "could", "should", "about", "after", "before", "because", "while", "where",
    "every", "each", "both", "many", "make", "makes", "made", "does", "doing",
}

FORMAT_LABELS = {
    "linkedin_post": "LinkedIn post",
    "short_form_video_outline": "Short-form video outline",
    "long_form_essay_outline": "Long-form essay outline",
    "executive_talking_point": "Executive talking point",
    "podcast_discussion_point": "Podcast discussion point",
    "customer_story_angle": "Customer-story angle",
    "engagement_comment": "Comment / engagement suggestion",
    "internal_briefing_note": "Internal briefing note",
}


@dataclass
class DraftResult:
    draft_text: str
    content_type: str
    claims_used: list[dict] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    verification_required: list[str] = field(default_factory=list)
    voice_notes: list[str] = field(default_factory=list)
    cited_source_ids: list[int] = field(default_factory=list)
    evidence_score: float = 0.0
    voice_score: float = 0.0
    generation_method: str = "heuristic-v1"
    alternative_hooks: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Evidence audit
# ─────────────────────────────────────────────────────────────────────────────

_META_LINE = re.compile(
    r"^\s*(\[|https?://|#\d|\*\*(sources?|evidence|verification|pre-production|rules)|"
    r"-\s*(source|evidence|on-screen)\b|\|)",
    re.IGNORECASE,
)


def _auditable_units(draft_text: str) -> list[str]:
    """Split a draft into checkable claims.

    Drafts are not flowing prose — they contain bullets, outline beats and
    on-screen lines. Running a sentence splitter over the whole blob merges
    separate bullets into one giant pseudo-sentence, whose token set spans
    several unrelated passages and therefore matches none of them. Split on
    lines first, then into sentences within each line.

    Metadata lines (source URLs, the review disclaimer, section labels) are not
    factual claims and are excluded rather than scored as unsupported.
    """
    units: list[str] = []
    for raw_line in (draft_text or "").split("\n"):
        line = raw_line.strip()
        if not line or _META_LINE.match(line):
            continue
        # Strip list/outline markers so the claim itself is what gets compared.
        line = re.sub(r"^\s*(?:[-—•*]|\d+\.)\s*", "", line)
        line = line.strip().strip("*").strip()
        if not line:
            continue
        parts = sentences(line) or [line]
        units.extend(parts)
    return units


def audit_draft(draft_text: str, evidence_passages: list[dict]) -> dict:
    """Classify each claim in a draft against the available evidence.

    ``evidence_score`` = supported ÷ (supported + partially + unsupported),
    computed over factual claims only. Opinion and future-tense statements are
    excluded from the denominator but reported.
    """
    corpus = " ".join(p.get("passage", "") for p in evidence_passages).lower()
    corpus_tokens = {w for w in re.findall(r"[a-z']{4,}", corpus)}
    rows: list[dict] = []
    supported = partial = unsupported = 0

    for sentence in _auditable_units(draft_text):
        low = sentence.lower().strip()
        if len(low.split()) < 4:
            continue
        # A quoted, attributed passage is evidence being *shown*, not a claim
        # being made — the verbatim gate already proved it. Score it directly.
        stripped = low.strip('"“”\' ')
        if stripped[:60] and stripped[:60] in corpus:
            supported += 1
            match = next(
                (p for p in evidence_passages
                 if stripped[:60] in p.get("passage", "").lower()), None
            )
            rows.append({
                "sentence": sentence, "status": "supported",
                "supporting_source_ids": [match["source_id"]] if match else [],
                "supporting_passage": match["passage"] if match else None,
                "overlap": 1.0, "problem": None,
            })
            continue

        if any(marker in low for marker in OPINION_MARKERS):
            rows.append({"sentence": sentence, "status": "opinion",
                         "supporting_source_ids": [], "problem": None})
            continue
        if any(low.startswith(m) or f" {m}" in low for m in FUTURE_MARKERS) and "?" not in low:
            rows.append({"sentence": sentence, "status": "unverifiable",
                         "supporting_source_ids": [],
                         "problem": "Statement about the future — cannot be evidenced."})
            continue

        best_overlap, best_passage = 0.0, None
        tokens = {w for w in re.findall(r"[a-z']{4,}", low)} - _AUDIT_STOPWORDS
        if not tokens:
            continue
        for passage in evidence_passages:
            passage_tokens = {w for w in re.findall(r"[a-z']{4,}", passage.get("passage", "").lower())}
            if not passage_tokens:
                continue
            overlap = len(tokens & passage_tokens) / len(tokens)
            if overlap > best_overlap:
                best_overlap, best_passage = overlap, passage

        if best_overlap >= 0.6 and best_passage:
            supported += 1
            rows.append({
                "sentence": sentence, "status": "supported",
                "supporting_source_ids": [best_passage["source_id"]],
                "supporting_passage": best_passage["passage"],
                "overlap": round(best_overlap, 2), "problem": None,
            })
        elif best_overlap >= 0.35 and best_passage:
            partial += 1
            rows.append({
                "sentence": sentence, "status": "partially_supported",
                "supporting_source_ids": [best_passage["source_id"]],
                "supporting_passage": best_passage["passage"],
                "overlap": round(best_overlap, 2),
                "problem": "Consistent with the evidence but not directly stated by it.",
            })
        elif tokens and len(tokens & corpus_tokens) / len(tokens) >= 0.75:
            # Synthesis across passages. Matching sentence-to-passage alone
            # rewards copying and punishes writing: a sentence that accurately
            # combines two passages scores ~0.5 against each and lands in
            # "unsupported", which is wrong — its substance *does* come from the
            # evidence. Requiring 75% of its content words to exist somewhere in
            # the corpus catches that without letting new claims through, since
            # a genuinely novel assertion introduces vocabulary the corpus lacks.
            partial += 1
            rows.append({
                "sentence": sentence, "status": "partially_supported",
                "supporting_source_ids": sorted({
                    p["source_id"] for p in evidence_passages
                    if tokens & {w for w in re.findall(r"[a-z']{4,}", p.get("passage", "").lower())}
                })[:3],
                "supporting_passage": None,
                "overlap": round(len(tokens & corpus_tokens) / len(tokens), 2),
                "problem": "Synthesised from several passages rather than stated by one.",
            })
        else:
            unsupported += 1
            rows.append({
                "sentence": sentence, "status": "unsupported",
                "supporting_source_ids": [], "overlap": round(best_overlap, 2),
                "problem": "No evidence passage states this.",
            })

    factual_total = supported + partial + unsupported
    evidence_score = round((supported + 0.5 * partial) / factual_total * 100, 1) if factual_total else 0.0

    # Fabrication checks that do not depend on the model's self-report.
    draft_numbers = set(re.findall(r"\b\d[\d,.]*%?\b", draft_text))
    evidence_numbers = set(re.findall(r"\b\d[\d,.]*%?\b", corpus))
    invented_numbers = sorted(
        n for n in draft_numbers - evidence_numbers
        if not re.fullmatch(r"(19|20)\d{2}", n.replace(",", "")) and len(n.strip("%")) > 1
    )
    quoted = re.findall(r"[“\"]([^”\"]{20,})[”\"]", draft_text)
    invented_quotes = [q for q in quoted if q.lower()[:60] not in corpus]

    return {
        "sentence_audit": rows,
        "evidence_score": evidence_score,
        "supported": supported,
        "partially_supported": partial,
        "unsupported": unsupported,
        "opinion": sum(1 for r in rows if r["status"] == "opinion"),
        "unverifiable": sum(1 for r in rows if r["status"] == "unverifiable"),
        "invented_numbers": invented_numbers,
        "invented_quotes": invented_quotes,
        "banned_phrases": [p for p in BANNED_PHRASES if p in draft_text.lower()],
        "unsupported_sentences": [r["sentence"] for r in rows if r["status"] == "unsupported"],
    }


def score_voice_alignment(draft_text: str, guide: dict) -> tuple[float, list[str]]:
    """0-100 alignment against the *approved examples*, with the reasons.

    Returns 0 with an explanation when no approved examples exist — the system
    never claims voice alignment it cannot evidence.
    """
    if not guide or not guide.get("approved_example_count"):
        return 0.0, [
            "No approved voice examples in the library, so no voice alignment can be measured. "
            "Add public examples on the Voice Library page."
        ]

    notes: list[str] = []
    score = 100.0

    sents = sentences(draft_text)
    if sents:
        median_words = sorted(len(s.split()) for s in sents)[len(sents) // 2]
        target = guide.get("median_sentence_words") or 16
        delta = abs(median_words - target)
        if delta > 8:
            score -= 20
            notes.append(f"Sentence length {median_words} words vs approved-example median {target} — off pattern.")
        elif delta > 4:
            score -= 8
            notes.append(f"Sentence length {median_words} words vs median {target} — slightly off.")
        else:
            notes.append(f"Sentence length {median_words} words matches the approved-example median ({target}).")

    paragraphs = [p for p in re.split(r"\n\s*\n", draft_text) if p.strip()]
    if paragraphs:
        median_para = sorted(max(len(sentences(p)), 1) for p in paragraphs)[len(paragraphs) // 2]
        target_para = guide.get("median_paragraph_sentences") or 2
        if abs(median_para - target_para) > 2:
            score -= 12
            notes.append(f"Paragraph length {median_para} sentences vs approved median {target_para}.")

    found_hype = [p for p in BANNED_PHRASES if p in draft_text.lower()]
    if found_hype:
        if not guide.get("hype_terms_found"):
            score -= 25
            notes.append("Contains hype vocabulary absent from every approved example: " + ", ".join(found_hype))
        else:
            score -= 10
            notes.append("Contains hype vocabulary: " + ", ".join(found_hype))
    else:
        notes.append("No hype vocabulary — consistent with the approved examples.")

    has_number = bool(re.search(r"\b\d", draft_text))
    if "%" in (guide.get("use_of_numbers") or ""):
        try:
            share = int(re.search(r"(\d+)%", guide["use_of_numbers"]).group(1))
        except (AttributeError, ValueError):
            share = 0
        if share >= 50 and not has_number:
            score -= 10
            notes.append(f"{share}% of approved examples use a figure; this draft uses none.")

    themes = guide.get("recurring_themes") or []
    if themes:
        hit = [t for t in themes if t.lower().split()[0] in draft_text.lower()]
        if hit:
            notes.append("Touches recurring approved-example theme(s): " + ", ".join(hit[:3]))
        else:
            score -= 5
            notes.append("Does not touch any recurring theme from the approved examples.")

    if guide.get("coverage_warning"):
        score *= 0.8
        notes.append("Score reduced 20%: " + guide["coverage_warning"])

    return round(max(0.0, min(score, 100.0)), 1), notes


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic draft composition
# ─────────────────────────────────────────────────────────────────────────────

class HeuristicDraftWriter:
    """Compose drafts from the brief's own evidenced material.

    It assembles verbatim-backed points and clearly-marked argument. It never
    writes a customer story, never invents a figure, and never speaks for a
    named person.
    """

    method = "heuristic-v1"

    def write(self, opportunity: dict, content_type: str, evidence: list[dict]) -> DraftResult:
        writer = {
            "linkedin_post": self._linkedin,
            "short_form_video_outline": self._short_video,
            "long_form_essay_outline": self._essay,
            "executive_talking_point": self._talking_point,
            "podcast_discussion_point": self._podcast,
            "customer_story_angle": self._customer_story,
            "engagement_comment": self._comment,
            "internal_briefing_note": self._briefing,
        }.get(content_type, self._talking_point)

        text = writer(opportunity, evidence)
        source_ids = sorted({
            sid for point in opportunity.get("supporting_points", [])
            for sid in (point.get("evidence_source_ids") or [])
        })
        return DraftResult(
            draft_text=text,
            content_type=content_type,
            cited_source_ids=source_ids,
            generation_method=self.method,
        )

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _points(opportunity: dict, limit: int = 5) -> list[dict]:
        return (opportunity.get("supporting_points") or [])[:limit]

    @staticmethod
    def _clean_point(point: dict) -> str:
        text = (point.get("point") or point.get("evidence_passage") or "").strip()
        return text.rstrip(".") + "."

    @staticmethod
    def _is_verbatim_point(point: dict) -> bool:
        """True when the point text *is* the source passage rather than a summary.

        The heuristic brief builder has no summarisation ability, so its
        `point` is the evidence passage itself. Rendering that as a plain bullet
        would present a publication's sentence as the author's own words — so
        those points are quoted and attributed instead.
        """
        point_text = (point.get("point") or "").strip().rstrip(".")
        passage = (point.get("evidence_passage") or "").strip().rstrip(".")
        if not point_text or not passage:
            return False
        return point_text[:60].lower() in passage.lower()

    @classmethod
    def _render_point(cls, point: dict) -> str:
        """One bullet: quoted + attributed when verbatim, plain when a summary."""
        ids = ", ".join(f"#{i}" for i in point.get("evidence_source_ids", []))
        domain = point.get("evidence_domain") or "source"
        body = truncate(cls._clean_point(point), 190)
        if cls._is_verbatim_point(point):
            return f'— "{body.rstrip(".")}" — {domain} [{ids}]'
        return f"— {body} [{ids}]"

    # ── formats ─────────────────────────────────────────────────────────

    def _linkedin(self, opportunity: dict, evidence: list[dict]) -> str:
        points = self._points(opportunity, 3)
        lines = [opportunity.get("hook") or opportunity.get("title", "")]
        lines.append("")

        insight = opportunity.get("core_insight") or ""
        insight = re.sub(r"\[Inference[^\]]*\]\s*", "", insight)
        lines.append(truncate(insight.split("The most concrete problem")[0].strip(), 320))
        lines.append("")

        lines.append("What the public sources actually say:")
        for point in points:
            lines.append(self._render_point(point))
        lines.append("")

        pov = re.sub(r"\[Inference[^\]]*\]\s*", "", opportunity.get("founder_point_of_view") or "")
        first_two = " ".join(sentences(pov)[:2])
        if first_two:
            lines.append(f"My read: {truncate(first_two, 300)}")
            lines.append("")

        cta = opportunity.get("suggested_call_to_action") or ""
        if cta:
            lines.append(truncate(re.sub(r"^Ask the reader to ", "", cta).capitalize(), 200))

        lines.append("")
        lines.append(
            "[Draft for human review — evidence-linked, not published. Sources listed below.]"
        )
        seen: set[tuple[int, str]] = set()
        for point in points:
            url = point.get("evidence_url")
            if not url:
                continue
            for sid in point.get("evidence_source_ids", []):
                if (sid, url) in seen:
                    continue
                seen.add((sid, url))
                lines.append(f"#{sid} {url}")
        return "\n".join(lines).strip()

    def _short_video(self, opportunity: dict, evidence: list[dict]) -> str:
        points = self._points(opportunity, 3)
        out = [
            f"# Short-form video outline — {opportunity.get('title', '')}",
            "",
            f"**Hook (0-3s):** {opportunity.get('hook', '')}",
            "",
            "**Beats:**",
        ]
        for index, point in enumerate(points, start=1):
            ids = ", ".join(f"#{i}" for i in point.get("evidence_source_ids", []))
            beat = truncate(self._clean_point(point), 160)
            if self._is_verbatim_point(point):
                beat = f'Quote {point.get("evidence_domain", "the source")}: "{beat.rstrip(".")}"'
            out.append(f"{index}. {beat}")
            out.append(f"   - On-screen: “{truncate(point.get('evidence_passage', ''), 90)}”")
            out.append(f"   - Source: {ids} — {point.get('evidence_url', '')}")
        if not points:
            out.append("[NEEDS EVIDENCE] No evidenced points available for this theme.")
        out += [
            "",
            f"**Close:** {truncate(opportunity.get('suggested_call_to_action', ''), 180)}",
            "",
            f"**Spoken length:** ~{sum(word_count(self._clean_point(p)) for p in points) + 40} words "
            "(≈45-60 seconds).",
            "",
            "**Pre-production check:** every on-screen figure must be verified against a primary "
            "source before filming.",
        ]
        return "\n".join(out)

    def _essay(self, opportunity: dict, evidence: list[dict]) -> str:
        points = self._points(opportunity, 5)
        out = [
            f"# {opportunity.get('title', '')}",
            "",
            f"**Thesis:** {truncate(re.sub(r'\\[Inference[^\\]]*\\]\\s*', '', opportunity.get('founder_point_of_view', '')), 400)}",
            "",
            "## Sections",
        ]
        out.append(f"1. **Why now** — {truncate(opportunity.get('why_now', ''), 300)}")
        for index, point in enumerate(points, start=2):
            ids = ", ".join(f"#{i}" for i in point.get("evidence_source_ids", []))
            heading = truncate(self._clean_point(point), 120)
            if self._is_verbatim_point(point):
                heading = (f'Section built on {point.get("evidence_domain", "this source")}: '
                           f'"{heading.rstrip(".")}"')
            out.append(f"{index}. **{heading}**")
            out.append(f"   - Evidence [{ids}]: “{truncate(point.get('evidence_passage', ''), 220)}”")
            out.append(f"   - {point.get('evidence_url', '')}")
        out.append(f"{len(points) + 2}. **Objections** —")
        for objection in (opportunity.get("potential_objections") or [])[:3]:
            out.append(f"   - *{objection.get('objection', '')}* → {objection.get('response', '')}")
        out.append(f"{len(points) + 3}. **Close** — {truncate(opportunity.get('suggested_call_to_action', ''), 220)}")
        out += ["", "## Sections still needing evidence", ""]
        if len(points) < 4:
            out.append("[NEEDS EVIDENCE] Fewer than four evidenced points — this outline is not "
                       "yet publishable as a long-form piece.")
        else:
            out.append("All sections above carry at least one verbatim source passage.")
        return "\n".join(out)

    def _talking_point(self, opportunity: dict, evidence: list[dict]) -> str:
        points = self._points(opportunity, 3)
        objection = (opportunity.get("potential_objections") or [{}])[0]
        numbers = [p for p in evidence if re.search(r"\d", p.get("passage", ""))]
        out = [
            f"# Executive talking point — {opportunity.get('title', '')}",
            "",
            "**Position (3 sentences):**",
            truncate(re.sub(r"\[Inference[^\]]*\]\s*", "", opportunity.get("core_insight", "")), 480),
            "",
            "**Supporting facts:**",
        ]
        for point in points:
            ids = ", ".join(f"#{i}" for i in point.get("evidence_source_ids", []))
            out.append(f"- [{ids}] “{truncate(point.get('evidence_passage', ''), 200)}”")
        out += [
            "",
            f"**Strongest objection:** {objection.get('objection', 'None recorded.')}",
            f"**Response:** {objection.get('response', '')}",
            "",
            "**Number worth citing:** " + (
                f"“{truncate(numbers[0]['passage'], 160)}” (source #{numbers[0]['source_id']}) — "
                "verify before use."
                if numbers else "none verified."
            ),
        ]
        return "\n".join(out)

    def _podcast(self, opportunity: dict, evidence: list[dict]) -> str:
        points = self._points(opportunity, 2)
        out = [
            f"# Podcast discussion point — {opportunity.get('title', '')}",
            "",
            f"**Question a host would ask:** {opportunity.get('title', '').rstrip('.')}?",
            "",
            "**60-second answer:**",
            truncate(re.sub(r"\[Inference[^\]]*\]\s*", "", opportunity.get("founder_point_of_view", "")), 700),
            "",
            "**Concrete example drawn only from the evidence:**",
        ]
        for point in points:
            out.append(f"- “{truncate(point.get('evidence_passage', ''), 220)}” "
                       f"({point.get('evidence_domain', '')}, source "
                       f"#{(point.get('evidence_source_ids') or ['?'])[0]})")
        out += ["", "**Natural follow-up question:** What would have to be true for this to be "
                    "wrong — and what would you measure to find out?"]
        return "\n".join(out)

    def _customer_story(self, opportunity: dict, evidence: list[dict]) -> str:
        return "\n".join([
            f"# Customer-story angle — {opportunity.get('title', '')}",
            "",
            "**This is a structure, not a story. No customer is described here, and none may be "
            "invented.** A real, consented customer and real, verified numbers are required "
            "before anything in this shape is written.",
            "",
            "**Structure to fill with a real customer:**",
            "1. The situation before — what demand was arriving and what happened to it.",
            "2. The specific failure point — where, when, and how often it occurred.",
            "3. What changed operationally — the process, not the marketing claim.",
            "4. The measured outcome — with the measurement method stated.",
            "5. What the operator would tell a peer.",
            "",
            "**Questions to ask the real customer:**",
            "- What did you measure before, and how did you measure it?",
            "- What period do these numbers cover?",
            "- What else changed in that period that could explain the result?",
            "- What did not improve?",
            "- May we publish your name, your numbers, and this quote?",
            "",
            "**Consent and verification requirements:**",
            "- Written permission to publish the name, figures, and quotes.",
            "- A source for every figure that is independent of the sales conversation.",
            "- Legal review if the story implies a performance guarantee.",
            "",
            f"**Theme context:** {truncate(opportunity.get('core_insight', ''), 300)}",
        ])

    def _comment(self, opportunity: dict, evidence: list[dict]) -> str:
        point = (self._points(opportunity, 1) or [{}])[0]
        return "\n".join([
            f"# Engagement comment draft — {opportunity.get('title', '')}",
            "",
            "**Draft comment (40-80 words, to be posted by a human, never automated):**",
            "",
            f"{truncate(re.sub(r'\\[Inference[^\\]]*\\]\\s*', '', opportunity.get('core_insight', '')), 240)} "
            f"The detail I keep coming back to: {truncate(point.get('evidence_passage', 'no evidenced point available'), 160)} "
            "Curious whether that matches what you're seeing.",
            "",
            "**Rules:** no pitch, no link drop, no praise-only reply. If the comment does not add "
            "a distinction, a counter-example, or a real question, do not post it.",
            "",
            f"**Evidence behind it:** source #{(point.get('evidence_source_ids') or ['?'])[0]} — "
            f"{point.get('evidence_url', '')}",
        ])

    def _briefing(self, opportunity: dict, evidence: list[dict]) -> str:
        points = self._points(opportunity, 5)
        out = [
            f"# Internal briefing note — {opportunity.get('title', '')}",
            "",
            "## What we now know",
        ]
        for point in points:
            ids = ", ".join(f"#{i}" for i in point.get("evidence_source_ids", []))
            out.append(f"- [{ids}] {truncate(point.get('evidence_passage', ''), 220)}")
        out += [
            "",
            "## What changed",
            truncate(opportunity.get("why_now", ""), 500),
            "",
            "## What we do not know",
        ]
        for item in (opportunity.get("verification_checklist") or [])[:6]:
            out.append(f"- {item.get('item', '')} — {item.get('why', '')}")
        out += [
            "",
            "## Recommended next action",
            truncate(opportunity.get("suggested_call_to_action", ""), 300),
            "",
            f"## Confidence",
            opportunity.get("confidence_note", "") or "Not stated.",
        ]
        return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def generate_draft(opportunity_id: int, content_type: str = "linkedin_post",
                   *, force_heuristic: bool = False) -> dict:
    """Generate, audit, and store one draft. Returns a UI-ready summary."""
    with session_scope() as session:
        opportunity = session.get(ContentOpportunity, opportunity_id)
        if opportunity is None:
            return {"ok": False, "error": f"Opportunity {opportunity_id} not found."}
        payload = {
            "id": opportunity.id,
            "title": opportunity.title,
            "core_insight": opportunity.core_insight,
            "why_now": opportunity.why_now,
            "why_podium": opportunity.why_podium,
            "why_eric": opportunity.why_eric,
            "founder_point_of_view": opportunity.founder_point_of_view,
            "hook": opportunity.hook,
            "supporting_points": list(opportunity.supporting_points or []),
            "potential_objections": list(opportunity.potential_objections or []),
            "suggested_call_to_action": opportunity.suggested_call_to_action,
            "verification_checklist": list(opportunity.verification_checklist or []),
            "confidence_note": (opportunity.score_breakdown or {}).get("notes", [""])[0],
            "risk_notes": list(opportunity.risk_notes or []),
        }
        evidence = list(opportunity.evidence_passages or [])
        source_ids = list(opportunity.supporting_source_ids or [])

    client = AIClient()
    result: DraftResult | None = None

    if client.available and not force_heuristic:
        result = _llm_draft(client, payload, content_type, evidence)
    if result is None:
        result = HeuristicDraftWriter().write(payload, content_type, evidence)

    audit = audit_draft(result.draft_text, evidence)
    guide = build_voice_guide()
    voice_score, voice_notes = score_voice_alignment(result.draft_text, guide)

    result.evidence_score = audit["evidence_score"]
    result.voice_score = voice_score
    result.voice_notes = voice_notes + result.voice_notes
    result.unsupported_claims = sorted(set(result.unsupported_claims + audit["unsupported_sentences"]))

    verification = list(result.verification_required)
    if audit["invented_numbers"]:
        verification.append(
            "Figures appear in the draft that are not in the evidence corpus: "
            + ", ".join(audit["invented_numbers"][:6])
            + " — remove them or attach a primary source."
        )
    if audit["invented_quotes"]:
        verification.append(
            f"{len(audit['invented_quotes'])} quotation(s) in the draft do not match any stored "
            "verbatim passage. Remove or re-source before review."
        )
    if audit["banned_phrases"]:
        verification.append("Banned/hype phrases present: " + ", ".join(audit["banned_phrases"]))
    for item in payload["verification_checklist"][:4]:
        if item.get("item"):
            verification.append(item["item"])
    verification.append(
        "Confirm nothing in the draft states or implies that Eric Rea wrote, reviewed, or "
        "approved it."
    )
    result.verification_required = sorted(set(verification))
    if not result.cited_source_ids:
        result.cited_source_ids = source_ids

    with session_scope() as session:
        draft = ContentDraft(
            content_opportunity_id=opportunity_id,
            content_type=content_type,
            draft_text=result.draft_text,
            voice_score=result.voice_score,
            voice_notes=result.voice_notes,
            evidence_score=result.evidence_score,
            unsupported_claims=result.unsupported_claims,
            verification_required=result.verification_required,
            cited_source_ids=result.cited_source_ids,
            generation_method=result.generation_method,
            approval_status="pending_review",
        )
        session.add(draft)

        opportunity = session.get(ContentOpportunity, opportunity_id)
        if opportunity is not None and opportunity.status in {"new", "ready_for_brief", "research_needed"}:
            opportunity.status = "drafting"
            session.add(opportunity)

        session.flush()
        draft_id = draft.id

    return {
        "ok": True,
        "draft_id": draft_id,
        "content_type": content_type,
        "draft_text": result.draft_text,
        "evidence_score": result.evidence_score,
        "voice_score": result.voice_score,
        "voice_notes": result.voice_notes,
        "unsupported_claims": result.unsupported_claims,
        "verification_required": result.verification_required,
        "audit": audit,
        "generation_method": result.generation_method,
        "cited_source_ids": result.cited_source_ids,
        "alternative_hooks": result.alternative_hooks,
    }


def _llm_draft(client: AIClient, opportunity: dict, content_type: str,
               evidence: list[dict]) -> DraftResult | None:
    evidence_lines = "\n".join(
        f"  [src {p['source_id']}] {p['passage']}" for p in evidence[:25]
    ) or "  (no verbatim evidence available)"
    number_lines = "\n".join(
        f"  [src {p['source_id']}] {p['passage']}"
        for p in evidence if re.search(r"\d", p.get("passage", ""))
    )[:4000] or "  (none)"

    if content_type == "linkedin_post":
        prompt = load_prompt("linkedin_draft").render(
            title=opportunity["title"],
            core_insight=opportunity.get("core_insight"),
            why_now=opportunity.get("why_now"),
            why_podium=opportunity.get("why_podium"),
            founder_point_of_view=opportunity.get("founder_point_of_view"),
            hook=opportunity.get("hook"),
            supporting_points="\n".join(
                f"  - {p.get('point')} [src {p.get('evidence_source_ids')}]"
                for p in opportunity.get("supporting_points", [])
            ),
            call_to_action=opportunity.get("suggested_call_to_action"),
            evidence_lines=evidence_lines,
            number_lines=number_lines,
            voice_guide=_voice_guide_text() or "(no approved voice examples yet)",
        )
    else:
        import json

        prompt = load_prompt("longform_outline").render(
            content_type=content_type,
            brief_json=json.dumps({k: v for k, v in opportunity.items() if k != "id"},
                                  ensure_ascii=False, default=str)[:6000],
            evidence_lines=evidence_lines,
            number_lines=number_lines,
            voice_guide=_voice_guide_text() or "(no approved voice examples yet)",
        )

    response = client.complete_json(prompt, max_tokens=2500)
    if not response.ok:
        log.warning("LLM draft failed (%s): %s", content_type, response.error)
        return None

    data = response.data
    text = (data.get("draft_text") or "").strip()
    if len(text.split()) < 30:
        return None

    return DraftResult(
        draft_text=text,
        content_type=content_type,
        claims_used=[c for c in data.get("claims_used", []) if isinstance(c, dict)],
        unsupported_claims=[str(c) for c in data.get("unsupported_claims", [])],
        verification_required=[str(v) for v in data.get("verification_required", [])],
        voice_notes=[str(n) for n in data.get("voice_alignment_notes", [])],
        cited_source_ids=sorted({
            c.get("source_id") for c in data.get("claims_used", [])
            if isinstance(c, dict) and isinstance(c.get("source_id"), int)
        }),
        alternative_hooks=[str(h) for h in data.get("alternative_hooks", [])],
        generation_method=response.model or "llm",
    )


def set_approval(draft_id: int, status: str, notes: str = "") -> bool:
    """Human approval gate. Nothing is ever published by the system."""
    if status not in {"pending_review", "changes_requested", "approved", "rejected"}:
        return False
    with session_scope() as session:
        draft = session.get(ContentDraft, draft_id)
        if draft is None:
            return False
        draft.approval_status = status
        draft.reviewer_notes = notes
        draft.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(draft)

        if status == "approved" and draft.content_opportunity_id:
            opportunity = session.get(ContentOpportunity, draft.content_opportunity_id)
            if opportunity is not None:
                opportunity.status = "approved"
                opportunity.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(opportunity)
    return True


def draft_source_links(draft_id: int) -> list[dict]:
    """Resolve a draft's cited source ids back to live URLs."""
    with session_scope() as session:
        draft = session.get(ContentDraft, draft_id)
        if draft is None:
            return []
        ids = list(draft.cited_source_ids or [])
        if not ids:
            opportunity = session.get(ContentOpportunity, draft.content_opportunity_id)
            ids = list(opportunity.supporting_source_ids or []) if opportunity else []
        if not ids:
            return []
        rows = session.execute(
            select(Source.id, Source.title, Source.canonical_url, Source.source_domain,
                   Source.published_at, Source.source_type)
            .where(Source.id.in_(ids))
        ).all()
    return [
        {"id": r[0], "title": r[1], "url": r[2], "domain": r[3],
         "published_at": r[4], "source_type": r[5]}
        for r in rows
    ]
