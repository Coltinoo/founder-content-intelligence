"""Meeting, interview and podcast transcripts → structured notes and post ideas.

The rest of this system reads the public web. This reads the raw material a
founder generates in a day — a call, an interview, a podcast — and turns it into
notes plus publishable content ideas.

It runs *without touching the database*. That is deliberate: it means the public
read-only demo can accept a pasted transcript and show the agent working end to
end, without any stored data changing. Nothing here writes, so nothing here
needs an admin gate.

The anti-hallucination contract is the same as everywhere else: every quote and
every piece of evidence is re-checked against the transcript with
``is_verbatim`` before it is shown, and anything that fails is discarded and
counted rather than displayed.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from ..ai.client import AIClient
from ..ai.prompts import load_prompt
from ..utils.text import clean_text, is_verbatim, sentences, word_count
from .drafts import audit_draft

log = logging.getLogger(__name__)

MIN_TRANSCRIPT_WORDS = 60
MAX_TRANSCRIPT_CHARS = 24000


@dataclass
class MeetingNotes:
    title: str = "(untitled meeting)"
    summary: str = ""
    decisions: list[dict] = field(default_factory=list)
    action_items: list[dict] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    quotes: list[dict] = field(default_factory=list)
    content_ideas: list[dict] = field(default_factory=list)
    sensitivity_notes: list[str] = field(default_factory=list)
    backend: str = "heuristic-v1"
    dropped_unverifiable: int = 0
    warnings: list[str] = field(default_factory=list)
    word_count: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.summary or self.decisions or self.action_items or self.quotes)


def _verbatim_or_none(candidate: str | None, transcript: str) -> str | None:
    """Return the quote only if it really appears in the transcript."""
    text = (candidate or "").strip().strip('"“”')
    if not text:
        return None
    return text if is_verbatim(text, transcript) else None


# ── speaker-aware helpers ────────────────────────────────────────────────────

_SPEAKER_RE = re.compile(r"^\s*([A-Z][\w .'-]{1,40}?)\s*:\s*(.+)$")

_DECISION_MARKERS = ("we'll ", "we will ", "let's ", "we're going to ",
                     "decision is", "we've decided", "we should ", "agreed")
_ACTION_MARKERS = ("i'll ", "i will ", "can you ", "please ", "take that",
                   "by friday", "by monday", "next week", "action item",
                   "owns ", "will own", "follow up")
_QUESTION_MARKERS = ("?",)


def _lines_with_speakers(transcript: str) -> list[tuple[str | None, str]]:
    out: list[tuple[str | None, str]] = []
    for raw in (transcript or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _SPEAKER_RE.match(line)
        if match:
            out.append((match.group(1).strip(), match.group(2).strip()))
        else:
            out.append((None, line))
    return out


def _heuristic_notes(transcript: str, title: str) -> MeetingNotes:
    """Deterministic fallback so the page works with no model available.

    Marker-based, not clever. It exists so a demo never dead-ends on a missing
    API key, and so there is always a baseline to compare the model against.
    """
    notes = MeetingNotes(title=title, backend="heuristic-v1")
    lines = _lines_with_speakers(transcript)

    for speaker, text in lines:
        low = text.lower()
        if any(m in low for m in _DECISION_MARKERS) and len(text.split()) >= 5:
            notes.decisions.append(
                {"decision": text, "owner": speaker or "unattributed", "quote": text}
            )
        elif any(m in low for m in _ACTION_MARKERS) and len(text.split()) >= 5:
            notes.action_items.append(
                {"action": text, "owner": speaker or "unattributed", "due": "",
                 "quote": text}
            )
        if text.endswith(_QUESTION_MARKERS) and len(text.split()) >= 5:
            notes.open_questions.append(text)

    # Longest substantive lines make the most quotable material.
    ranked = sorted(
        (t for _s, t in lines if 12 <= len(t.split()) <= 45),
        key=lambda t: -len(t),
    )
    notes.quotes = [
        {"quote": text, "speaker": "", "why_notable": "Longest substantive statements."}
        for text in ranked[:4]
    ]

    body = " ".join(t for _s, t in lines)
    notes.summary = " ".join(sentences(body)[:3]) or "(transcript too short to summarise)"
    notes.decisions = notes.decisions[:6]
    notes.action_items = notes.action_items[:8]
    notes.open_questions = notes.open_questions[:6]

    if ranked:
        notes.content_ideas = [{
            "idea": "Draft an argument from the most substantive point raised.",
            "audience": "Local business owners and operators",
            "why_it_works": (
                "[Inference] Built without a language model — this is the longest "
                "substantive line in the transcript, not a judgement about what is "
                "most publishable."
            ),
            "evidence_quote": ranked[0],
            "suggested_post": "",
            "needs_verification": [
                "Written by the deterministic fallback. Re-run with the model "
                "configured for a usable draft."
            ],
        }]
    notes.warnings.append(
        "No language model configured — these notes come from the deterministic "
        "fallback, which matches phrases rather than reading for meaning."
    )
    return notes


def _coerce_list(value) -> list:
    return [v for v in value if v] if isinstance(value, list) else []


def analyse_transcript(
    transcript: str,
    *,
    title: str = "(untitled meeting)",
    force_heuristic: bool = False,
) -> MeetingNotes:
    """Structured notes and content ideas from a transcript. Never writes to the DB."""
    cleaned = clean_text(transcript or "")
    words = word_count(cleaned)
    if words < MIN_TRANSCRIPT_WORDS:
        return MeetingNotes(
            title=title,
            warnings=[f"Transcript is {words} words. At least "
                      f"{MIN_TRANSCRIPT_WORDS} are needed to extract anything useful."],
            word_count=words,
        )

    client = AIClient()
    if force_heuristic or not client.available:
        notes = _heuristic_notes(cleaned, title)
        notes.word_count = words
        return notes

    prompt = load_prompt("meeting_notes").render(
        title=title, transcript=cleaned[:MAX_TRANSCRIPT_CHARS]
    )
    response = client.complete_json(prompt, max_tokens=3000)
    if not response.ok:
        log.warning("Meeting analysis failed, using fallback: %s", response.error)
        notes = _heuristic_notes(cleaned, title)
        notes.word_count = words
        notes.warnings.insert(0, f"The model call failed ({response.error}).")
        return notes

    data = response.data or {}
    notes = MeetingNotes(title=title, backend=client.model, word_count=words)
    notes.summary = str(data.get("summary") or "").strip()
    notes.open_questions = [str(q) for q in _coerce_list(data.get("open_questions"))][:8]
    notes.sensitivity_notes = [
        str(s) for s in _coerce_list(data.get("sensitivity_notes"))
    ][:8]

    # ── the gate: a quote that is not in the transcript does not get shown ──
    for row in _coerce_list(data.get("decisions")):
        if not isinstance(row, dict):
            continue
        quote = _verbatim_or_none(row.get("quote"), cleaned)
        if quote is None and row.get("quote"):
            notes.dropped_unverifiable += 1
        notes.decisions.append({
            "decision": str(row.get("decision") or "").strip(),
            "owner": str(row.get("owner") or "").strip(),
            "quote": quote or "",
        })

    for row in _coerce_list(data.get("action_items")):
        if not isinstance(row, dict):
            continue
        quote = _verbatim_or_none(row.get("quote"), cleaned)
        if quote is None and row.get("quote"):
            notes.dropped_unverifiable += 1
        notes.action_items.append({
            "action": str(row.get("action") or "").strip(),
            "owner": str(row.get("owner") or "").strip(),
            "due": str(row.get("due") or "").strip(),
            "quote": quote or "",
        })

    for row in _coerce_list(data.get("quotes")):
        if not isinstance(row, dict):
            continue
        quote = _verbatim_or_none(row.get("quote"), cleaned)
        if quote is None:
            notes.dropped_unverifiable += 1
            continue  # a quote that is not verbatim is not a quote
        notes.quotes.append({
            "quote": quote,
            "speaker": str(row.get("speaker") or "").strip(),
            "why_notable": str(row.get("why_notable") or "").strip(),
        })

    for row in _coerce_list(data.get("content_ideas")):
        if not isinstance(row, dict):
            continue
        evidence = _verbatim_or_none(row.get("evidence_quote"), cleaned)
        if evidence is None and row.get("evidence_quote"):
            notes.dropped_unverifiable += 1
        post = str(row.get("suggested_post") or "").strip()
        # Audit the suggested post against the transcript itself, using the same
        # sentence-level auditor the web-sourced drafts go through. It reads
        # `source_id`/`url`/`domain` off each passage when it finds a match, so
        # the transcript has to look like a source even though it is not stored.
        audit = audit_draft(post, [{
            "passage": cleaned,
            "source_id": 0,
            "url": "",
            "domain": "this transcript",
        }]) if post else {}
        notes.content_ideas.append({
            "idea": str(row.get("idea") or "").strip(),
            "audience": str(row.get("audience") or "").strip(),
            "why_it_works": str(row.get("why_it_works") or "").strip(),
            "evidence_quote": evidence or "",
            "suggested_post": post,
            "evidence_score": audit.get("evidence_score", 0.0),
            "unsupported_claims": audit.get("unsupported_claims", []),
            # The same cliché list the web-sourced drafts are held to. The
            # generator reaches for "game-changer" and "in today's fast-paced"
            # unprompted; showing that it was caught is more useful than
            # silently allowing it.
            "banned_phrases": audit.get("banned_phrases", []),
            "needs_verification": [
                str(v) for v in _coerce_list(row.get("needs_verification"))
            ][:6],
        })

    if notes.dropped_unverifiable:
        notes.warnings.append(
            f"{notes.dropped_unverifiable} quoted line(s) did not appear in the "
            "transcript word for word and were discarded rather than shown."
        )
    return notes


def notes_to_markdown(notes: MeetingNotes) -> str:
    """Export, so the notes can leave the app and go where work actually happens."""
    from .. import DISCLAIMER

    lines = [
        f"# {notes.title}",
        "",
        f"_{notes.word_count} words of transcript · analysed by {notes.backend}_",
        "",
        f"> {DISCLAIMER}",
        "",
        "## Summary",
        "",
        notes.summary or "_None._",
        "",
    ]

    def block(heading: str, rows: list, render) -> None:
        lines.extend([f"## {heading}", ""])
        if not rows:
            lines.extend(["_None recorded._", ""])
            return
        lines.extend(render(rows))
        lines.append("")

    block("Decisions", notes.decisions, lambda rows: [
        f"- **{r['decision']}**" + (f" — {r['owner']}" if r["owner"] else "")
        + (f"\n  > {r['quote']}" if r["quote"] else "")
        for r in rows
    ])
    block("Action items", notes.action_items, lambda rows: [
        f"- [ ] **{r['action']}**" + (f" — {r['owner']}" if r["owner"] else "")
        + (f" (due {r['due']})" if r["due"] else "")
        for r in rows
    ])
    block("Open questions", notes.open_questions, lambda rows: [f"- {q}" for q in rows])
    block("Notable quotes", notes.quotes, lambda rows: [
        f"> {r['quote']}" + (f"\n> — {r['speaker']}" if r["speaker"] else "")
        for r in rows
    ])

    lines.extend(["## Content ideas", ""])
    if not notes.content_ideas:
        lines.extend(["_None._", ""])
    for index, idea in enumerate(notes.content_ideas, start=1):
        lines.append(f"### {index}. {idea['idea']}")
        if idea.get("audience"):
            lines.append(f"**Audience:** {idea['audience']}")
        if idea.get("why_it_works"):
            lines.append(f"**Why now:** {idea['why_it_works']}")
        if idea.get("evidence_quote"):
            lines.append(f"\n> {idea['evidence_quote']}\n")
        if idea.get("suggested_post"):
            lines.append("**Draft post — AI-assisted suggestion, not approved copy:**")
            lines.append("")
            lines.append(idea["suggested_post"])
        for item in idea.get("needs_verification") or []:
            lines.append(f"- ⚠️ Verify: {item}")
        lines.append("")

    if notes.sensitivity_notes:
        lines.extend(["## Do not publish", ""])
        lines.extend(f"- {s}" for s in notes.sensitivity_notes)
        lines.append("")
    if notes.warnings:
        lines.extend(["## Notes on this analysis", ""])
        lines.extend(f"- {w}" for w in notes.warnings)

    return "\n".join(lines)
