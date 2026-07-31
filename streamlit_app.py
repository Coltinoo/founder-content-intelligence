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
    card,
    chip,
    empty_state,
    format_date,
    header,
    page_setup,
    risk_chip,
    run_pipeline_widget,
    score_bar,
    sidebar_status,
    signal_card,
    trend_badge,
)
from fcie.utils.format import count_label, humanize_label, relative_time, truncate_words

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
c1.metric("Sources", counters["total_sources"],
          f"+{counters['sources_24h']} today" if counters["sources_24h"] else None)
c2.metric("Domains", counters["distinct_domains"])
c3.metric("Signals", counters["extracted_signals"])
c4.metric("Themes", counters["themes"],
          f"{counters['rising_themes']} rising" if counters["rising_themes"] else None)
c5.metric("Opportunities", counters["opportunities"])
c6.metric("Drafts to review", counters["drafts_pending"])

notes = []
if counters["needs_review"]:
    notes.append(f"{count_label(counters['needs_review'], 'source')} need review")
if counters["policy_skipped"]:
    notes.append(
        f"{counters['policy_skipped']} skipped by crawl policy (robots.txt, paywall, "
        "or excluded platform)"
    )
last_run = counters.get("last_run")
if last_run:
    notes.append(
        f"last run {relative_time(last_run['started_at'])} — "
        f"{last_run['stored']} stored, {last_run['duplicates']} duplicates merged"
    )
if notes:
    st.markdown(f"<div class='fcie-muted'>{' · '.join(notes)}</div>",
                unsafe_allow_html=True)

st.divider()

# ── highest-ranking signals ─────────────────────────────────────────────────
left, right = st.columns([1.45, 1], gap="large")

with left:
    st.markdown("## Highest-ranking signals")
    st.markdown(
        "<div class='fcie-muted' style='margin:-.35rem 0 .7rem'>"
        "Ranked by a transparent 100-point model. Every score breaks down on the "
        "source's detail page.</div>",
        unsafe_allow_html=True,
    )
    signals = top_signals(limit=6)
    if not signals:
        empty_state("No signals extracted yet. Run discovery to populate this view.")
    for signal in signals:
        signal_card(signal)

with right:
    st.markdown("## Rising themes")
    themes = themes_dataframe()
    if themes.empty:
        empty_state("No themes computed yet.")
    else:
        rising = themes[themes["trend_status"].isin(["rising", "emerging"])]
        if rising.empty:
            rising = themes.sort_values("source_count", ascending=False).head(5)
            st.caption("No theme has met the rising threshold — showing highest-volume themes.")
        for _, theme in rising.head(5).iterrows():
            card(
                title=theme["name"],
                meta=(f"{count_label(int(theme['source_count']), 'source')} · "
                      f"{count_label(int(theme['domains']), 'domain')}"),
                chip_html=(
                    chip(trend_badge(theme["trend_status"]))
                    + chip("relevance", f"{theme['avg_relevance']:.1f}/10")
                    + chip("evidence", f"{theme['avg_evidence']:.1f}/10")
                ),
            )
        st.caption("Full detail on the Trend Radar page →")

    st.markdown("## Top opportunities")
    opportunities = opportunities_list()
    if not opportunities:
        empty_state("No opportunities generated yet.")
    for opportunity in opportunities[:4]:
        card(
            title=truncate_words(opportunity["title"], 16),
            meta=f"{count_label(opportunity['source_count'], 'source')} · "
                 f"{humanize_label(opportunity['status'])}",
            chip_html=(
                score_bar(opportunity["score"], "opportunity")
                + chip("confidence", f"{opportunity['confidence']:.0f}")
                + risk_chip(opportunity["risk"])
            ),
        )
    if opportunities:
        st.caption("Review and approve on the Content Pipeline page →")

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
