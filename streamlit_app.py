"""Founder Content Intelligence Engine — Executive Dashboard (entry point).

Run with:  streamlit run streamlit_app.py
"""

from __future__ import annotations

import streamlit as st

from fcie.config import load_config
from fcie.db import init_db
from fcie.queries import (
    dashboard_counters,
    opportunities_list,
    recent_runs,
    themes_dataframe,
    top_signals,
)
from fcie.ui.components import (
    empty_state,
    format_date,
    header,
    method_tag,
    page_setup,
    risk_badge,
    run_pipeline_widget,
    sidebar_status,
    trend_badge,
)

page_setup("Executive Dashboard", "◆")
init_db()
sidebar_status()

header(
    "Executive Dashboard",
    "Public company, founder, customer and industry signals → a source-grounded "
    "founder-content pipeline.",
)

cfg = load_config()
counters = dashboard_counters()

# ── setup guidance ──────────────────────────────────────────────────────────
missing = [row for row in cfg.integration_status() if row["ready"] in ("no", "fallback")]
if missing:
    with st.expander(f"⚙️ {len(missing)} integration(s) unconfigured — the app still runs", expanded=False):
        for row in missing:
            st.markdown(f"**{row['integration']}** — {row['status']}  \n{row['detail']}")

run_pipeline_widget()

if counters["total_sources"] == 0:
    empty_state(
        "The library is empty.",
        "Open **Run discovery** above and press *Run discovery*, or run "
        "`python scripts/run_discovery.py` from the command line. "
        "You can also add sources by hand on the **Source Library** page.",
    )
    st.stop()

# ── counters ────────────────────────────────────────────────────────────────
st.markdown("## Coverage")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Sources", counters["total_sources"], f"+{counters['sources_24h']} in 24h")
c2.metric("Domains", counters["distinct_domains"])
c3.metric("Signals extracted", counters["extracted_signals"])
c4.metric("Themes", counters["themes"], f"{counters['rising_themes']} rising")
c5.metric("Opportunities", counters["opportunities"])
c6.metric("Drafts pending", counters["drafts_pending"])

if counters["needs_review"] or counters["policy_skipped"]:
    st.caption(
        f"{counters['needs_review']} source(s) need review · "
        f"{counters['policy_skipped']} skipped by crawl policy (robots.txt, paywall, or "
        "excluded platform) — see the Source Library."
    )

last_run = counters.get("last_run")
if last_run:
    st.caption(
        f"Last run #{last_run['id']} ({last_run['trigger']}) at "
        f"{format_date(last_run['started_at'])} — {last_run['stored']} stored, "
        f"{last_run['duplicates']} duplicate(s) merged, {last_run['signals']} signal(s), "
        f"{len(last_run['errors'])} error(s)."
    )

st.divider()

# ── highest-ranking signals ─────────────────────────────────────────────────
left, right = st.columns([1.35, 1])

with left:
    st.markdown("## Highest-ranking signals")
    signals = top_signals(limit=8)
    if not signals:
        empty_state("No signals extracted yet. Run discovery to populate this view.")
    for signal in signals:
        st.markdown(
            f"**[{signal['title'][:110]}]({signal['url']})**  \n"
            f"<span class='fcie-muted'>{signal['domain']} · {format_date(signal['published_at'])} · "
            f"theme: {signal['theme'] or 'unassigned'}</span>",
            unsafe_allow_html=True,
        )
        s1, s2, s3, s4 = st.columns([1, 1, 1, 2])
        s1.markdown(f"**{signal['score']:.0f}**/100  \n<span class='fcie-muted'>opportunity</span>",
                    unsafe_allow_html=True)
        s2.markdown(f"{risk_badge(signal['risk'])}  \n<span class='fcie-muted'>risk</span>",
                    unsafe_allow_html=True)
        s3.markdown(f"{signal['evidence_strength']:.0f}/10  \n<span class='fcie-muted'>evidence</span>",
                    unsafe_allow_html=True)
        s4.markdown(method_tag(signal["extraction_method"]), unsafe_allow_html=True)
        if signal["problem"]:
            st.caption(f"Problem identified in source: {signal['problem'][:220]}")
        st.markdown("<hr>", unsafe_allow_html=True)

with right:
    st.markdown("## Rising themes")
    themes = themes_dataframe()
    if themes.empty:
        empty_state("No themes computed yet.")
    else:
        rising = themes[themes["trend_status"].isin(["rising", "emerging"])]
        if rising.empty:
            rising = themes.sort_values("source_count", ascending=False).head(5)
            st.caption("No theme has met the rising threshold — showing the highest-volume themes.")
        for _, theme in rising.head(6).iterrows():
            st.markdown(
                f"**{theme['name']}** {trend_badge(theme['trend_status'])}  \n"
                f"<span class='fcie-muted'>{int(theme['source_count'])} source(s) · "
                f"{int(theme['domains'])} domain(s) · "
                f"relevance {theme['avg_relevance']:.1f}/10 · "
                f"evidence {theme['avg_evidence']:.1f}/10</span>",
                unsafe_allow_html=True,
            )
        st.caption("Full detail on the Trend Radar page.")

    st.markdown("## Top content opportunities")
    opportunities = opportunities_list()
    if not opportunities:
        empty_state("No opportunities generated yet.")
    for opportunity in opportunities[:5]:
        st.markdown(
            f"**{opportunity['title'][:120]}**  \n"
            f"<span class='fcie-muted'>score {opportunity['score']:.0f} · "
            f"confidence {opportunity['confidence']:.0f} · "
            f"risk {opportunity['risk']:.0f} · {opportunity['source_count']} source(s) · "
            f"{opportunity['status']}</span>",
            unsafe_allow_html=True,
        )
    if opportunities:
        st.caption("Open the Content Pipeline page to review and approve.")

st.divider()
with st.expander("Recent pipeline runs"):
    runs = recent_runs(8)
    if not runs:
        st.caption("No runs recorded yet.")
    for run in runs:
        st.markdown(
            f"**#{run['id']}** · {run['trigger']} · {format_date(run['started_at'])} — "
            f"{run['stored']} stored, {run['duplicates']} duplicate(s), {run['signals']} signal(s), "
            f"{run['themes']} theme(s), {run['opportunities']} opportunity/ies, "
            f"{run['errors']} error(s)"
        )
        if run["notes"]:
            st.caption(run["notes"])
