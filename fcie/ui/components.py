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
    RECENCY_LABELS,
    recency_tier,
    count_label,
    humanize_label,
    relative_time,
    strip_inference_prefix,
    truncate_words,
)

# Deliberately plain CSS. Two rules learned the hard way:
#
#   1. Never use `prefers-color-scheme`. The app pins Streamlit's light theme in
#      .streamlit/config.toml, so on a machine set to dark mode the media query
#      fired and painted cards with a dark background while the text kept
#      Streamlit's dark ink — dark-on-dark, unreadable. Every colour below is
#      fixed and light, matching the pinned theme.
#   2. Always set colour and background together. Inheriting one from Streamlit
#      and setting the other is what caused that bug.
#
# No color-mix(), no variables, no gradients — an interviewer should read the
# screen instantly, and this has fewer ways to go wrong.
BASE_CSS = """
<style>
  .block-container {padding-top: 2rem; padding-bottom: 4rem; max-width: 1280px;}

  /* Typography: three clear levels, nothing decorative. */
  h1 {font-size: 1.8rem !important; font-weight: 700; color: #16202B;
      letter-spacing: -0.02em; margin-bottom: 0.2rem !important;}
  h2 {font-size: 1.15rem !important; font-weight: 700; color: #16202B;
      margin: 2.2rem 0 0.7rem !important;}
  h3 {font-size: 1.02rem !important; font-weight: 650; color: #16202B;
      margin-top: 1.1rem !important;}
  p, li {line-height: 1.62; color: #16202B;}

  [data-testid="stMetricValue"] {font-size: 1.9rem; font-weight: 700; color: #16202B;}
  [data-testid="stMetricLabel"] {font-size: 0.8rem; color: #5B6B7C;}

  /* #6B7A89 on #F7F9FB measured 4.17:1 — under the 4.5:1 AA floor, on the one
     block of text that must not be hard to read. #55636F measures 5.85:1. */
  .fcie-disclaimer {
    font-size: 0.74rem; color: #55636F; background: #F7F9FB;
    border-left: 3px solid #D6DEE6; border-radius: 0 6px 6px 0;
    padding: 0.5rem 0.8rem; margin: 0.6rem 0 1.4rem; line-height: 1.5;
  }

  /* Chips — one shape for all metadata. Colour AND background always set. */
  .fcie-chip {
    display: inline-block; font-size: 0.72rem; font-weight: 600; line-height: 1.35;
    padding: 0.2rem 0.55rem; border-radius: 6px; margin: 0 0.3rem 0.3rem 0;
    white-space: nowrap; background: #F0F3F7; color: #4A5866; border: 1px solid #DDE4EB;
  }
  .fcie-chip b {color: #16202B; font-weight: 700;}
  .fcie-chip--good   {background: #E8F5EE; color: #1B6E47; border-color: #BFE3D0;}
  .fcie-chip--warn   {background: #FDF3E3; color: #8A5A12; border-color: #F0DBB4;}
  .fcie-chip--bad    {background: #FCEBE9; color: #963025; border-color: #F2C9C4;}
  .fcie-chip--accent {background: #EAF1F8; color: #1F4E79; border-color: #C7DAEC;}

  /* Cards — white surface, dark text, always. */
  .fcie-card {
    border: 1px solid #E3E8ED; border-radius: 8px; background: #FFFFFF;
    padding: 0.9rem 1rem; margin-bottom: 0.7rem;
  }
  .fcie-card__title {font-size: 0.98rem; font-weight: 650; line-height: 1.4;
                     color: #16202B; margin-bottom: 0.25rem;}
  .fcie-card__title a {color: #16202B; text-decoration: none;}
  .fcie-card__title a:hover {color: #1F4E79; text-decoration: underline;}
  .fcie-card__meta {font-size: 0.76rem; color: #5B6B7C; margin-bottom: 0.5rem;}
  .fcie-card__body {font-size: 0.86rem; line-height: 1.55; color: #2C3947;
                    margin: 0.35rem 0 0.55rem;}

  /* Score bar — the number leads, the bar makes it comparable. */
  .fcie-score {display: flex; align-items: center; gap: 0.55rem; margin: 0.3rem 0;}
  .fcie-score__num {font-size: 1.1rem; font-weight: 700; color: #16202B; min-width: 2.3rem;}
  .fcie-score__track {flex: 1; height: 6px; border-radius: 999px; background: #E7ECF1;}
  .fcie-score__fill {display: block; height: 100%; border-radius: 999px; background: #1F4E79;}
  .fcie-score__label {font-size: 0.74rem; color: #5B6B7C; min-width: 5.5rem;}

  /* The one distinction that matters: quoted fact vs our interpretation. */
  .fcie-evidence {
    border-left: 3px solid #2E6DA4; background: #F2F7FC; color: #1B2733;
    padding: 0.65rem 0.85rem; margin: 0.55rem 0; font-size: 0.88rem;
    line-height: 1.6; border-radius: 0 6px 6px 0;
  }
  .fcie-inference {
    border-left: 3px solid #C08A2E; background: #FDF8EF; color: #1B2733;
    padding: 0.65rem 0.85rem; margin: 0.55rem 0; font-size: 0.88rem;
    line-height: 1.6; border-radius: 0 6px 6px 0;
  }
  .fcie-srcline {font-size: 0.73rem; color: #5B6B7C; margin-top: 0.4rem;}
  .fcie-srcline a {color: #1F4E79;}

  .fcie-muted {font-size: 0.8rem; color: #5B6B7C;}
  .fcie-lead  {font-size: 1.02rem; line-height: 1.7; color: #16202B;}

  section[data-testid="stSidebar"] .fcie-status {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 0.78rem; padding: 0.3rem 0; border-bottom: 1px solid #E3E8ED;
    color: #16202B;
  }
  section[data-testid="stSidebar"] .fcie-status span:last-child {
    color: #5B6B7C; text-align: right; margin-left: 0.5rem;
  }

  hr {margin: 1.3rem 0; border-color: #E3E8ED;}
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


def header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)
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
    """A number plus a proportional bar, so scores are comparable at a glance."""
    value = float(score or 0)
    pct = max(0.0, min(100.0, value / maximum * 100.0))
    colour = {
        "good": "var(--fcie-good)", "warn": "var(--fcie-warn)",
        "bad": "var(--fcie-bad)", None: "var(--fcie-accent)",
    }.get(tone, "var(--fcie-accent)")
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


RECENCY_TONE = {"new": "good", "recent": "", "evergreen": "warn", "undated": "warn"}


def recency_chip(published_at, discovered_at=None) -> str:
    """State plainly whether a source is news, background, or undated."""
    tier, label = recency_tier(published_at, discovered_at)
    return chip(RECENCY_LABELS[tier], tone=RECENCY_TONE.get(tier, ""))


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
        chip_html=(
            score_bar(signal.get("score"), "opportunity")
            + recency_chip(signal.get("published_at"), signal.get("discovered_at"))
            + chip("evidence", f"{signal.get('evidence_strength') or 0:.0f}/10")
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
