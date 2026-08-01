"""Meeting to Content — turn a transcript into notes and post drafts.

The rest of this system reads the public web. This reads the raw material a
founder generates in a day: a call, an interview, a podcast.

It runs entirely in-session and writes nothing to the database, which is why it
is available in the public read-only demo. Nothing here mutates state.
"""

from __future__ import annotations

import pathlib
import re

import streamlit as st

from fcie.db import init_db
from fcie.pipeline.meetings import analyse_transcript, notes_to_markdown
from fcie.ui.components import (
    evidence_block,
    header,
    how_it_works,
    page_setup,
    sidebar_status,
)

SAMPLE_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "sample_meeting.txt"


def _same_text(left: str, right: str) -> bool:
    """Whether two strings say the same thing, ignoring punctuation and case."""
    def normalise(text: str) -> str:
        return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()

    return normalise(left) == normalise(right)


page_setup("Meeting to Content", "🎙")
init_db()
sidebar_status()
header(
    "Meeting to Content",
    "Paste a transcript from a call, an interview or a podcast. Get structured "
    "notes and draft posts back, with every quote checked against what was "
    "actually said.",
)

# ═══════════════════════════════════════════════════════════════════════════
st.markdown("## Turn a meeting into content")
st.markdown(
    "<div class='fcie-hero-sub'>The rest of this system reads the public web. "
    "This reads the raw material you generate in a day — a call, an interview, a "
    "podcast — and returns structured notes plus post drafts, with every quote "
    "checked against the transcript.</div>",
    unsafe_allow_html=True,
)
how_it_works([
    ("Paste a transcript", "A meeting, an interview, a podcast. Nothing is stored."),
    ("Read it for meaning", "Decisions, action items, open questions, quotable lines."),
    ("Check every quote", "Anything not word for word in the transcript is discarded."),
    ("Draft the posts", "Content ideas with drafts, each audited against the transcript."),
])

st.caption(
    "🔒 This runs in your browser session only. Nothing is written to the "
    "database, which is why it is available in this read-only demo."
)

sample_text = ""
if SAMPLE_PATH.exists():
    sample_text = SAMPLE_PATH.read_text(encoding="utf-8")

use_sample = st.checkbox(
    "Load the sample meeting (synthetic — written for this demo)",
    value=True,
    help="A short, entirely fictional GTM sync. No real person said any of it. "
         "Untick to paste your own transcript.",
)

transcript = st.text_area(
    "Transcript",
    value=sample_text if use_sample else "",
    height=260,
    placeholder="Paste a meeting, interview or podcast transcript here…",
    help="Speaker labels like 'Dana:' at the start of a line are recognised but "
         "not required.",
)
col1, col2 = st.columns([1, 2])
meeting_title = col1.text_input("Title", value="Weekly GTM sync"
                                if use_sample else "")
force_heuristic = col2.checkbox(
    "Use the deterministic analyser instead of the model",
    value=False,
    help="Shows what the system produces with no AI at all — phrase matching "
         "rather than reading for meaning. Useful for comparison.",
)

if st.button("Analyse this transcript", type="primary"):
    if not transcript.strip():
        st.error("Paste a transcript first, or tick the sample box.")
    else:
        with st.spinner("Reading the transcript…"):
            st.session_state["meeting_notes"] = analyse_transcript(
                transcript,
                title=meeting_title or "(untitled meeting)",
                force_heuristic=force_heuristic,
            )

notes = st.session_state.get("meeting_notes")
if notes is not None:
    st.divider()
    if not notes.ok:
        for warning in notes.warnings:
            st.warning(warning)
    else:
        st.markdown(f"# {notes.title}")
        st.caption(
            f"{notes.word_count} words of transcript · analysed by "
            f"`{notes.backend}` · nothing stored"
        )
        for warning in notes.warnings:
            st.info(warning)

        st.markdown("### Summary")
        st.markdown(notes.summary or "_None._")

        n1, n2 = st.columns(2)
        with n1:
            st.markdown("### Decisions")
            if not notes.decisions:
                st.caption("None recorded.")
            for row in notes.decisions:
                st.markdown(f"**{row['decision']}**"
                            + (f"  \n*{row['owner']}*" if row["owner"] else ""))
                # When the model lifts the decision straight out of the
                # transcript, `decision` and `quote` come back identical and
                # the same sentence renders twice. Show the quote only when
                # it adds something.
                if row["quote"] and not _same_text(row["quote"], row["decision"]):
                    st.markdown(
                        f"<div class='fcie-evidence'>{row['quote']}</div>",
                        unsafe_allow_html=True,
                    )
        with n2:
            st.markdown("### Action items")
            if not notes.action_items:
                st.caption("None recorded.")
            for row in notes.action_items:
                due = f" · due {row['due']}" if row["due"] else ""
                st.markdown(f"- **{row['action']}**"
                            + (f"  \n  {row['owner']}{due}" if row["owner"] else due))

        if notes.open_questions:
            st.markdown("### Left unresolved")
            for question in notes.open_questions:
                st.markdown(f"- {question}")

        if notes.quotes:
            st.markdown("### Quotable lines")
            st.caption("Every line here was checked word for word against the "
                       "transcript. Anything that failed was discarded.")
            for row in notes.quotes:
                evidence_block(row["quote"], None, None,
                               row["speaker"] or "transcript")

        if notes.sensitivity_notes:
            st.markdown("### Do not publish")
            for note in notes.sensitivity_notes:
                st.warning(note)

        # ── the payoff: mock posts ──────────────────────────────────────
        st.markdown("## Post drafts from this meeting")
        if not notes.content_ideas:
            st.caption("No publishable angle found in this transcript.")
        for index, idea in enumerate(notes.content_ideas, start=1):
            with st.container(border=True):
                st.markdown(f"### {index}. {idea['idea']}")
                if idea.get("audience"):
                    st.caption(f"For: {idea['audience']}")
                if idea.get("why_it_works"):
                    st.markdown(f"**Why now.** {idea['why_it_works']}")
                if idea.get("evidence_quote"):
                    st.markdown("**What was actually said:**")
                    st.markdown(
                        f"<div class='fcie-evidence'>{idea['evidence_quote']}</div>",
                        unsafe_allow_html=True,
                    )
                if idea.get("suggested_post"):
                    st.markdown("**Draft post**")
                    st.markdown(
                        f"<div class='fcie-inference'>{idea['suggested_post']}</div>",
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        f"AI-assisted suggestion for human review — not approved "
                        f"copy, and not written or endorsed by any named person. "
                        f"Audited at {idea.get('evidence_score', 0):.0f}/100 against "
                        f"the transcript."
                    )
                if idea.get("banned_phrases"):
                    st.warning(
                        "Marketing cliché caught by the style check: "
                        + ", ".join(f"“{p}”" for p in idea["banned_phrases"])
                        + ". Same list the web-sourced drafts are held to."
                    )
                for item in idea.get("needs_verification") or []:
                    st.caption(f"⚠️ Verify before publishing: {item}")

        st.divider()
        st.download_button(
            "⬇  Export these notes as Markdown",
            data=notes_to_markdown(notes),
            file_name="fcie-meeting-notes.md",
            mime="text/markdown",
        )
