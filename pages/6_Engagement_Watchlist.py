"""Engagement Watchlist — public conversations worth a human's review. Never automated."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from fcie.db import init_db
from fcie.pipeline.engagement import build_watchlist, set_review_status
from fcie.queries import watchlist_items
from fcie.ui.components import empty_state, format_date, header, page_setup, sidebar_status

page_setup("Engagement Watchlist", "👁")
init_db()
sidebar_status()
header("Engagement Watchlist", "Conversations a human may want to join — surfaced, never acted on.")

st.warning(
    "**This system never comments, likes, reposts, follows, connects, or messages.** "
    "It produces a review queue and stops. Every URL below is a source already in the "
    "library; no profile URL is constructed or looked up, and no LinkedIn activity is "
    "automated.",
    icon="🔒",
)

col1, col2, col3 = st.columns([1, 1, 2])
status_filter = col1.multiselect(
    "Review status", ["unreviewed", "reviewed", "dismissed", "actioned_by_human"],
    default=["unreviewed"],
)
priority_filter = col2.multiselect("Priority", ["high", "medium", "low"],
                                   default=["high", "medium", "low"])
if col3.button("↻ Rebuild watchlist"):
    with st.spinner("Scanning recent high-relevance sources…"):
        report = build_watchlist()
    st.success(f"{report.created} item(s) added, {report.skipped} already present "
               f"(backend: {report.backend}).")
    st.cache_data.clear()
    st.rerun()

items = [
    item for item in watchlist_items(statuses=status_filter or None)
    if item["priority"] in priority_filter
]

if not items:
    empty_state(
        "The watchlist is empty for these filters.",
        "Press *Rebuild watchlist* after running discovery.",
    )
    st.stop()

counts = pd.Series([i["priority"] for i in items]).value_counts()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Items shown", len(items))
m2.metric("High priority", int(counts.get("high", 0)))
m3.metric("Medium", int(counts.get("medium", 0)))
m4.metric("Low", int(counts.get("low", 0)))

st.divider()

priority_icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}

for item in items:
    with st.container(border=True):
        head_left, head_right = st.columns([3, 1])
        head_left.markdown(
            f"### {priority_icon.get(item['priority'], '·')} {item['person_or_company']}\n"
            f"<span class='fcie-muted'>{item['topic']} · discovered "
            f"{format_date(item['discovered_at'])} · status: {item['review_status']}</span>",
            unsafe_allow_html=True,
        )
        head_right.markdown(f"[Open source]({item['url']})")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Recent signal**")
            st.markdown(item["recent_signal"] or "—")
            st.markdown("**Why it is relevant**")
            st.caption(item["why_relevant"] or "—")
        with c2:
            st.markdown("**Connection to Podium**")
            st.caption(item["podium_connection"] or "—")
            st.markdown("**Suggested response angle**")
            st.markdown(item["suggested_response_angle"] or "—")

        if item["risk_notes"]:
            st.caption(f"⚠️ {item['risk_notes']}")

        a1, a2, a3, _ = st.columns([1, 1, 1, 3])
        if a1.button("Mark reviewed", key=f"rev_{item['id']}"):
            set_review_status(item["id"], "reviewed")
            st.cache_data.clear()
            st.rerun()
        if a2.button("Dismiss", key=f"dis_{item['id']}"):
            set_review_status(item["id"], "dismissed")
            st.cache_data.clear()
            st.rerun()
        if a3.button("A human acted", key=f"act_{item['id']}"):
            set_review_status(item["id"], "actioned_by_human")
            st.cache_data.clear()
            st.rerun()
