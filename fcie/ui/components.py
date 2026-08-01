"""Shared Streamlit components.

Restrained visual language: no animation, no gradients, no fake metrics. Every
number shown is computed from the database, and provenance (LLM vs heuristic) is
always visible.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from .. import DISCLAIMER, __version__
from ..config import is_admin, load_config, read_only_notice
from ..db import describe_backend
from ..utils.format import (
    recency_tier,
    count_label,
    humanize_label,
    relative_time,
    strip_inference_prefix,
    truncate_words,
)

# Palette taken from Podium's own published design tokens (the `--token-*` custom
# properties on podium.com): the #18181C near-black spine, the periwinkle blue
# ramp, the sage/olive secondary, and their warm and red ramps. Read off the live
# stylesheet rather than eyeballed, so the app looks like it belongs in front of
# this particular company. It deliberately borrows no logo, wordmark or layout —
# the disclaimer at the top of every page says whose project this is.
#
# Two rules learned the hard way and enforced by tests:
#
#   1. Never use `prefers-color-scheme`. The app pins Streamlit's light theme in
#      .streamlit/config.toml, so on a machine set to dark mode the media query
#      fired and painted cards with a dark background while the text kept
#      Streamlit's dark ink — dark-on-dark, unreadable. Every colour below is
#      fixed and light, matching the pinned theme.
#   2. Always set colour and background together. Inheriting one from Streamlit
#      and setting the other is what caused that bug.
#
# No color-mix(), no variables, no gradients. Every text/background pair here is
# asserted against the 4.5:1 WCAG AA floor in tests/test_database.py; the worst
# pair measures 5.54:1. If you change a colour, change the test.
BASE_CSS = """
<style>
  /* Typeface is set in .streamlit/config.toml, not here — Streamlit's own font
     rules outrank a stylesheet appended to the page, so a font-family declared
     in this file silently loses to Source Sans on every element it styles. */

  .block-container {padding-top: 3rem; padding-bottom: 6rem; max-width: 1100px;}

  /* Type scale borrowed from product-marketing pages rather than dashboards:
     one confident headline, a readable sub, and body text at a size meant for
     reading. Sections are separated by whitespace, not boxes — the previous
     version drew a border around almost everything and the eye had nowhere to
     rest. */
  h1 {font-size: 2.9rem !important; font-weight: 700; color: #18181C;
      letter-spacing: -0.035em; line-height: 1.1;
      margin: 0 0 0.5rem !important;}
  h2 {font-size: 1.6rem !important; font-weight: 700; color: #18181C;
      letter-spacing: -0.02em; line-height: 1.25;
      margin: 3.4rem 0 1rem !important;}
  h3 {font-size: 1.15rem !important; font-weight: 650; color: #18181C;
      letter-spacing: -0.01em; margin: 1.4rem 0 0.4rem !important;}
  p, li {font-size: 1.02rem; line-height: 1.75; color: #18181C;}
  a {color: #38549C;}

  /* The standfirst under a page title: what this page is for, in one line. */
  .fcie-hero-sub {
    font-size: 1.05rem; line-height: 1.7; color: #4A4A4D;
    max-width: 44rem; margin: 0 0 0.4rem;
  }

  /* "How it works" — four numbered steps, so a first-time visitor knows what
     the app did before they are shown what it found. Without this the page
     opened straight into counts of things nobody had defined yet. */
  .fcie-steps {
    display: flex; gap: 1.6rem; flex-wrap: wrap;
    margin: 0.4rem 0 0.2rem; padding: 0;
  }
  .fcie-step {
    flex: 1 1 12rem; min-width: 11rem;
    border-top: 2px solid #E8E8ED; padding-top: 0.7rem;
  }
  .fcie-step__n {
    display: inline-block; font-size: 0.72rem; font-weight: 700;
    color: #4565B6; background: #E0E9FC; border-radius: 999px;
    width: 1.35rem; height: 1.35rem; line-height: 1.35rem; text-align: center;
    margin-bottom: 0.35rem;
  }
  .fcie-step__t {
    font-size: 0.98rem; font-weight: 650; color: #18181C; margin-bottom: 0.2rem;
  }
  .fcie-step__d {font-size: 0.86rem; line-height: 1.6; color: #4A4A4D;}

  /* A single quiet fact, set apart. Used for the "why you need it" line. */
  .fcie-pull {
    border-top: 1px solid #E8E8ED; border-bottom: 1px solid #E8E8ED;
    padding: 1.5rem 0; margin: 2.2rem 0;
    font-size: 1.2rem; line-height: 1.6; color: #18181C; font-weight: 500;
    letter-spacing: -0.01em; max-width: 46rem;
  }
  .fcie-pull b {font-weight: 700;}

  [data-testid="stMetricValue"] {font-size: 2rem; font-weight: 700; color: #18181C;}
  [data-testid="stMetricLabel"] {font-size: 0.82rem; color: #626265; font-weight: 600;}

  .fcie-disclaimer {
    font-size: 0.76rem; color: #4A4A4D; background: #F4F4F7;
    border-left: 3px solid #DCDCE1; border-radius: 0 8px 8px 0;
    padding: 0.55rem 0.85rem; margin: 0.6rem 0 1.5rem; line-height: 1.55;
  }

  /* Chips — one shape for all metadata. Colour AND background always set.
     Pill-shaped, matching Podium's 50px button radius. */
  .fcie-chip {
    display: inline-block; font-size: 0.74rem; font-weight: 600; line-height: 1.4;
    padding: 0.22rem 0.62rem; border-radius: 999px; margin: 0 0.35rem 0.35rem 0;
    white-space: nowrap; background: #F4F4F7; color: #4A4A4D; border: 1px solid #E8E8ED;
  }
  .fcie-chip b {color: #18181C; font-weight: 700;}
  .fcie-chip--good   {background: #F3F4EF; color: #434832; border-color: #CDD1BF;}
  .fcie-chip--warn   {background: #F9F4EB; color: #5C4F3A; border-color: #EEE0CA;}
  .fcie-chip--bad    {background: #F0DCDC; color: #862525; border-color: #D2A1A1;}
  .fcie-chip--accent {background: #E0E9FC; color: #38549C; border-color: #C2D2F9;}

  /* Cards — white surface, dark text, always. */
  .fcie-card {
    border: 1px solid #E8E8ED; border-radius: 10px; background: #FFFFFF;
    padding: 1rem 1.1rem; margin-bottom: 0.75rem;
  }
  .fcie-card__title {font-size: 1rem; font-weight: 650; line-height: 1.45;
                     color: #18181C; margin-bottom: 0.3rem;}
  .fcie-card__title a {color: #18181C; text-decoration: none;}
  .fcie-card__title a:hover {color: #38549C; text-decoration: underline;}
  .fcie-card__meta {font-size: 0.79rem; color: #626265; margin-bottom: 0.55rem;}
  .fcie-card__body {font-size: 0.92rem; line-height: 1.62; color: #4A4A4D;
                    margin: 0.4rem 0 0.6rem;}

  /* Score bar — the number leads, the bar makes it comparable. */
  .fcie-score {display: flex; align-items: center; gap: 0.6rem; margin: 0.35rem 0;}
  .fcie-score__num {font-size: 1.15rem; font-weight: 700; color: #18181C; min-width: 2.4rem;}
  .fcie-score__track {flex: 1; height: 7px; border-radius: 999px; background: #E8E8ED;}
  .fcie-score__fill {display: block; height: 100%; border-radius: 999px; background: #4565B6;}
  .fcie-score__label {font-size: 0.76rem; color: #626265; min-width: 5.5rem;}

  /* The one distinction that matters: quoted fact vs our interpretation.
     Blue rule = something a source actually said. Warm rule = our reading of
     it. Two of Podium's own ramps, doing one job each. */
  .fcie-evidence {
    border-left: 3px solid #4565B6; background: #F5F8FF; color: #18181C;
    padding: 0.7rem 0.9rem; margin: 0.6rem 0; font-size: 0.94rem;
    line-height: 1.65; border-radius: 0 8px 8px 0;
  }
  .fcie-inference {
    border-left: 3px solid #CF9D4E; background: #FCFAF5; color: #18181C;
    padding: 0.7rem 0.9rem; margin: 0.6rem 0; font-size: 0.94rem;
    line-height: 1.65; border-radius: 0 8px 8px 0;
  }
  .fcie-srcline {font-size: 0.76rem; color: #626265; margin-top: 0.45rem;}
  .fcie-srcline a {color: #38549C;}

  .fcie-muted {font-size: 0.85rem; color: #626265;}
  .fcie-lead  {font-size: 1.1rem; line-height: 1.75; color: #18181C;}

  section[data-testid="stSidebar"] .fcie-status {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 0.8rem; padding: 0.32rem 0; border-bottom: 1px solid #E8E8ED;
    color: #18181C;
  }
  section[data-testid="stSidebar"] .fcie-status span:last-child {
    color: #626265; text-align: right; margin-left: 0.5rem;
  }

  hr {margin: 1.4rem 0; border-color: #E8E8ED;}

  /* Primary buttons. Streamlit paints the fill from theme.primaryColor but takes
     the label from theme.textColor, so it put #18181C ink on the blue fill —
     3.19:1. It does not pick a readable label for you, and darkening the fill
     makes it worse rather than flipping the text to white. Both values set here,
     which is rule 2 at the top of this file. The label sits in a nested <p> that
     inherits Streamlit's colour, so it needs saying twice. */
  button[data-testid="stBaseButton-primary"],
  button[data-testid="stBaseButton-primary"] p {
    background: #4565B6; color: #FFFFFF; border-color: #4565B6;
  }
  button[data-testid="stBaseButton-primary"]:hover,
  button[data-testid="stBaseButton-primary"]:hover p {
    background: #38549C; color: #FFFFFF; border-color: #38549C;
  }

  /* Streamlit labels the entry-point page in the sidebar from its filename, so
     the first nav item reads "streamlit app" — the first thing anyone sees.
     There is no config for it: the supported fix is st.navigation(), which
     requires the pages/ directory to be renamed and the entry point rewritten
     as a router, and Streamlit Cloud's configured main file is streamlit_app.py.
     This relabels the visible text only: the link's accessible name stays
     "streamlit app", which is what it already was, so this is no worse for a
     screen reader — just not a fix for one. If Streamlit changes its markup the
     selector stops matching and the original label returns; it cannot break
     routing either way. Renaming the entry file is the real fix, and needs the
     main-file path changed in Streamlit Cloud's settings at the same time. */
  [data-testid="stSidebarNav"] li:first-child a p {
    visibility: hidden; position: relative;
  }
  [data-testid="stSidebarNav"] li:first-child a p::after {
    content: "Dashboard"; visibility: visible;
    position: absolute; left: 0; top: 0; white-space: nowrap;
  }

  /* Sidebar nav: a little more room between items than the default. */
  [data-testid="stSidebarNav"] li {margin-bottom: 0.1rem;}
</style>
"""

TREND_BADGES = {
    "emerging": "🟢 Emerging",
    "rising": "🔺 Rising",
    "stable": "⬜ Stable",
    "declining": "🔻 Declining",
    "saturated": "⬛ Saturated",
    "low_confidence": "⚠️ Low confidence",
}

RISK_BADGES = {"Low": "🟢 Low", "Moderate": "🟡 Moderate",
               "Elevated": "🟠 Elevated", "High": "🔴 High"}

STATUS_LABELS = {
    "new": "New", "research_needed": "Research needed", "ready_for_brief": "Ready for brief",
    "drafting": "Drafting", "review": "Review", "approved": "Approved", "archived": "Archived",
}


def admin() -> bool:
    """Whether write controls should render. See ``config.is_admin``."""
    return is_admin()


def admin_only(render, *, note: str | None = None):
    """Render a mutating control only for an admin.

    Every Delete / Reprocess / Approve / Update-status control routes through
    this, so "is this safe to expose publicly?" has exactly one answer in one
    place rather than being re-decided at each call site.
    """
    if admin():
        return render()
    if note:
        st.caption(f"🔒 {note}")
    return None


def read_only_banner() -> None:
    if not admin():
        st.caption(f"🔒 {read_only_notice()}")


def page_setup(title: str, icon: str = "◆") -> None:
    st.set_page_config(page_title=f"{title} · FCIE", page_icon=icon, layout="wide")
    st.markdown(BASE_CSS, unsafe_allow_html=True)


def how_it_works(steps: list[tuple[str, str]]) -> None:
    """Numbered steps explaining what the page did before showing what it found.

    Every page in this app reported counts of things — signals, themes,
    opportunities — that are only meaningful once you know the pipeline that
    produced them. A first-time reader had to infer the process from the
    results. This states it.
    """
    cells = "".join(
        f"<div class='fcie-step'>"
        f"<span class='fcie-step__n'>{index}</span>"
        f"<div class='fcie-step__t'>{title}</div>"
        f"<div class='fcie-step__d'>{detail}</div>"
        f"</div>"
        for index, (title, detail) in enumerate(steps, start=1)
    )
    st.markdown(f"<div class='fcie-steps'>{cells}</div>", unsafe_allow_html=True)


def header(title: str, subtitle: str = "") -> None:
    """Page title and its one-line purpose.

    The subtitle used to render as ``st.caption`` — 0.8rem grey, the same
    treatment as a footnote. It is the sentence that tells a first-time reader
    what the page is *for*, so it is now set as a proper standfirst under the
    heading and given room to breathe.
    """
    st.title(title)
    if subtitle:
        st.markdown(f"<div class='fcie-hero-sub'>{subtitle}</div>",
                    unsafe_allow_html=True)
    st.markdown(f'<div class="fcie-disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)


# Long config labels compressed to something scannable in a narrow sidebar.
_STATUS_SHORT = {
    "Database": "Database",
    "OpenAI (extraction, briefs, drafts)": "AI analysis",
    "Web search": "Web search",
    "YouTube": "YouTube",
    "RSS feeds": "RSS feeds",
    "Podium first-party crawl": "Podium crawl",
}


def sidebar_status() -> None:
    """Sidebar for a reader, not an operator.

    This used to carry the Supabase hostname, a "4/6 live" connection tally,
    per-integration fallback notes, environment-variable instructions and a
    repo path. None of that answers the executive's question — *what should I
    look at today, why does it matter, what could I say?* — and all of it
    competes with the answer. The technical detail now lives on Settings, one
    click away, for whoever asks how it was built.
    """
    with st.sidebar:
        st.markdown("### Founder Content Intelligence")
        st.caption("Public signals → evidence-linked founder content")
        st.divider()
        st.caption(
            "**Nothing is published automatically.** Every draft needs a human "
            "decision."
        )
        if not is_admin():
            st.caption("🔒 Read-only demo")


def risk_band(score) -> str:
    score = float(score or 0)
    return ("Low" if score <= 24 else "Moderate" if score <= 49
            else "Elevated" if score <= 74 else "High")


def risk_badge(band_or_score) -> str:
    band = risk_band(band_or_score) if isinstance(band_or_score, (int, float)) else str(band_or_score)
    return RISK_BADGES.get(band, band)


def trend_badge(status: str | None) -> str:
    return TREND_BADGES.get(status or "", humanize_label(status))


def chip(label: str, value: str | None = None, tone: str = "") -> str:
    """One consistent metadata shape. ``tone``: good | warn | bad | accent."""
    css = f" fcie-chip--{tone}" if tone else ""
    inner = f"{label} <b>{value}</b>" if value else label
    return f'<span class="fcie-chip{css}">{inner}</span>'


def chips(*items: str) -> None:
    st.markdown("".join(i for i in items if i), unsafe_allow_html=True)


def tag(text: str) -> str:          # kept for callers that just want a plain chip
    return chip(text)


def method_chip(method: str | None, model: str | None = None) -> str:
    """Which analyser produced a row — always visible, never ambiguous."""
    if not method:
        return chip("not analysed")
    if method in ("heuristic", "heuristic-v1"):
        return chip("analysed by", "rules", tone="")
    return chip("analysed by", model or "LLM", tone="accent")


def score_bar(score: float | None, label: str = "opportunity",
              maximum: float = 100.0, tone: str | None = None) -> str:
    """A number plus a proportional bar, so scores are comparable at a glance.

    These used to emit ``background: var(--fcie-accent)``. The stylesheet
    defines no custom properties — that was the point of removing them — so the
    variable resolved to nothing and every bar in the app rendered as an empty
    grey track. Literal hex, matching BASE_CSS.
    """
    value = float(score or 0)
    pct = max(0.0, min(100.0, value / maximum * 100.0))
    colour = {
        "good": "#5D6345",    # sage
        "warn": "#CF9D4E",    # warm
        "bad": "#A54848",     # red
    }.get(tone or "", "#4565B6")  # periwinkle — Podium's primary
    return (
        f'<div class="fcie-score">'
        f'<span class="fcie-score__num">{value:.0f}</span>'
        f'<span class="fcie-score__track">'
        f'<span class="fcie-score__fill" style="width:{pct:.0f}%;background:{colour}"></span>'
        f'</span>'
        f'<span class="fcie-score__label">{label}</span>'
        f'</div>'
    )


def risk_chip(score) -> str:
    band = risk_band(score)
    tone = {"Low": "good", "Moderate": "warn", "Elevated": "warn", "High": "bad"}[band]
    return chip("risk", f"{band.lower()} · {float(score or 0):.0f}", tone=tone)


def evidence_block(passage: str, source_id=None, url: str | None = None,
                   domain: str | None = None) -> None:
    """Verbatim source material — visually distinct from interpretation."""
    bits = []
    if source_id is not None:
        bits.append(f"source #{source_id}")
    if domain:
        bits.append(domain)
    line = " · ".join(bits)
    if url:
        line += f' · <a href="{url}" target="_blank">open original ↗</a>'
    st.markdown(
        f'<div class="fcie-evidence">“{passage}”'
        f'<div class="fcie-srcline">{line}</div></div>',
        unsafe_allow_html=True,
    )


def inference_block(text: str, label: str = "Interpretation — not a source claim") -> None:
    st.markdown(
        f'<div class="fcie-inference">'
        f'<div class="fcie-srcline" style="margin:0 0 .3rem">{label}</div>'
        f'{strip_inference_prefix(text)}</div>',
        unsafe_allow_html=True,
    )


def card(title: str, meta: str = "", body: str = "", url: str | None = None,
         chip_html: str = "") -> None:
    """A bounded unit so list items stop bleeding into one another."""
    heading = f'<a href="{url}" target="_blank">{title}</a>' if url else title
    st.markdown(
        f'<div class="fcie-card">'
        f'<div class="fcie-card__title">{heading}</div>'
        + (f'<div class="fcie-card__meta">{meta}</div>' if meta else "")
        + (f'<div class="fcie-card__body">{body}</div>' if body else "")
        + (chip_html or "")
        + "</div>",
        unsafe_allow_html=True,
    )


def signal_card(signal: dict) -> None:
    """One ranked source. Replaces four stacked st.metric columns."""
    _tier, recency_label = recency_tier(signal.get("published_at"),
                                        signal.get("discovered_at"))
    theme = signal.get("theme") or "unclassified"
    meta = f"{signal.get('domain','')} · {recency_label} · {theme}"
    body = ""
    if signal.get("problem"):
        body = f"<b>Problem in source:</b> {truncate_words(signal['problem'], 34)}"
    card(
        title=truncate_words(signal.get("title") or "(untitled)", 18),
        meta=meta, body=body, url=signal.get("url"),
        # Three chips, not five. The recency chip repeated what the meta line
        # already says, and evidence strength is on the source's own page — five
        # pills per row across five cards is a wall, not a summary. The method
        # chip stays: provenance is always visible, by design.
        chip_html=(
            score_bar(signal.get("score"), "opportunity")
            + risk_chip(signal.get("risk"))
            + method_chip(signal.get("extraction_method"))
        ),
    )


def score_breakdown_table(breakdown: dict) -> None:
    components = (breakdown or {}).get("components", [])
    if not components:
        st.caption("No score breakdown recorded.")
        return
    frame = pd.DataFrame(components)[
        ["label", "raw_0_10", "weight_pct", "points", "max_points"]
    ].rename(columns={
        "label": "Component", "raw_0_10": "Raw (0-10)", "weight_pct": "Weight",
        "points": "Points", "max_points": "Max",
    })
    st.dataframe(frame, hide_index=True, width="stretch")
    st.caption(breakdown.get("formula", ""))
    for note in (breakdown.get("notes") or [])[:6]:
        st.caption(f"· {note}")


def risk_breakdown_table(breakdown: dict) -> None:
    factors = (breakdown or {}).get("factors", [])
    if not factors:
        st.caption("No risk factors detected.")
        return
    frame = pd.DataFrame(factors)[["label", "points", "reason"]].rename(
        columns={"label": "Risk factor", "points": "Points", "reason": "Why it fired"}
    )
    st.dataframe(frame, hide_index=True, width="stretch")


def format_date(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "no date"
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    return str(value)


def empty_state(message: str, action: str = "") -> None:
    st.info(message + (f"\n\n**Next step:** {action}" if action else ""))


def setup_warnings(messages: list[str]) -> None:
    if not messages:
        return
    with st.expander(f"⚙️ {len(messages)} integration(s) not configured — click for setup steps"):
        for message in messages:
            st.markdown(f"- {message}")


def run_pipeline_widget(key_prefix: str = "run") -> None:
    """The 'Run discovery' control used on the Executive Dashboard."""
    from ..pipeline.run import run_full_pipeline

    cfg = load_config()
    if not admin():
        # A public visitor must not be able to start a crawl against third-party
        # sites from someone else's deployment, nor rewrite the demo database.
        st.caption(f"🔒 {read_only_notice()}")
        return
    with st.expander("▶︎ Run discovery", expanded=False):
        st.caption(
            "Fetches public sources, extracts structured signals, recomputes themes and "
            "regenerates opportunity briefs. Crawling respects robots.txt and is rate-limited "
            "per domain; unrelated hosts are fetched concurrently."
        )
        mode = st.radio(
            "Run size",
            ["Quick demo (~25 sources, ≈2 min)", "Standard run"],
            horizontal=True,
            key=f"{key_prefix}_mode",
        )
        quick = mode.startswith("Quick")

        col1, col2 = st.columns(2)
        with col1:
            podium = st.checkbox("Podium public pages", value=True, key=f"{key_prefix}_podium")
            rss = st.checkbox(f"RSS feeds ({len(cfg.enabled_feeds)})", value=True, key=f"{key_prefix}_rss")
        with col2:
            search = st.checkbox(
                f"Web search ({cfg.credentials.search_provider or 'not configured'})",
                value=bool(cfg.credentials.search_provider),
                disabled=not cfg.credentials.search_provider,
                key=f"{key_prefix}_search",
            )
            youtube = st.checkbox("YouTube", value=True, key=f"{key_prefix}_yt")

        if quick:
            max_sources = 25
        else:
            max_sources = st.slider(
                "Max new sources this run", 10, 200, cfg.crawl.max_sources_per_run, step=10,
                key=f"{key_prefix}_max",
            )
        heuristic = st.checkbox(
            "Force heuristic analyser (skip the LLM)",
            value=not cfg.credentials.has_openai,
            disabled=not cfg.credentials.has_openai,
            key=f"{key_prefix}_heur",
            help="Runs the deterministic backend even when an OpenAI key is present.",
        )

        if st.button("Run discovery", type="primary", key=f"{key_prefix}_go"):
            log_area = st.empty()
            lines: list[str] = []

            def progress(message: str) -> None:
                lines.append(message)
                log_area.code("\n".join(lines[-14:]), language=None)

            with st.spinner("Running the pipeline — this can take a few minutes…"):
                result = run_full_pipeline(
                    trigger="dashboard", include_podium=podium, include_rss=rss,
                    include_search=search, include_youtube=youtube,
                    max_sources=max_sources, force_heuristic=heuristic,
                    progress=progress,
                )
            st.success(f"Finished in {result.duration_seconds}s — {result.summary_line()}")
            if result.setup_messages:
                setup_warnings(result.setup_messages)
            if result.errors:
                with st.expander(f"{len(result.errors)} non-fatal error(s)"):
                    for error in result.errors[:30]:
                        st.text(error)
            st.cache_data.clear()
