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
from ..config import load_config
from ..db import describe_backend

BASE_CSS = """
<style>
  .block-container {padding-top: 2.2rem; max-width: 1400px;}
  h1 {font-size: 1.65rem !important; font-weight: 620; letter-spacing: -0.01em;}
  h2 {font-size: 1.2rem !important; font-weight: 600; margin-top: 1.4rem;}
  h3 {font-size: 1.02rem !important; font-weight: 600;}
  [data-testid="stMetricValue"] {font-size: 1.55rem; font-weight: 600;}
  [data-testid="stMetricLabel"] {font-size: 0.78rem; opacity: 0.72;}
  .fcie-disclaimer {
    font-size: 0.76rem; opacity: 0.7; border-left: 2px solid rgba(128,128,128,0.35);
    padding: 0.35rem 0 0.35rem 0.7rem; margin: 0.4rem 0 1.1rem 0; line-height: 1.45;
  }
  .fcie-tag {
    display: inline-block; font-size: 0.68rem; padding: 0.09rem 0.44rem;
    border-radius: 3px; border: 1px solid rgba(128,128,128,0.4);
    margin-right: 0.3rem; opacity: 0.88; white-space: nowrap;
  }
  .fcie-evidence {
    border-left: 2px solid rgba(90,140,200,0.65); padding: 0.4rem 0 0.4rem 0.75rem;
    margin: 0.45rem 0; font-size: 0.87rem; line-height: 1.5;
  }
  .fcie-inference {
    border-left: 2px solid rgba(200,150,60,0.7); padding: 0.4rem 0 0.4rem 0.75rem;
    margin: 0.45rem 0; font-size: 0.87rem; line-height: 1.5;
  }
  .fcie-muted {font-size: 0.79rem; opacity: 0.66;}
  hr {margin: 1.1rem 0; opacity: 0.25;}
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


def page_setup(title: str, icon: str = "◆") -> None:
    st.set_page_config(page_title=f"{title} · FCIE", page_icon=icon, layout="wide")
    st.markdown(BASE_CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    st.markdown(f'<div class="fcie-disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)


def sidebar_status() -> None:
    cfg = load_config()
    with st.sidebar:
        st.markdown("### Founder Content\nIntelligence Engine")
        st.caption(f"v{__version__} · independent prototype")
        st.divider()
        st.markdown("**System status**")
        for row in cfg.integration_status():
            icon = {"yes": "🟢", "fallback": "🟡", "no": "⚪"}.get(row["ready"], "⚪")
            st.markdown(
                f"{icon} **{row['integration']}**  \n"
                f"<span class='fcie-muted'>{row['status']}</span>",
                unsafe_allow_html=True,
            )
        st.divider()
        st.caption(describe_backend())
        st.caption(
            "Nothing is published automatically. Every draft requires human approval."
        )


def risk_badge(band_or_score) -> str:
    if isinstance(band_or_score, (int, float)):
        score = float(band_or_score)
        band = "Low" if score <= 24 else "Moderate" if score <= 49 else "Elevated" if score <= 74 else "High"
    else:
        band = str(band_or_score)
    return RISK_BADGES.get(band, band)


def trend_badge(status: str | None) -> str:
    return TREND_BADGES.get(status or "", status or "—")


def tag(text: str) -> str:
    return f'<span class="fcie-tag">{text}</span>'


def method_tag(method: str | None) -> str:
    if not method:
        return tag("no analysis")
    if method in ("heuristic", "heuristic-v1"):
        return tag("heuristic analyser")
    return tag(f"LLM · {method}")


def evidence_block(passage: str, source_id=None, url: str | None = None,
                   domain: str | None = None) -> None:
    """Verbatim source material — visually distinct from interpretation."""
    attribution = ""
    if source_id is not None:
        attribution = f"source #{source_id}"
        if domain:
            attribution += f" · {domain}"
    link = f' · <a href="{url}" target="_blank">open source</a>' if url else ""
    st.markdown(
        f'<div class="fcie-evidence">“{passage}”<br>'
        f'<span class="fcie-muted">{attribution}{link}</span></div>',
        unsafe_allow_html=True,
    )


def inference_block(text: str, label: str = "AI interpretation — not a source claim") -> None:
    st.markdown(
        f'<div class="fcie-inference"><span class="fcie-muted">{label}</span><br>{text}</div>',
        unsafe_allow_html=True,
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
    with st.expander("▶︎ Run discovery", expanded=False):
        st.caption(
            "Fetches public sources, extracts structured signals, recomputes themes and "
            "regenerates opportunity briefs. Crawling respects robots.txt and is rate-limited."
        )
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
