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

cfg = load_config()
counters = dashboard_counters()

header(
    "Executive Dashboard",
    "Reads the public web every day and turns what it finds into founder-content "
    "briefs — where every claim links back to the source it came from.",
)

if counters["total_sources"] == 0:
    run_pipeline_widget()
    empty_state(
        "The library is empty.",
        "Open **Run discovery** above and press *Run discovery*, or run "
        "`python scripts/run_discovery.py --quick` from the command line. "
        "You can also add sources by hand on the **Source Library** page.",
    )
    st.stop()

# ── the one-paragraph answer, before any dials ──────────────────────────────
st.markdown(
    f"<div class='fcie-lead'>Tracking <b>{counters['total_sources']}</b> public sources "
    f"across <b>{counters['distinct_domains']}</b> publishers. "
    f"They cluster into <b>{counters['themes']}</b> themes, of which "
    f"<b>{counters['rising_themes']}</b> are gaining ground — and "
    f"<b>{counters['opportunities']}</b> have enough evidence behind them to be worth "
    f"writing about.</div>",
    unsafe_allow_html=True,
)
st.markdown("<div style='height:.4rem'></div>", unsafe_allow_html=True)

# ── the pipeline, as four numbers that mean something ───────────────────────
st.markdown("## The pipeline")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Sources collected", counters["total_sources"],
          f"+{counters['sources_24h']} today" if counters["sources_24h"] else None)
c1.caption("Public pages read and stored")
c2.metric("Analysed", counters["extracted_signals"])
c2.caption("Facts, quotes and themes extracted")
c3.metric("Ready to write", counters["opportunities"])
c3.caption("Themes with enough evidence")
c4.metric("To review", counters["drafts_pending"])
c4.caption("Waiting on a human decision")

st.divider()

# ── highest-ranking signals ─────────────────────────────────────────────────
left, right = st.columns([1.45, 1], gap="large")

with left:
    st.markdown("## What's worth your attention")
    st.markdown(
        "<div class='fcie-muted' style='margin:-.35rem 0 .7rem'>"
        "The highest-scoring sources that are actually about this market. "
        "Scored out of 100 on relevance, evidence quality, freshness and novelty — "
        "open any source to see the full breakdown.</div>",
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

# ── Operations: everything an operator needs, nothing a reader does ─────────
# Deliberately last. A first-time visitor should meet the findings before the
# machinery; previously the page opened with three configuration blocks.
st.markdown("## Run & diagnostics")
run_pipeline_widget()

ops_left, ops_right = st.columns(2)

with ops_left:
    with st.expander("Collection health"):
        rows = []
        if counters["needs_review"]:
            rows.append(f"- {count_label(counters['needs_review'], 'source')} need review "
                        "(too little body text to analyse)")
        if counters["policy_skipped"]:
            rows.append(
                f"- {counters['policy_skipped']} skipped by crawl policy — robots.txt, a "
                "paywall, or an excluded platform. Nothing was bypassed."
            )
        last_run = counters.get("last_run")
        if last_run:
            rows.append(
                f"- Last run {relative_time(last_run['started_at'])}: "
                f"{last_run['stored']} stored, {last_run['duplicates']} duplicates merged, "
                f"{len(last_run['errors'])} errors"
            )
        st.markdown("\n".join(rows) if rows else "Nothing to report.")

    missing = [r for r in cfg.integration_status() if r["ready"] in ("no", "fallback")]
    if missing:
        with st.expander(f"{len(missing)} optional integrations not configured"):
            st.caption("The app runs without them; each is skipped with a reason.")
            for row in missing:
                st.markdown(f"**{row['integration']}** — {row['status']}  \n{row['detail']}")

with ops_right:
    with st.expander("Recent runs"):
        runs = recent_runs(6)
        if not runs:
            st.caption("No runs recorded yet.")
        for run in runs:
            st.markdown(
                f"**#{run['id']}** · {run['trigger']} · {relative_time(run['started_at'])} — "
                f"{run['stored']} stored, {run['signals']} analysed, "
                f"{run['opportunities']} opportunities, {run['errors']} errors"
            )
