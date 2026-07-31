"""Founder voice library.

Examples are added **manually** by a human pasting publicly available text and
its URL. Nothing here scrapes LinkedIn or any other platform, and no LinkedIn
action is ever automated.

The output is called *"founder voice alignment based on approved public
examples"*. It describes measurable patterns in a small sample of public text.
It does not claim to reproduce anyone's voice, and every default assumption that
the examples do not confirm is reported as unconfirmed.
"""

from __future__ import annotations

import logging
import re
import statistics
from datetime import datetime, timezone

from sqlalchemy import select

from ..ai.client import AIClient
from ..ai.prompts import load_prompt
from ..ai.taxonomy import match_themes
from ..db import session_scope
from ..models import VoiceExample
from ..utils.text import sentences, word_count

log = logging.getLogger(__name__)

# Provenance matters more than volume here. A company blog post and a founder's
# own LinkedIn post are both "public text", but only one is evidence of how the
# founder writes. Company SEO content is written by a marketing team to rank in
# search — treating it as founder voice would be the same category of error the
# rest of this system exists to prevent.
FOUNDER_CONTENT_TYPES = {
    "linkedin_post", "interview", "podcast", "press_quote", "keynote",
    "earnings_or_investor_comment",
}
COMPANY_CONTENT_TYPES = {"company_public_content", "blog_post", "other"}


def classify_provenance(content_type: str | None) -> str:
    """``verified_founder`` | ``company_editorial``."""
    return ("verified_founder" if (content_type or "") in FOUNDER_CONTENT_TYPES
            else "company_editorial")


DEFAULT_ASSUMPTIONS = [
    "Direct",
    "Clear",
    "Commercially focused",
    "Optimistic about AI",
    "Grounded in business outcomes",
    "Focused on local-business problems",
    "Uses short paragraphs",
    "Avoids generic AI hype",
    "Prefers measurable impact",
    "Connects product capability to revenue or customer outcomes",
]

_HYPE_TERMS = ("game-changer", "game changer", "revolutionize", "revolutionise",
               "unlock", "leverage", "paradigm", "disrupt", "10x", "supercharge")
_CONTRAST_PATTERNS = (
    r"\bisn'?t\b[^.]{0,60}\bit'?s\b", r"\bnot\b[^.]{0,50}\bbut\b",
    r"\bless\b[^.]{0,40}\bmore\b", r"\bdon'?t\b[^.]{0,50}\bdo\b",
)
_CTA_PATTERNS = (
    r"what (are|do) you", r"let me know", r"curious (what|how)", r"agree\?",
    r"how (are|do) you", r"tell me", r"drop a", r"reply", r"thoughts",
)
_NUMBER = re.compile(r"\b\d[\d,.]*\s?%?\b")
_STORY_MARKERS = ("a customer", "one of our customers", "a dealership", "a shop owner",
                  "a business owner", "we worked with", "last week i", "i talked to",
                  "i met", "a client")


def _split_paragraphs(text: str) -> list[str]:
    """Split into paragraphs, tolerating text that lost its blank lines.

    Article extraction often returns block-per-line rather than blank-line
    separated prose. Splitting only on blank lines then treats a whole 18,000-
    character article as ONE paragraph, and the voice guide reported "median
    123 sentences per paragraph" — a number that is arithmetically true and
    completely misleading, which is worse than no number at all.

    So: prefer blank-line structure when it exists; fall back to single
    newlines when it plainly does not.
    """
    blocks = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    if len(blocks) > 1:
        return blocks
    lines = [line.strip() for line in (text or "").split("\n") if line.strip()]
    return lines if len(lines) > 1 else blocks


def analyse_example(text: str, *, title: str | None = None) -> dict:
    """Measure one example. Every figure here is countable from the text."""
    text = (text or "").strip()
    if not text:
        return {"error": "empty text"}

    paragraphs = _split_paragraphs(text)
    sents = sentences(text)
    sentence_lengths = [len(s.split()) for s in sents] or [0]
    paragraph_sentence_counts = [max(len(sentences(p)), 1) for p in paragraphs] or [1]
    low = text.lower()

    first_sentence = sents[0] if sents else ""
    first_line = paragraphs[0].split("\n")[0] if paragraphs else ""
    hook = first_line if len(first_line.split()) <= 30 else first_sentence

    words = text.split()
    long_words = [w for w in words if len(w.strip(".,!?;:")) >= 9]

    theme_hits = match_themes(text, top_n=5)

    return {
        "word_count": word_count(text),
        "sentence_count": len(sents),
        "paragraph_count": len(paragraphs),
        "median_sentence_words": round(statistics.median(sentence_lengths), 1),
        "mean_sentence_words": round(statistics.fmean(sentence_lengths), 1),
        "max_sentence_words": max(sentence_lengths),
        "median_paragraph_sentences": round(statistics.median(paragraph_sentence_counts), 1),
        "short_sentence_share": round(
            sum(1 for n in sentence_lengths if n <= 12) / max(len(sentence_lengths), 1), 2
        ),
        "uses_fragments": any(n <= 5 for n in sentence_lengths),
        "hook": hook,
        "hook_words": len(hook.split()),
        "hook_is_question": hook.strip().endswith("?"),
        "hook_has_number": bool(_NUMBER.search(hook)),
        "number_count": len(_NUMBER.findall(text)),
        "numbers_per_100_words": round(len(_NUMBER.findall(text)) / max(word_count(text), 1) * 100, 2),
        "uses_contrast": any(re.search(p, low) for p in _CONTRAST_PATTERNS),
        "contrast_examples": [
            s for s in sents if any(re.search(p, s.lower()) for p in _CONTRAST_PATTERNS)
        ][:2],
        "uses_customer_story": any(m in low for m in _STORY_MARKERS),
        "uses_first_person": bool(re.search(r"\b(i|we|our|my)\b", low)),
        "hype_terms_found": [t for t in _HYPE_TERMS if t in low],
        "cta_present": any(re.search(p, low) for p in _CTA_PATTERNS),
        "cta_sentences": [s for s in sents if any(re.search(p, s.lower()) for p in _CTA_PATTERNS)][:2],
        "question_count": sum(1 for s in sents if s.strip().endswith("?")),
        "long_word_share": round(len(long_words) / max(len(words), 1), 3),
        "themes": [t.name for t, _s, _k in theme_hits],
        "closing_sentence": sents[-1] if sents else "",
        "analysed_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
    }


def analyse_and_store(example_id: int) -> dict:
    """Run the analyser over a stored example and write the summary fields."""
    with session_scope() as session:
        example = session.get(VoiceExample, example_id)
        if example is None:
            return {"error": f"voice example {example_id} not found"}
        analysis = analyse_example(example.pasted_text, title=example.title)
        if analysis.get("error"):
            return analysis

        example.analysis_json = analysis
        example.analysed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        example.hook_style = _describe_hook(analysis)
        example.sentence_style = (
            f"Median {analysis['median_sentence_words']} words per sentence; "
            f"{analysis['short_sentence_share']:.0%} of sentences are 12 words or fewer; "
            f"median {analysis['median_paragraph_sentences']} sentence(s) per paragraph."
        )
        example.recurring_themes = analysis["themes"]
        example.evidence_style = (
            f"{analysis['number_count']} figure(s) "
            f"({analysis['numbers_per_100_words']} per 100 words); "
            + ("includes a customer example." if analysis["uses_customer_story"]
               else "no customer example present.")
        )
        example.tone_notes = _describe_tone(analysis)
        session.add(example)
        return analysis


def _describe_hook(analysis: dict) -> str:
    bits = [f"{analysis['hook_words']}-word opening"]
    if analysis["hook_is_question"]:
        bits.append("question hook")
    if analysis["hook_has_number"]:
        bits.append("leads with a figure")
    if analysis["hook_words"] <= 10:
        bits.append("short declarative")
    return "; ".join(bits)


def _describe_tone(analysis: dict) -> str:
    bits = []
    bits.append("first person" if analysis["uses_first_person"] else "impersonal")
    if analysis["uses_contrast"]:
        bits.append("uses contrast framing")
    if analysis["hype_terms_found"]:
        bits.append("contains hype vocabulary: " + ", ".join(analysis["hype_terms_found"]))
    else:
        bits.append("no hype vocabulary detected")
    if analysis["cta_present"]:
        bits.append("ends with an invitation to respond")
    if analysis["question_count"]:
        bits.append(f"{analysis['question_count']} question(s)")
    return "; ".join(bits)


# ─────────────────────────────────────────────────────────────────────────────
# Voice guide
# ─────────────────────────────────────────────────────────────────────────────

def build_voice_guide(*, use_llm: bool = False) -> dict:
    """Aggregate the approved examples into an editable voice guide.

    Conclusions are derived from the examples. Anything from the default
    assumption list that the examples do not exhibit is reported as
    unconfirmed rather than asserted.
    """
    with session_scope() as session:
        examples = session.execute(
            select(VoiceExample)
            .where(VoiceExample.approved_for_voice_library.is_(True))
            .order_by(VoiceExample.date.desc().nulls_last()
                      if hasattr(VoiceExample.date, "desc") else VoiceExample.id.desc())
        ).scalars().all()
        payloads = [
            {
                "id": e.id, "title": e.title, "text": e.pasted_text,
                "url": e.source_url, "content_type": e.content_type,
                "date": e.date, "analysis": dict(e.analysis_json or {}),
            }
            for e in examples
        ]

    if not payloads:
        return {
            "approved_example_count": 0,
            "status": "empty",
            "message": (
                "No approved voice examples yet. Add public, manually-pasted examples on the "
                "Voice Library page. Until then the system uses no voice guide — it will not "
                "invent one, and drafts are generated without voice alignment."
            ),
            "unsupported_assumptions": DEFAULT_ASSUMPTIONS,
            "coverage_warning": "Zero examples: no voice conclusion can be drawn.",
        }

    analyses = []
    for payload in payloads:
        analysis = payload["analysis"] or analyse_example(payload["text"], title=payload["title"])
        analysis["_id"] = payload["id"]
        analysis["_title"] = payload["title"]
        analysis["_url"] = payload["url"]
        analyses.append(analysis)

    def median_of(key: str, default=0):
        values = [a.get(key) for a in analyses if isinstance(a.get(key), (int, float))]
        return round(statistics.median(values), 1) if values else default

    theme_counts: dict[str, int] = {}
    for analysis in analyses:
        for theme in analysis.get("themes", []):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
    recurring = sorted(
        [t for t, c in theme_counts.items() if c >= 2],
        key=lambda t: theme_counts[t], reverse=True,
    )

    contrast_share = sum(1 for a in analyses if a.get("uses_contrast")) / len(analyses)
    story_share = sum(1 for a in analyses if a.get("uses_customer_story")) / len(analyses)
    number_share = sum(1 for a in analyses if a.get("number_count", 0) > 0) / len(analyses)
    hype_examples = [t for a in analyses for t in a.get("hype_terms_found", [])]
    cta_share = sum(1 for a in analyses if a.get("cta_present")) / len(analyses)
    first_person_share = sum(1 for a in analyses if a.get("uses_first_person")) / len(analyses)
    content_types = sorted({p["content_type"] for p in payloads if p["content_type"]})

    # Which default assumptions do the examples actually support?
    confirmed, unconfirmed = [], []
    checks = {
        "Uses short paragraphs": median_of("median_paragraph_sentences", 99) <= 3,
        "Avoids generic AI hype": not hype_examples,
        "Prefers measurable impact": number_share >= 0.5,
        "Direct": median_of("median_sentence_words", 99) <= 20,
        "Clear": median_of("long_word_share", 1) <= 0.22,
        "Grounded in business outcomes": bool(recurring),
        "Focused on local-business problems": any(
            "local" in t.lower() or "business" in t.lower() for t in recurring
        ),
        "Commercially focused": any(
            t in recurring for t in ("Revenue ownership by AI", "Speed to lead",
                                     "Customer reactivation", "AI cost and measurable ROI")
        ),
    }
    for assumption in DEFAULT_ASSUMPTIONS:
        if checks.get(assumption) is True:
            confirmed.append(assumption)
        else:
            unconfirmed.append(assumption)

    coverage_warning = None
    if len(analyses) < 5:
        coverage_warning = (
            f"Only {len(analyses)} approved example(s). Below five examples these patterns "
            "are indicative, not reliable. Add more public examples before relying on them."
        )
    elif len(content_types) <= 1:
        coverage_warning = (
            f"All examples are of one type ({content_types[0] if content_types else 'unknown'}). "
            "The guide may not transfer to other formats."
        )

    # What the library actually contains decides what it may claim to be.
    founder_examples = [p for p in payloads
                        if classify_provenance(p["content_type"]) == "verified_founder"]
    company_examples = [p for p in payloads if p not in founder_examples]

    if founder_examples:
        label = (f"Founder voice alignment — {len(founder_examples)} verified founder "
                 f"example(s), {len(company_examples)} company editorial")
        provenance_warning = None if len(founder_examples) >= 5 else (
            f"Only {len(founder_examples)} verified founder example(s). Patterns below are "
            f"dominated by company editorial content and should be treated as a baseline, "
            f"not as the founder's voice."
        )
    else:
        label = "Podium Editorial Baseline — company content, not founder voice"
        provenance_warning = (
            "Every example in this library is company-published editorial or marketing "
            "content. That is written by a marketing team to rank in search, and it is NOT "
            "evidence of how the founder writes. Nothing here should be described as founder "
            "voice until verified founder posts, interviews or transcripts are added."
        )

    guide = {
        "approved_example_count": len(analyses),
        "founder_example_count": len(founder_examples),
        "company_example_count": len(company_examples),
        "provenance_warning": provenance_warning,
        "status": "derived",
        "label": label,
        "disclaimer": (
            "This describes measurable patterns in manually-approved public text. It does not "
            "reproduce, imitate, or represent any individual's voice, and no output should be "
            "presented as written or approved by them."
        ),
        "content_types": content_types,
        "median_sentence_words": median_of("median_sentence_words"),
        "median_paragraph_sentences": median_of("median_paragraph_sentences"),
        "median_word_count": median_of("word_count"),
        "short_sentence_share": median_of("short_sentence_share"),
        "uses_fragments": any(a.get("uses_fragments") for a in analyses),
        "median_hook_words": median_of("hook_words"),
        "example_hooks": [a.get("hook", "") for a in analyses if a.get("hook")][:5],
        "hook_patterns": _hook_patterns(analyses),
        "recurring_themes": recurring,
        "all_themes_seen": sorted(theme_counts, key=lambda t: theme_counts[t], reverse=True),
        "use_of_numbers": (
            f"{number_share:.0%} of examples contain at least one figure "
            f"(median {median_of('numbers_per_100_words')} per 100 words)."
        ),
        "use_of_customer_stories": f"{story_share:.0%} of examples reference a customer situation.",
        "use_of_contrast": f"{contrast_share:.0%} of examples use an explicit contrast construction.",
        "use_of_founder_experience": f"{first_person_share:.0%} of examples are written in the first person.",
        "typical_calls_to_action": _cta_examples(analyses),
        "cta_share": f"{cta_share:.0%} of examples end with an invitation to respond.",
        "hype_terms_found": sorted(set(hype_examples)),
        "tone": _tone_summary(analyses, hype_examples, contrast_share, first_person_share),
        "technical_detail_level": _technical_level(analyses),
        "confirmed_assumptions": confirmed,
        "unsupported_assumptions": unconfirmed,
        "coverage_warning": coverage_warning,
        "evidence_map": [
            {"conclusion": "sentence and paragraph rhythm",
             "example_titles": [a.get("_title") for a in analyses][:8]},
            {"conclusion": "recurring themes",
             "example_titles": [a.get("_title") for a in analyses if a.get("themes")][:8]},
        ],
        "examples": [
            {"id": a["_id"], "title": a.get("_title"), "url": a.get("_url"),
             "hook": a.get("hook"), "words": a.get("word_count")}
            for a in analyses
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generation_method": "heuristic-v1",
    }

    if use_llm:
        llm_guide = _llm_voice_guide(payloads)
        if llm_guide:
            guide["llm_analysis"] = llm_guide
            guide["generation_method"] = f"heuristic-v1 + {AIClient().model}"

    return guide


def _hook_patterns(analyses: list[dict]) -> list[str]:
    patterns = []
    questions = sum(1 for a in analyses if a.get("hook_is_question"))
    numbers = sum(1 for a in analyses if a.get("hook_has_number"))
    short = sum(1 for a in analyses if a.get("hook_words", 99) <= 10)
    total = len(analyses)
    if questions:
        patterns.append(f"{questions}/{total} open with a question")
    if numbers:
        patterns.append(f"{numbers}/{total} open with a figure")
    if short:
        patterns.append(f"{short}/{total} open with a line of 10 words or fewer")
    if not patterns:
        patterns.append("No single dominant hook pattern across the approved examples")
    return patterns


def _cta_examples(analyses: list[dict]) -> list[str]:
    out: list[str] = []
    for analysis in analyses:
        out.extend(analysis.get("cta_sentences", []))
    return out[:5]


def _tone_summary(analyses, hype_examples, contrast_share, first_person_share) -> str:
    bits = []
    median_sentence = statistics.median(
        [a.get("median_sentence_words", 0) for a in analyses]
    ) if analyses else 0
    bits.append("concise" if median_sentence <= 16 else "measured")
    bits.append("first-person" if first_person_share >= 0.6 else "third-person")
    bits.append("hype-free" if not hype_examples else "occasionally promotional")
    if contrast_share >= 0.4:
        bits.append("argues by contrast")
    return ", ".join(bits) + f" (derived from {len(analyses)} example(s))"


def _technical_level(analyses: list[dict]) -> str:
    share = statistics.fmean([a.get("long_word_share", 0) for a in analyses]) if analyses else 0
    if share < 0.12:
        level = "none"
    elif share < 0.18:
        level = "light"
    elif share < 0.25:
        level = "moderate"
    else:
        level = "heavy"
    return f"{level} (mean long-word share {share:.1%} across the approved examples)"


def _llm_voice_guide(payloads: list[dict]) -> dict | None:
    client = AIClient()
    if not client.available:
        return None
    blocks = []
    for payload in payloads[:12]:
        blocks.append(
            f"--- EXAMPLE {payload['id']} ---\n"
            f"title: {payload['title']}\n"
            f"type: {payload['content_type']}\n"
            f"date: {payload['date'].date().isoformat() if payload['date'] else 'not stated'}\n"
            f"url: {payload['url']}\n\n{payload['text']}\n"
        )
    prompt = load_prompt("voice_analysis").render(
        example_count=len(payloads),
        examples="\n".join(blocks),
    )
    response = client.complete_json(prompt, max_tokens=2500)
    return response.data if response.ok else None


def add_voice_example(*, title: str, text: str, source_url: str | None = None,
                      date: datetime | None = None, content_type: str = "linkedin_post",
                      approved: bool = False) -> int:
    """Store a manually-supplied public example and analyse it immediately."""
    if not (text or "").strip():
        raise ValueError("A voice example requires pasted text.")
    with session_scope() as session:
        example = VoiceExample(
            title=title or "(untitled)",
            source_url=source_url,
            pasted_text=text.strip(),
            date=date.replace(tzinfo=None) if date and date.tzinfo else date,
            content_type=content_type,
            approved_for_voice_library=approved,
        )
        session.add(example)
        session.flush()
        example_id = example.id
    analyse_and_store(example_id)
    return example_id
