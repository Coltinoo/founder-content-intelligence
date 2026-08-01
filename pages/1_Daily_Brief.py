"""Daily Brief — the one-screen morning read, exportable as Markdown."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from fcie.db import init_db
from fcie.pipeline.brief_export import brief_to_markdown, build_daily_brief
from fcie.queries import BRIEF_WINDOWS, best_brief_window
from fcie.ui.components import (
    empty_state,
    evidence_block,
    format_date,
    header,
    page_setup,
    risk_badge,
    sidebar_status,
    trend_badge,
)

page_setup("Daily Brief", "📄")
init_db()
sidebar_status()
header("Daily Brief", "What changed, what it means, and what needs verifying.")

WINDOW_LABELS = {24: "last 24 hours", 48: "last 2 days", 72: "last 3 days",
                 168: "last week", 720: "last 30 days"}

# Default to the narrowest window that actually holds something rather than a
# fixed 48 hours — otherwise the page reads as broken any day you open it
# without having just run discovery.
default_window = best_brief_window()

col1, col2 = st.columns([1, 3])
lookback = col1.selectbox(
    "Window", list(BRIEF_WINDOWS),
    index=list(BRIEF_WINDOWS).index(default_window),
    format_func=lambda h: WINDOW_LABELS[h],
)
brief = build_daily_brief(lookback_hours=lookback)

markdown = brief_to_markdown(brief)
col2.download_button(
    "⬇ Export brief as Markdown",
    data=markdown,
    file_name=f"fcie-daily-brief-{datetime.utcnow().date().isoformat()}.md",
    mime="text/markdown",
)

counters = brief["counters"]
m1, m2, m3, m4 = st.columns(4)
m1.metric("New sources", len(brief["new_sources"]))
m1.caption(f"Found in the {WINDOW_LABELS[lookback]}")
m2.metric("Rising themes", len(brief["rising_themes"]))
m2.caption("Gaining ground across publishers")
m3.metric("Worth writing about", len(brief["opportunities"]))
m3.caption("Briefs with evidence behind them")
m4.metric("Needs verifying", len(brief["warnings"]))
m4.caption("Claims the system will not vouch for")

st.divider()

# ── new sources ─────────────────────────────────────────────────────────────
st.markdown("## Most important new sources")
if not brief["new_sources"]:
    empty_state(
        f"No sources discovered in the last {lookback} hours.",
        "Run discovery from the Executive Dashboard, or widen the window.",
    )
for source in brief["new_sources"]:
    st.markdown(
        f"### [{source['title']}]({source['url']})\n"
        f"<span class='fcie-muted'>{source['domain']} · {format_date(source['published_at'])} · "
        f"score {source['score']:.0f}/100 · risk {risk_badge(source['risk'])} · "
        f"theme: {source['theme'] or 'unassigned'}</span>",
        unsafe_allow_html=True,
    )
    if source["problem"]:
        st.markdown(f"**Problem identified in the source:** {source['problem']}")
    for passage in source["evidence"]:
        evidence_block(passage.get("passage", ""), source["id"], source["url"], source["domain"])
    for note in source["verification_notes"]:
        st.caption(f"⚠️ {note}")

st.divider()

# ── rising themes ───────────────────────────────────────────────────────────
st.markdown("## Top three rising themes")
if not brief["rising_themes"]:
    empty_state("No theme has met the trend threshold. A single source is never called a trend.")
for theme in brief["rising_themes"]:
    st.markdown(
        f"### {theme['name']} {trend_badge(theme['trend_status'])}\n"
        f"<span class='fcie-muted'>{int(theme['source_count'])} source(s) · "
        f"{int(theme['domains'])} domain(s) · {int(theme['industries'])} industry/ies · "
        f"{int(theme['current_period'])} this period vs {int(theme['previous_period'])} last "
        f"({theme['growth_rate']:+.0%})</span>",
        unsafe_allow_html=True,
    )
    if theme.get("rationale"):
        st.markdown(theme["rationale"])

st.divider()

# ── actions ─────────────────────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.markdown("## Recommended content actions")
    if not brief["opportunities"]:
        empty_state("No opportunities yet.")
    for opportunity in brief["opportunities"]:
        st.markdown(
            f"**{opportunity['title']}**  \n"
            f"<span class='fcie-muted'>score {opportunity['score']:.0f} · "
            f"confidence {opportunity['confidence']:.0f} · risk {opportunity['risk']:.0f} · "
            f"{opportunity['source_count']} source(s) · format: {opportunity['format']} · "
            f"status: {opportunity['status']}</span>",
            unsafe_allow_html=True,
        )

    st.markdown("## Drafts awaiting approval")
    if not brief["pending_drafts"]:
        st.caption("None pending.")
    for draft in brief["pending_drafts"]:
        st.markdown(
            f"- Draft **#{draft['id']}** ({draft['type']}) — evidence "
            f"{draft['evidence_score']:.0f}/100, voice {draft['voice_score']:.0f}/100, "
            f"{draft['unsupported']} unsupported sentence(s)"
        )

with right:
    st.markdown("## Engagement opportunities")
    st.caption(
        "Review only. The system never comments, likes, reposts, follows, or messages."
    )
    if not brief["watchlist"]:
        st.caption("Watchlist is empty.")
    for item in brief["watchlist"]:
        st.markdown(
            f"**{item['person_or_company']}** · {item['priority']} priority  \n"
            f"<span class='fcie-muted'>{item['topic']}</span>  \n"
            f"{item['suggested_response_angle']}  \n"
            f"[open source]({item['url']})",
            unsafe_allow_html=True,
        )

st.divider()
st.markdown("## Verification warnings")
if not brief["warnings"]:
    st.success("No outstanding verification warnings.")
for warning in brief["warnings"]:
    st.warning(warning)

with st.expander("Preview the exported Markdown"):
    st.code(markdown, language="markdown")
