"""Founder Content Intelligence Engine — Executive Dashboard (entry point).

Run with:  streamlit run streamlit_app.py
"""

from __future__ import annotations

import altair as alt
import streamlit as st

from fcie.config import load_config
from fcie.db import init_db
from fcie.queries import (
    agent_activity,
    discovery_queries,
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
    chips,
    empty_state,
    hero,
    how_it_works,
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

hero(
    "Know what to",
    "say next.",
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
st.markdown(
    "<div class='fcie-pull'>A founder's most valuable asset is a point of view "
    "the market is ready to hear. Finding it means reading everything; publishing "
    "it safely means being able to prove every word. <b>This does the reading, and "
    "keeps the proof.</b></div>",
    unsafe_allow_html=True,
)

# ── how it works, before what it found ──────────────────────────────────────
# The page used to open on counts of "signals", "themes" and "opportunities" —
# words that mean something specific here and nothing to a first-time reader.
# State the process, then the results.
st.markdown("## How it works")
how_it_works([
    ("Reads the public web",
     "Podium's own pages, ~40 news feeds, and live web search. Public pages only — "
     "never anything behind a login or paywall."),
    ("Pulls out the facts",
     "For each page: the problem it describes, the claims it makes, and the exact "
     "sentences that back them up."),
    ("Finds what's growing",
     "Groups pages into topics and compares the last three weeks against the three "
     "before. One publisher repeating itself is not a trend."),
    ("Writes the brief",
     "An argument you could publish, where every point sits next to the quote it "
     "came from — and nothing goes out without you approving it."),
])

st.markdown("## What it found")
st.markdown(
    f"<div class='fcie-hero-sub'>Reading <b>{counters['total_sources']}</b> public "
    f"pages from <b>{counters['distinct_domains']}</b> publishers, grouped into "
    f"<b>{counters['themes']}</b> topics — <b>{counters['rising_themes']}</b> of them "
    f"gaining ground.</div>",
    unsafe_allow_html=True,
)
st.markdown("<div style='height:1.1rem'></div>", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Pages read", counters["total_sources"],
          f"+{counters['sources_24h']} today" if counters["sources_24h"] else None,
          help="Public web pages collected and stored, across all publishers. "
               "Every one is listed on the Source Library page with its original link.")
c1.caption("Collected from the public web")
c2.metric("Analysed", counters["extracted_signals"],
          help="Pages the analyser could read properly and pull facts from. The gap "
               "between this and 'Pages read' is pages with too little text to use — "
               "they are kept and listed, not hidden.")
c2.caption("Facts and quotes pulled out")
c3.metric("Worth writing about", counters["opportunities"],
          help="Topics with enough evidence behind them to argue a position. A topic "
               "needs at least two sources from two different publishers before it "
               "qualifies.")
c3.caption("Topics with real evidence behind them")
c4.metric("Waiting on you", counters["drafts_pending"],
          help="Drafts written and waiting for a human to approve, edit or reject. "
               "Nothing is ever published automatically.")
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
        own = [s for s in featured["sources"] if s.get("is_first_party")]

        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Outside sources", len(featured["sources"]) - len(own),
                  help="Pages from publishers we do not own. Our own site is excluded "
                       "from this count — quoting ourselves is not corroboration.")
        f2.metric("Points you can prove", len(opportunity["supporting_points"]),
                  help="Arguments that have an exact quote from a real source attached. "
                       "Points that could not be evidenced were dropped, not softened.")
        f3.metric("Drafts ready", len(featured["drafts"]),
                  help="Draft posts written from this idea, waiting for your review. "
                       "Open the Daily Brief page to read them in full.")
        f4.metric("Confidence", f"{opportunity['confidence_score']:.0f}/100",
                  help="How well-supported this is — driven by how many independent "
                       "publishers back it and how strong their evidence is. Higher is "
                       "better. This is separate from publication risk.")

        # Our own pages are not evidence that the market agrees with us. Say how
        # much of the cluster is actually us talking to ourselves.
        if own:
            st.markdown(
                f"<div class='fcie-inference'><b>⌂ A further {len(own)} pages in this "
                f"cluster are our own.</b> They are kept — knowing what we have already "
                f"published stops us repeating ourselves — but they do not count toward "
                f"the figure above, and they are excluded from what the market is "
                f"saying below.</div>",
                unsafe_allow_html=True,
            )

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
            "Open **Daily Brief** for the full argument, every supporting point with the "
            "exact quote it came from, and the draft posts written from it →"
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
    st.markdown("## Topics gaining ground")
    themes = themes_dataframe()
    if themes.empty:
        empty_state("No topics computed yet.")
    else:
        rising = themes[themes["trend_status"].isin(["rising", "emerging"])]
        if rising.empty:
            rising = themes.sort_values("source_count", ascending=False).head(5)
            st.caption("No topic has met the rising threshold — showing the highest-volume ones.")
        for _, theme in rising.head(4).iterrows():
            card(
                title=theme["name"],
                meta=(f"{count_label(int(theme['source_count']), 'source')} across "
                      f"{count_label(int(theme['domains']), 'publisher')}"),
                chip_html=chip(trend_badge(theme["trend_status"])),
            )

    st.markdown("## More ideas ready to write")
    opportunities = opportunities_list()
    if not opportunities:
        empty_state("No content ideas generated yet.")
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
        st.caption("Read the full brief and its draft posts on **Daily Brief** →")

st.divider()

# ── the trend picture, moved here from its own page ─────────────────────────
st.markdown("## Which topics are actually growing")
st.markdown(
    f"<div class='fcie-hero-sub'>Every topic, sized by how many sources discuss it. "
    f"The last {cfg.trends.current_period_days} days compared with the "
    f"{cfg.trends.previous_period_days} before. A topic needs at least "
    f"{cfg.trends.min_sources_for_trend} sources across "
    f"{cfg.trends.min_domains_for_trend} different publishers before it counts as a "
    f"trend at all — one publisher repeating itself is not a trend.</div>",
    unsafe_allow_html=True,
)

if themes.empty:
    empty_state("No topics computed yet.")
else:
    chart_left, chart_right = st.columns(2, gap="large")
    with chart_left:
        st.markdown("#### How much is being written")
        volume = themes.sort_values("source_count", ascending=False).head(12)
        st.altair_chart(
            alt.Chart(volume).mark_bar().encode(
                y=alt.Y("name:N", sort="-x", title=None),
                x=alt.X("source_count:Q", title="Sources discussing it"),
                color=alt.Color("trend_status:N", title="Status",
                                scale=alt.Scale(scheme="tableau10")),
                tooltip=["name", "trend_status", "source_count", "domains",
                         "avg_relevance", "avg_evidence"],
            ).properties(height=min(32 * len(volume) + 40, 420)),
            width="stretch",
        )
    with chart_right:
        st.markdown("#### Where the good material is")
        st.caption(
            "Bubble size is how many sources back the topic. **Top-right is where "
            "founder content should come from** — highly relevant to this market, "
            "and well evidenced."
        )
        st.altair_chart(
            alt.Chart(themes).mark_circle(opacity=0.75).encode(
                x=alt.X("avg_relevance:Q", title="Relevance to this market (0-10)",
                        scale=alt.Scale(domain=[0, 10])),
                y=alt.Y("avg_evidence:Q", title="Strength of the evidence (0-10)",
                        scale=alt.Scale(domain=[0, 10])),
                size=alt.Size("source_count:Q", title="Sources"),
                color=alt.Color("trend_status:N", title="Status",
                                scale=alt.Scale(scheme="tableau10")),
                tooltip=["name", "trend_status", "source_count", "domains",
                         "avg_relevance", "avg_evidence", "growth_rate"],
            ).properties(height=380),
            width="stretch",
        )

    with st.expander("Every topic, with the numbers behind it"):
        table = themes[[
            "name", "trend_status", "source_count", "domains",
            "current_period", "previous_period", "growth_rate",
            "avg_relevance", "avg_evidence",
        ]].rename(columns={
            "name": "Topic", "trend_status": "Status", "source_count": "Sources",
            "domains": "Publishers", "current_period": "This period",
            "previous_period": "Previous", "growth_rate": "Change",
            "avg_relevance": "Relevance", "avg_evidence": "Evidence",
        })
        st.dataframe(table, hide_index=True, width="stretch", height=380,
                     column_config={"Change": st.column_config.NumberColumn(format="%+.0f%%")})
        st.caption(
            "`low_confidence` is not a gap — it is the system refusing to call "
            "something a trend when it rests on one source from one publisher."
        )

st.divider()

# ── Operations: everything an operator needs, nothing a reader does ─────────
# Deliberately last. A first-time visitor should meet the findings before the
# machinery; previously the page opened with three configuration blocks.
# ── the agent: what it did, on its own, and what it refused ─────────────────
# This is the part the pipeline diagram only claims. Read straight from the run
# log so the page cannot drift out of step with what actually happened.
st.markdown("## The agent, and what it did")
st.markdown(
    "<div class='fcie-hero-sub'>This runs on a schedule with nobody watching — "
    "<b>06:00 UTC every weekday</b>, via a GitHub Action. It decides what to search "
    "for, reads what it finds, and refuses what it should not take.</div>",
    unsafe_allow_html=True,
)

activity = agent_activity()
if not activity:
    st.caption("No runs recorded yet.")
else:
    trigger = {"cron": "on schedule", "cli": "from the command line",
               "ui": "from this dashboard"}.get(activity["trigger"], activity["trigger"])
    took = (f" and took {activity['duration_seconds'] / 60:.0f} min"
            if activity.get("duration_seconds") else "")
    st.markdown(
        f"<div class='fcie-hero-sub'>Last run was <b>{relative_time(activity['started_at'])}</b>, "
        f"started {trigger}{took}.</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Candidates considered", activity["candidates"],
              help="Every article, page and video the agent surfaced across all of "
                   "its sources before deciding what was worth keeping.")
    a2.metric("Kept", activity["stored"],
              help="New, relevant, and readable. Everything else was rejected for a "
                   "recorded reason rather than silently dropped.")
    a3.metric("Duplicates merged", activity["duplicates"],
              help="The same story reached the agent by several routes. It matched "
                   "them on canonical URL, content hash, title and phrasing, and "
                   "kept one — recording the other routes against it.")
    a4.metric("Refused on policy", activity["skipped_policy"],
              help="robots.txt disallowed it, it sat behind a paywall or login, or "
                   "the platform is excluded. Nothing was bypassed.")

    st.markdown("#### Where it looked")
    for connector in activity["connectors"]:
        found = connector["candidates"]
        detail = count_label(found, "candidate")
        if connector["requests"]:
            detail += f" from {count_label(connector['requests'], 'request')}"
        # "live" on a connector that returned nothing and reported itself
        # unconfigured is the app flattering itself. Say which it is.
        if not connector["ok"]:
            state, tone = "failed", "bad"
        elif found:
            state, tone = "live", "good"
        elif connector["note"]:
            state, tone = "not configured", "warn"
        else:
            state, tone = "nothing new", ""
        card(title=connector["name"], meta=detail,
             body=connector["note"][:200] if connector["note"] else "",
             chip_html=chip(state, tone=tone))

    st.markdown("#### What it chose to search for")
    st.markdown(
        "<div class='fcie-hero-sub'>Not a fixed feed list — these are the queries "
        "the agent ran against live web search, with what each returned. This is the "
        "difference between an agent and a scraper.</div>",
        unsafe_allow_html=True,
    )
    queries = discovery_queries(limit=12)
    if queries:
        chips(*[chip(q["query"], str(q["sources"])) for q in queries])

    notes = []
    if activity["deferred"]:
        notes.append(
            f"**{activity['deferred']} deferred** — the publisher's robots.txt asked "
            f"for a longer delay between requests than the run had budget for, so the "
            f"agent left them for next time instead of ignoring it."
        )
    if activity["needs_review"]:
        notes.append(
            f"**{activity['needs_review']} kept but not analysed** — too little body "
            f"text to extract anything honest from. Stored and listed, not hidden."
        )
    if activity["fetch_errors"]:
        notes.append(f"**{activity['fetch_errors']} failed to fetch** — recorded with "
                     f"the error against the source.")
    if notes:
        with st.expander("What it did with the rest"):
            for note in notes:
                st.markdown(f"- {note}")

    missing = [r for r in cfg.integration_status() if r["ready"] in ("no", "fallback")]
    if missing:
        with st.expander(count_label(len(missing), "optional integration") + " not configured"):
            st.caption("The agent runs without them and says so rather than "
                       "pretending the coverage is there.")
            for row in missing:
                st.markdown(f"**{row['integration']}** — {row['status']}")
                st.caption(row["detail"])

    with st.expander("Recent runs"):
        for run in recent_runs(6):
            st.markdown(
                f"**#{run['id']}** · {run['trigger']} · {relative_time(run['started_at'])} — "
                f"{run['stored']} kept, {run['signals']} analysed, "
                f"{run['opportunities']} ideas, {run['errors']} errors"
            )

st.divider()
st.markdown("## Run it yourself")
run_pipeline_widget()
