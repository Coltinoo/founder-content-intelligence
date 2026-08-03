"""Daily Brief — the daily update: what changed, and what to publish.

What the agent found since the last run, then the strongest thing to publish
because of it — the idea, the drafts written from it, and the exact source
quote behind every claim.

This page ties the channels together. Each has its own page: Social Media
for public posts, Meeting to Content for transcripts, Source Library for the
full record of everything read.
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
    watchlist_items,
)
from fcie.ui.components import (
    card,
    chip,
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
    "What the agent found since you last looked, and the strongest thing to "
    "publish because of it — with the exact quote behind every claim.",
)

# ── what changed, before what to do about it ────────────────────────────────
# This page is the daily update. It used to open on an idea picker, which
# answers "what should I write" without first answering "what happened".
window = best_brief_window()
update = build_daily_brief(lookback_hours=window)
WINDOW_LABELS = {24: "24 hours", 48: "2 days", 72: "3 days",
                 168: "week", 720: "30 days"}

st.markdown(f"## Since the last {WINDOW_LABELS.get(window, 'run')}")
u1, u2, u3, u4 = st.columns(4)
u1.metric("New pages read", len(update["new_sources"]),
          help="Public pages the agent found and analysed in this window. It runs "
               "at 06:00 UTC every weekday without being asked.")
u2.metric("Topics gaining ground", len(update["rising_themes"]),
          help="Topics with more coverage this period than last, across more than "
               "one publisher.")
u3.metric("Ideas worth writing", len(update["opportunities"]),
          help="Topics with enough evidence behind them to argue a position.")
u4.metric("Flagged to verify", len(update["warnings"]),
          help="Numbers and claims the agent will not vouch for. It surfaces them "
               "rather than quietly passing them through.")

if update["new_sources"]:
    with st.expander(f"What arrived — {count_label(len(update['new_sources']), 'page')}",
                     expanded=False):
        for source in update["new_sources"]:
            st.markdown(
                f"**[{source['title']}]({source['url']})**  \n"
                f"<span class='fcie-muted'>{source['domain']} · "
                f"{source['theme'] or 'unclassified'} · scored "
                f"{source['score']:.0f}/100</span>",
                unsafe_allow_html=True,
            )
            if source.get("problem"):
                st.caption(f"Problem it describes: {source['problem']}")
            for passage in source["evidence"]:
                evidence_block(passage.get("passage", ""), source["id"],
                               source["url"], source["domain"])

if update["warnings"]:
    with st.expander(f"⚠️  {count_label(len(update['warnings']), 'thing')} to verify "
                     f"before repeating"):
        for warning in update["warnings"]:
            st.markdown(f"- {warning}")

# ── conversations worth a reply ─────────────────────────────────────────────
# A teaser spanning every channel — this page is the synthesis. The social
# posts get their own page, with the angle and provenance for each; repeating
# all of that here would make this page long without making it more useful.
watchlist = watchlist_items(statuses=["unreviewed"])
if watchlist:
    st.markdown("## Worth replying to")
    st.markdown(
        "<div class='fcie-hero-sub'>Public conversations where a reply would add "
        "something. Surfaced only — nothing is ever commented, liked, reposted or "
        "sent.</div>",
        unsafe_allow_html=True,
    )
    for item in watchlist[:3]:
        url = item.get("url") or ""
        platform = ("LinkedIn" if "linkedin.com" in url
                    else "X" if "x.com" in url
                    else "Reddit" if "reddit.com" in url else None)
        card(
            title=item["person_or_company"],
            meta=(f"{platform} · " if platform else "") + (item.get("topic") or ""),
            body=(item.get("recent_signal") or "")[:180],
            url=url or None,
            chip_html=chip(item["priority"],
                           tone={"high": "bad", "medium": "warn"}.get(item["priority"], "")),
        )
    st.caption(
        f"{count_label(len(watchlist), 'conversation')} in the queue. "
        f"Social posts, with the angle for each, are on **Social Media** →"
    )

st.divider()

# ═══════════════════════════════════════════════════════════════════════════
# What to publish because of it
# ═══════════════════════════════════════════════════════════════════════════
opportunities = opportunities_list()
if not opportunities:
    empty_state("No content ideas yet.",
                "Run discovery from the Dashboard to populate this view.")
else:
    ids = [o["id"] for o in opportunities]
    featured_id = featured_opportunity_id()
    default_index = ids.index(featured_id) if featured_id in ids else 0

    st.markdown("## What to publish")
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

    st.divider()
    st.download_button(
        "⬇  Export this update as Markdown",
        data=brief_to_markdown(update),
        file_name=f"fcie-daily-brief-"
                  f"{datetime.now(timezone.utc).date().isoformat()}.md",
        mime="text/markdown",
    )
