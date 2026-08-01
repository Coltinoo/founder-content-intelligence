"""Founder Content Intelligence Engine — Executive Dashboard (entry point).

Run with:  streamlit run streamlit_app.py
"""

from __future__ import annotations

import streamlit as st

from fcie.config import load_config
from fcie.db import init_db
from fcie.queries import (
    featured_opportunity_id,
    opportunity_detail,
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
    header,
    page_setup,
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
    "Know what to say next.",
    "Founder Content Intelligence reads the public web every day and turns what "
    "it finds into founder-ready content briefs — where every single claim links "
    "back to the source it came from.",
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

# ── why this exists, before any numbers ─────────────────────────────────────
# A first-time reader needs the problem stated before the machinery. One
# sentence, set apart, doing the job a product page's opening line does.
st.markdown(
    "<div class='fcie-pull'>A founder's most valuable asset is a point of view "
    "the market is ready to hear. Finding it means reading everything; publishing "
    "it safely means being able to prove every word. <b>This does the reading, and "
    "keeps the proof.</b></div>",
    unsafe_allow_html=True,
)

# ── the pipeline, as four numbers that mean something ───────────────────────
st.markdown("## What it found")
st.markdown(
    f"<div class='fcie-hero-sub'>Reading <b>{counters['total_sources']}</b> public "
    f"pages from <b>{counters['distinct_domains']}</b> publishers, grouped into "
    f"<b>{counters['themes']}</b> themes — <b>{counters['rising_themes']}</b> of them "
    f"gaining ground.</div>",
    unsafe_allow_html=True,
)
st.markdown("<div style='height:1.1rem'></div>", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Pages read", counters["total_sources"],
          f"+{counters['sources_24h']} today" if counters["sources_24h"] else None)
c1.caption("Collected from the public web")
c2.metric("Analysed", counters["extracted_signals"])
c2.caption("Facts and quotes pulled out")
c3.metric("Worth writing about", counters["opportunities"])
c3.caption("Themes with real evidence behind them")
c4.metric("Waiting on you", counters["drafts_pending"])
c4.caption("Drafts needing a human decision")

# ── the golden path: one worked example, front and centre ───────────────────
# Nobody evaluating this in two minutes will explore 15 opportunities across 18
# themes. They will judge it by the first one they open — so choose it for them,
# and make it the strongest complete example rather than the highest score.
featured_id = featured_opportunity_id()
if featured_id:
    featured = opportunity_detail(featured_id)
    if featured:
        opportunity = featured["opportunity"]
        independent = [s for s in featured["sources"] if not s.get("is_promotional")]
        st.markdown("## Today, write about this")
        st.markdown(
            "<div class='fcie-hero-sub'>One opportunity, chosen for you. Most "
            "corroboration, squarely on your market, already taken through to a "
            "draft.</div>",
            unsafe_allow_html=True,
        )
        st.markdown(f"### {opportunity['title']}")

        # The insight, then the line you would actually open with. Two ideas,
        # full width, nothing competing with them.
        st.markdown(opportunity["core_insight"] or "—")
        if opportunity.get("hook"):
            st.markdown(
                f"<div class='fcie-evidence'><b>Your opening line.</b> "
                f"{opportunity['hook']}</div>",
                unsafe_allow_html=True,
            )

        # Four facts, evenly spaced, each labelled in plain words. Previously
        # five chips ran together into one unreadable string.
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Sources behind it", len(featured["sources"]))
        f2.metric("Evidenced points", len(opportunity["supporting_points"]))
        f3.metric("Drafts ready", len(featured["drafts"]))
        f4.metric("Confidence", f"{opportunity['confidence_score']:.0f}/100")

        # A low independent count is not a defect to hide — it is the system
        # reporting that a narrative is carried mostly by vendors.
        if len(independent) < 3:
            st.markdown(
                f"<div class='fcie-inference'><b>Worth knowing.</b> Only "
                f"{count_label(len(independent), 'independent publisher')} in this "
                f"cluster — the rest is vendor marketing. That is a real finding about "
                f"how this narrative is being carried, and it is why the risk score "
                f"reads {opportunity['risk_score']:.0f}/100. The brief lists it "
                f"explicitly.</div>",
                unsafe_allow_html=True,
            )
        st.caption(
            "Open **Content Brief** for the full argument, every supporting point "
            "with its verbatim source passage, the risk notes and the LinkedIn draft →"
        )

st.divider()

# ── highest-ranking signals ─────────────────────────────────────────────────
left, right = st.columns([1.45, 1], gap="large")

with left:
    st.markdown("## What the market is saying")
    st.markdown(
        "<div class='fcie-hero-sub' style='margin:-.4rem 0 1rem'>"
        "The pages most worth your time today, scored on relevance, evidence, "
        "freshness and novelty. Open any one to see the full breakdown.</div>",
        unsafe_allow_html=True,
    )
    signals = top_signals(limit=5)
    if not signals:
        empty_state("No signals extracted yet. Run discovery to populate this view.")
    for signal in signals:
        signal_card(signal)

with right:
    st.markdown("## Themes gaining ground")
    themes = themes_dataframe()
    if themes.empty:
        empty_state("No themes computed yet.")
    else:
        rising = themes[themes["trend_status"].isin(["rising", "emerging"])]
        if rising.empty:
            rising = themes.sort_values("source_count", ascending=False).head(5)
            st.caption("No theme has met the rising threshold — showing highest-volume themes.")
        for _, theme in rising.head(4).iterrows():
            card(
                title=theme["name"],
                meta=(f"{count_label(int(theme['source_count']), 'source')} across "
                      f"{count_label(int(theme['domains']), 'publisher')}"),
                chip_html=chip(trend_badge(theme["trend_status"])),
            )
        st.caption("Full detail on the Trend Radar page →")

    st.markdown("## Also ready to write")
    opportunities = opportunities_list()
    if not opportunities:
        empty_state("No opportunities generated yet.")
    # Exclude the one already featured above — repeating it here is the kind of
    # duplication that makes a page feel longer than it is.
    others = [o for o in opportunities if o["id"] != featured_id][:4]
    for opportunity in others:
        card(
            title=truncate_words(opportunity["title"], 14),
            meta=f"{count_label(opportunity['source_count'], 'source')} · "
                 f"{humanize_label(opportunity['status'])}",
            chip_html=score_bar(opportunity["score"], "opportunity"),
        )
    if others:
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
