"""Trend Radar — theme frequency, growth, corroboration breadth, and evidence quality."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from fcie.config import load_config
from fcie.db import init_db
from fcie.pipeline.trends import get_theme_sources, run_trend_analysis
from fcie.queries import themes_dataframe
from fcie.utils.format import growth_phrase
from fcie.ui.components import (
    admin,
    empty_state,
    evidence_block,
    format_date,
    header,
    page_setup,
    sidebar_status,
    trend_badge,
)

page_setup("Trend Radar", "📈")
init_db()
sidebar_status()
header("Trend Radar", "Which narratives are actually growing — and which are one publisher "
                     "repeating itself.")

cfg = load_config()
col1, col2 = st.columns([3, 1])
col1.caption(
    f"Current period: last {cfg.trends.current_period_days} days · compared with the "
    f"{cfg.trends.previous_period_days} days before that. A theme needs at least "
    f"{cfg.trends.min_sources_for_trend} source(s) across "
    f"{cfg.trends.min_domains_for_trend} distinct domain(s) before it is called a trend."
)
if admin() and col2.button("↻ Recompute trends"):
    with st.spinner("Recomputing…"):
        report = run_trend_analysis()
    st.success(f"{report.themes_updated} theme(s) updated.")
    st.cache_data.clear()
    st.rerun()

themes = themes_dataframe()
if themes.empty:
    empty_state("No themes computed yet.", "Run discovery, then press *Recompute trends*.")
    st.stop()

# ── status filter ───────────────────────────────────────────────────────────
statuses = st.multiselect(
    "Trend status",
    ["emerging", "rising", "stable", "declining", "saturated", "low_confidence"],
    default=["emerging", "rising", "stable", "saturated"],
)
view = themes[themes["trend_status"].isin(statuses)] if statuses else themes

if view.empty:
    empty_state("No themes with the selected status.")
    st.stop()

# ── charts ──────────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)

with c1:
    st.markdown("#### Theme volume and corroboration")
    chart_frame = view.sort_values("source_count", ascending=False).head(14)
    chart = (
        alt.Chart(chart_frame)
        .mark_bar()
        .encode(
            y=alt.Y("name:N", sort="-x", title=None),
            x=alt.X("source_count:Q", title="Supporting sources"),
            color=alt.Color("trend_status:N", title="Status",
                            scale=alt.Scale(scheme="tableau10")),
            tooltip=["name", "trend_status", "source_count", "domains",
                     "avg_relevance", "avg_evidence"],
        )
        .properties(height=min(34 * len(chart_frame) + 40, 500))
    )
    st.altair_chart(chart, use_container_width=True)

with c2:
    st.markdown("#### Relevance vs evidence strength")
    st.caption("Bubble size = number of supporting sources. Top-right is where founder "
               "content should come from.")
    scatter = (
        alt.Chart(view)
        .mark_circle(opacity=0.75)
        .encode(
            x=alt.X("avg_relevance:Q", title="Avg Podium relevance (0-10)",
                    scale=alt.Scale(domain=[0, 10])),
            y=alt.Y("avg_evidence:Q", title="Avg evidence strength (0-10)",
                    scale=alt.Scale(domain=[0, 10])),
            size=alt.Size("source_count:Q", title="Sources"),
            color=alt.Color("trend_status:N", title="Status",
                            scale=alt.Scale(scheme="tableau10")),
            tooltip=["name", "trend_status", "source_count", "domains",
                     "avg_relevance", "avg_evidence", "growth_rate"],
        )
        .properties(height=380)
    )
    st.altair_chart(scatter, use_container_width=True)

# ── table ───────────────────────────────────────────────────────────────────
st.markdown("#### All themes")
table = view[[
    "name", "trend_status", "source_count", "domains", "industries",
    "current_period", "previous_period", "growth_rate",
    "avg_relevance", "avg_founder_relevance", "avg_evidence", "avg_impact",
    "first_seen", "last_seen", "recency_days",
]].rename(columns={
    "name": "Theme", "trend_status": "Status", "source_count": "Sources",
    "domains": "Domains", "industries": "Industries",
    "current_period": "This period", "previous_period": "Last period",
    "growth_rate": "Growth", "avg_relevance": "Podium rel.",
    "avg_founder_relevance": "Founder rel.", "avg_evidence": "Evidence",
    "avg_impact": "Impact", "first_seen": "First seen", "last_seen": "Last seen",
    "recency_days": "Days since",
}).sort_values("Sources", ascending=False)

st.dataframe(
    table, hide_index=True, width="stretch", height=380,
    column_config={
        "Growth": st.column_config.NumberColumn("Growth", format="%.0f%%"),
        "First seen": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
        "Last seen": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
    },
)

st.divider()

# ── theme detail ────────────────────────────────────────────────────────────
st.markdown("## Theme detail")
theme_name = st.selectbox("Theme", view.sort_values("source_count", ascending=False)["name"].tolist())
theme_row = view[view["name"] == theme_name].iloc[0]

st.markdown(f"### {theme_row['name']} {trend_badge(theme_row['trend_status'])}")
st.caption(theme_row["description"] or "")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Sources", int(theme_row["source_count"]))
m2.metric("Distinct domains", int(theme_row["domains"]))
m3.metric("Industries", int(theme_row["industries"]))
m4.metric("This period", int(theme_row["current_period"]))
m4.caption(growth_phrase(theme_row["current_period"], theme_row["previous_period"]))
m5.metric("Days since newest", f"{theme_row['recency_days']:.0f}" if pd.notna(theme_row["recency_days"]) else "—")

s1, s2, s3, s4 = st.columns(4)
s1.metric("Podium relevance", f"{theme_row['avg_relevance']:.1f}/10")
s2.metric("Founder relevance", f"{theme_row['avg_founder_relevance']:.1f}/10")
s3.metric("Evidence strength", f"{theme_row['avg_evidence']:.1f}/10")
s4.metric("Business impact", f"{theme_row['avg_impact']:.1f}/10")

if theme_row.get("rationale"):
    st.markdown("**Why it was labelled this way**")
    st.markdown(theme_row["rationale"])

st.markdown("### Supporting sources")
sources = get_theme_sources(theme_name)
if not sources:
    st.caption("No supporting sources found.")
for source in sources:
    st.markdown(
        f"**[{(source['title'] or '(untitled)')[:120]}]({source['url']})** "
        f"<span class='fcie-muted'>· {source['domain']} · {format_date(source['published_at'])} · "
        f"{source['assignment']} assignment · score {source['opportunity_score']:.0f}/100</span>",
        unsafe_allow_html=True,
    )
    if source["customer_problem"]:
        st.caption(f"Problem: {source['customer_problem'][:230]}")
    for passage in (source["evidence"] or [])[:2]:
        evidence_block(passage.get("passage", ""), source["source_id"], source["url"], source["domain"])
