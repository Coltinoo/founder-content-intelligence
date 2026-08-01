"""Daily Brief — the content page: what to post, and the agent that drafts it.

Two ways in. The top half is content the pipeline produced overnight from the
public web. The bottom half is the meeting-notes agent: paste a transcript from
a call, an interview or a podcast, and it returns notes plus post drafts.

The agent runs entirely in-session and writes nothing to the database, which is
why it is available in the public read-only demo. Nothing here mutates state.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import streamlit as st

from fcie.db import init_db
from fcie.pipeline.brief_export import brief_to_markdown, build_daily_brief
from fcie.pipeline.meetings import analyse_transcript, notes_to_markdown
from fcie.queries import (
    BRIEF_WINDOWS,
    best_brief_window,
    featured_opportunity_id,
    opportunities_list,
    opportunity_detail,
)
from fcie.ui.components import (
    admin,
    empty_state,
    evidence_block,
    header,
    how_it_works,
    inference_block,
    page_setup,
    risk_badge,
    score_bar,
    sidebar_status,
)
from fcie.utils.format import count_label, relative_time

SAMPLE_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "sample_meeting.txt"

page_setup("Daily Brief", "📄")
init_db()
sidebar_status()
header(
    "Daily Brief",
    "What to post today, with the evidence attached — and an agent that turns "
    "any meeting, interview or podcast into notes and post drafts.",
)

tab_posts, tab_meeting = st.tabs(
    ["📝  Ready to post", "🎙  Turn a meeting into content"]
)

# ═══════════════════════════════════════════════════════════════════════════
# 1. Content the overnight pipeline produced
# ═══════════════════════════════════════════════════════════════════════════
with tab_posts:
    opportunities = opportunities_list()
    if not opportunities:
        empty_state("No content ideas yet.",
                    "Run discovery from the Dashboard to populate this view.")
    else:
        ids = [o["id"] for o in opportunities]
        featured_id = featured_opportunity_id()
        default_index = ids.index(featured_id) if featured_id in ids else 0

        st.markdown("## Pick an idea")
        selected_id = st.selectbox(
            "Content idea",
            ids,
            index=default_index,
            label_visibility="collapsed",
            format_func=lambda i: (
                ("★  " if i == featured_id else "     ")
                + next(o["title"] for o in opportunities if o["id"] == i)[:90]
            ),
        )
        if selected_id == featured_id:
            st.caption(
                "★ Today's pick — on your market, backed by more publishers than any "
                "other idea, and already taken through to a draft."
            )

        detail = opportunity_detail(int(selected_id))
        if detail is None:
            st.error("That idea could not be loaded.")
            st.stop()

        opportunity = detail["opportunity"]
        drafts = detail["drafts"]
        sources = detail["sources"]

        st.markdown(f"# {opportunity['title']}")
        st.markdown(opportunity["core_insight"] or "_No summary generated._")

        m1, m2, m3 = st.columns(3)
        m1.metric("Sources behind it", len(sources),
                  help="Separate public pages discussing this. More sources across more "
                       "publishers means the idea is real, not one outlet's opinion.")
        m2.metric("Points you can prove", len(opportunity["supporting_points"]),
                  help="Arguments with an exact quote from a real source attached. "
                       "Points that could not be evidenced were dropped, not softened.")
        m3.metric("Publication risk", f"{opportunity['risk_score']:.0f}/100",
                  help="How exposed you would be publishing this — unverified numbers, "
                       "vendor-heavy sourcing, competitor claims. Lower is safer. Scored "
                       "separately from how good the idea is, on purpose.")

        # ── the drafts: what the user actually came here for ────────────────
        st.markdown("## The posts")
        if not drafts:
            empty_state(
                "No drafts written for this idea yet.",
                "Every draft is generated from the evidence above and audited "
                "sentence by sentence before it is shown.",
            )
        for draft in drafts:
            with st.container(border=True):
                score = draft.get("evidence_score") or 0.0
                st.markdown(f"**{draft['content_type'].replace('_', ' ').title()}**")
                st.markdown(draft["draft_text"])
                st.markdown(
                    f"<div class='fcie-srcline'>Every draft is checked line by line "
                    f"against the stored evidence. This one scored "
                    f"<b>{score:.0f}/100</b> — the share of its factual sentences that "
                    f"trace to a source. Status: {draft['approval_status'].replace('_', ' ')}."
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if score < 30:
                    st.warning(
                        "Most of this draft is not traceable to a source. That is the "
                        "audit working, not a bug — the generator wrote connective "
                        "prose. Rewrite around the evidence, or drop it."
                    )

        # ── the proof ───────────────────────────────────────────────────────
        st.markdown("## Why you can say it")
        st.caption(
            "Each point below sits next to the exact sentence from the source that "
            "backs it. Points that could not be evidenced were removed."
        )
        for index, point in enumerate(opportunity["supporting_points"], start=1):
            st.markdown(f"**{index}. {point.get('point', '')}**")
            evidence_block(
                point.get("evidence_passage", ""),
                (point.get("evidence_source_ids") or [None])[0],
                point.get("evidence_url"),
                point.get("evidence_domain"),
            )

        if opportunity.get("founder_point_of_view"):
            st.markdown("## The angle")
            inference_block(opportunity["founder_point_of_view"],
                            "Our reading of the evidence — not something a source said")

        checklist = opportunity.get("verification_checklist") or []
        risks = opportunity.get("risk_notes") or []
        if checklist or risks:
            with st.expander(f"⚠️  Check {count_label(len(checklist) + len(risks), 'thing')} "
                             f"before publishing"):
                for item in checklist:
                    st.markdown(f"- **{item.get('item', '')}** — {item.get('why', '')}")
                for note in risks:
                    st.markdown(f"- {note}")

        window = best_brief_window()
        st.divider()
        st.download_button(
            "⬇  Export today's brief as Markdown",
            data=brief_to_markdown(build_daily_brief(lookback_hours=window)),
            file_name=f"fcie-daily-brief-"
                      f"{datetime.now(timezone.utc).date().isoformat()}.md",
            mime="text/markdown",
        )

# ═══════════════════════════════════════════════════════════════════════════
# 2. The meeting agent
# ═══════════════════════════════════════════════════════════════════════════
with tab_meeting:
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
                    if row["quote"]:
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
