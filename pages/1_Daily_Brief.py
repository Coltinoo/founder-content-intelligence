"""Daily Brief — what to post today, with the evidence attached.

Content the overnight pipeline produced from the public web: the idea, the
drafts written from it, and the exact source quote behind every claim.

The meeting agent lives on its own page — see pages/2_Meeting_to_Content.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from fcie.db import init_db
from fcie.pipeline.brief_export import brief_to_markdown, build_daily_brief
from fcie.queries import (
    best_brief_window,
    featured_opportunity_id,
    opportunities_list,
    opportunity_detail,
)
from fcie.ui.components import (
    empty_state,
    evidence_block,
    header,
    inference_block,
    page_setup,
    sidebar_status,
)
from fcie.utils.format import count_label



page_setup("Daily Brief", "📄")
init_db()
sidebar_status()
header(
    "Daily Brief",
    "The strongest thing to publish today, the drafts already written from it, "
    "and the exact quote behind every claim so you can check it before you post.",
)

# ═══════════════════════════════════════════════════════════════════════════
# 1. Content the overnight pipeline produced
# ═══════════════════════════════════════════════════════════════════════════
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
    own = [s for s in sources if s.get("is_first_party")]
    outside = len(sources) - len(own)
    m1.metric("Outside sources", outside,
              help="Pages from publishers we do not own. Our own site is excluded "
                   "from this count — quoting ourselves is not corroboration.")
    m2.metric("Points you can prove", len(opportunity["supporting_points"]),
              help="Arguments with an exact quote from a real source attached. "
                   "Points that could not be evidenced were dropped, not softened.")
    m3.metric("Publication risk", f"{opportunity['risk_score']:.0f}/100",
              help="How exposed you would be publishing this — unverified numbers, "
                   "vendor-heavy sourcing, competitor claims. Lower is safer. Scored "
                   "separately from how good the idea is, on purpose.")

    if own:
        st.caption(
            f"⌂ A further {count_label(len(own), 'source')} in this cluster "
            f"{'is' if len(own) == 1 else 'are'} our own site. Kept so you can see "
            f"what we have already published, but not counted as corroboration."
        )

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
