"""Social Media — public posts and discussions worth a reply.

Social only: LinkedIn, X and Reddit. Industry articles and company pages arrive
through the other channels and are summarised in the Daily Brief. Mixing them in
here would blur the one thing this page is for, which is finding a conversation
with a person in it.

Surfaces and stops. Nothing here comments, likes, reposts, follows, connects or
messages, and there is no control on this page that could. It produces a queue;
a person reads it and decides.
"""

from __future__ import annotations

import streamlit as st

from fcie.config import load_config
from fcie.db import init_db
from fcie.queries import social_post_stats, watchlist_items
from fcie.ui.components import (
    chip,
    empty_state,
    header,
    how_it_works,
    page_setup,
    sidebar_status,
)
from fcie.utils.format import count_label, relative_time

# host fragment -> (label, how the post was obtained)
PLATFORMS = {
    "linkedin.com": ("LinkedIn", "public post, located through web search"),
    "x.com": ("X", "public post, located through web search"),
    "twitter.com": ("X", "public post, located through web search"),
    "reddit.com": ("Reddit", "via Reddit's official Data API"),
}

PRIORITY_TONE = {"high": "bad", "medium": "warn", "low": ""}


def platform_of(url: str | None) -> tuple[str, str] | None:
    for host, meta in PLATFORMS.items():
        if host in (url or "").lower():
            return meta
    return None


page_setup("Social Media", "💬")
init_db()
sidebar_status()
header(
    "Social Media",
    "Public posts where a reply from you would add something. The system finds "
    "them and stops — it never comments, likes, reposts, follows or messages.",
)

how_it_works([
    ("Finds public posts",
     "LinkedIn and X through the public search index, Reddit through its official "
     "API. The platforms are never crawled, logged into, or contacted directly."),
    ("Drops what is not a conversation",
     "Profiles, company pages, product listings and job ads are destinations, not "
     "discussions. Neither is a post too old to reply to."),
    ("Drops vendor marketing",
     "Most public posts on these topics are competitors selling the same thing. "
     "Replying to a rival's lead-generation post reads as a spat, not insight."),
    ("Suggests an angle",
     "What was said, how it connects, and a line worth taking that is not a pitch. "
     "You open the original and write it yourself."),
])

# ── channel health, stated plainly ──────────────────────────────────────────
cfg = load_config()
stats = social_post_stats()

st.markdown("## Channels")
c1, c2, c3 = st.columns(3)
c1.metric("LinkedIn", stats["by_platform"].get("LinkedIn", 0),
          help="Public posts in the library, found through the search index.")
c1.caption("Public search index")
c2.metric("X", stats["by_platform"].get("X", 0),
          help="Public posts in the library, found through the search index.")
c2.caption("Public search index")
c3.metric("Reddit", stats["by_platform"].get("Reddit", 0),
          help="Needs REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET — free "
               "application credentials, not an account login.")
c3.caption("Official API" if cfg.credentials.has_reddit_api else "Not connected")

if not cfg.credentials.has_reddit_api:
    st.info(
        "**Reddit is not connected, and it is the channel that would carry this "
        "page.** LinkedIn and X are broadcast platforms: their public posts on "
        "these topics are overwhelmingly vendors marketing at each other, which "
        "the filter below correctly rejects. Reddit is where owners describe the "
        "problem in their own words while asking for help — the one context where "
        "a reply is welcome rather than an intrusion. Register a *script* app at "
        "reddit.com/prefs/apps (free, about two minutes) and set "
        "`REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`.",
        icon="🔌",
    )

if stats["analysed"]:
    st.caption(
        f"{count_label(stats['analysed'], 'social post')} analysed · "
        f"{stats['rejected_vendor']} rejected as vendor marketing · "
        f"{stats['rejected_relevance']} as off-topic. That filtering is the point: "
        f"a short queue you would act on beats a long one you scroll past."
    )

st.divider()

# ── the queue: social only ──────────────────────────────────────────────────
items = [i for i in watchlist_items() if platform_of(i["url"])]

if not items:
    empty_state(
        "No social conversations in the queue right now.",
        "Every candidate was vendor marketing, off-topic, or too old to reply to. "
        "Connecting Reddit is the fastest way to fill this.",
    )
    st.stop()

st.markdown(f"## {count_label(len(items), 'conversation')} worth a reply")

f1, f2 = st.columns(2)
platform_filter = f1.multiselect(
    "Platform", sorted({platform_of(i["url"])[0] for i in items}))
priority_filter = f2.multiselect("Priority", ["high", "medium", "low"])

shown = [
    i for i in items
    if (not platform_filter or platform_of(i["url"])[0] in platform_filter)
    and (not priority_filter or i["priority"] in priority_filter)
]
if not shown:
    empty_state("Nothing matches these filters.", "Clear them to see the queue.")
    st.stop()

for item in shown:
    label, provenance = platform_of(item["url"])
    with st.container(border=True):
        head, meta = st.columns([3, 1])
        head.markdown(f"### {item['person_or_company']}")
        meta.markdown(
            chip(label, tone="accent")
            + chip(item["priority"], tone=PRIORITY_TONE.get(item["priority"], "")),
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='fcie-muted'>{item['topic']} · found "
            f"{relative_time(item['discovered_at'])} · {provenance}</div>",
            unsafe_allow_html=True,
        )

        if item.get("recent_signal"):
            st.markdown("**What they said**")
            st.markdown(f"<div class='fcie-evidence'>{item['recent_signal']}</div>",
                        unsafe_allow_html=True)

        left, right = st.columns(2)
        with left:
            if item.get("why_relevant"):
                st.markdown("**Why it is worth your time**")
                st.caption(item["why_relevant"])
        with right:
            if item.get("podium_connection"):
                st.markdown("**How it connects**")
                st.caption(item["podium_connection"])

        if item.get("suggested_response_angle"):
            st.markdown("**An angle worth taking**")
            st.markdown(
                f"<div class='fcie-inference'>{item['suggested_response_angle']}</div>",
                unsafe_allow_html=True,
            )

        if item.get("url"):
            st.markdown(f"[Open the original post →]({item['url']})")
        if item.get("risk_notes"):
            st.caption(f"⚠️ {item['risk_notes']}")

st.divider()
st.caption(
    "LinkedIn and X posts are located through public web search and stored as "
    "what the search index already publishes — those platforms are never crawled, "
    "logged into, or contacted. Reddit uses its official API with application "
    "credentials. No interaction of any kind is ever automated."
)
