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
from ..utils.format import (
    count_label,
    humanize_label,
    relative_time,
    strip_inference_prefix,
    truncate_words,
)

BASE_CSS = """
<style>
  /* ── Design tokens ──────────────────────────────────────────────────── */
  :root {
    --fcie-ink:      #16202B;
    --fcie-muted:    #5B6B7C;
    --fcie-line:     #E3E8ED;
    --fcie-surface:  #FFFFFF;
    --fcie-raised:   #F7F9FB;
    --fcie-accent:   #1F4E79;
    --fcie-evidence: #2E6DA4;   /* facts, quoted from a source  */
    --fcie-infer:    #B4761F;   /* interpretation, not a finding */
    --fcie-good:     #1E7B4F;
    --fcie-warn:     #B4761F;
    --fcie-bad:      #B03A2E;
    --fcie-radius:   8px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --fcie-ink: #E8EDF2; --fcie-muted: #93A3B4; --fcie-line: #2A3541;
      --fcie-surface: #0E1620; --fcie-raised: #16202B;
      --fcie-evidence: #6FA8DC; --fcie-infer: #D9A441;
      --fcie-good: #4CAF7D; --fcie-warn: #D9A441; --fcie-bad: #E06B5D;
    }
  }

  .block-container {padding-top: 2rem; padding-bottom: 4rem; max-width: 1360px;}

  /* ── Typography: a real hierarchy instead of four similar sizes ─────── */
  h1 {font-size: 1.75rem !important; font-weight: 680; letter-spacing: -0.02em;
      margin-bottom: 0.15rem !important;}
  h2 {font-size: 1.08rem !important; font-weight: 640; letter-spacing: -0.005em;
      margin: 2rem 0 0.6rem !important; text-transform: uppercase;
      font-variant: small-caps; color: var(--fcie-muted);}
  h3 {font-size: 1.06rem !important; font-weight: 620; margin-top: 1.1rem !important;}
  h4 {font-size: 0.9rem !important; font-weight: 620; color: var(--fcie-muted);}
  p, li {line-height: 1.62;}

  [data-testid="stMetricValue"] {font-size: 1.7rem; font-weight: 660;
      letter-spacing: -0.02em;}
  [data-testid="stMetricLabel"] {font-size: 0.72rem; letter-spacing: 0.04em;
      text-transform: uppercase; color: var(--fcie-muted);}

  /* ── Disclaimer: present but never shouting ─────────────────────────── */
  .fcie-disclaimer {
    font-size: 0.74rem; color: var(--fcie-muted);
    border-left: 2px solid var(--fcie-line);
    padding: 0.3rem 0 0.3rem 0.7rem; margin: 0.5rem 0 1.4rem; line-height: 1.5;
  }

  /* ── Chips: one consistent shape for every piece of metadata ────────── */
  .fcie-chip {
    display: inline-flex; align-items: center; gap: 0.28rem;
    font-size: 0.7rem; font-weight: 550; line-height: 1;
    padding: 0.24rem 0.5rem; border-radius: 999px;
    border: 1px solid var(--fcie-line); color: var(--fcie-muted);
    background: var(--fcie-raised); margin: 0 0.3rem 0.3rem 0; white-space: nowrap;
  }
  .fcie-chip b {color: var(--fcie-ink); font-weight: 660;}
  .fcie-chip--good {border-color: color-mix(in srgb, var(--fcie-good) 40%, transparent);
                    color: var(--fcie-good);}
  .fcie-chip--warn {border-color: color-mix(in srgb, var(--fcie-warn) 45%, transparent);
                    color: var(--fcie-warn);}
  .fcie-chip--bad  {border-color: color-mix(in srgb, var(--fcie-bad) 45%, transparent);
                    color: var(--fcie-bad);}
  .fcie-chip--accent {border-color: color-mix(in srgb, var(--fcie-accent) 40%, transparent);
                      color: var(--fcie-accent);}

  /* ── Cards: give each item an edge so lists stop running together ──── */
  .fcie-card {
    border: 1px solid var(--fcie-line); border-radius: var(--fcie-radius);
    padding: 0.9rem 1rem; margin-bottom: 0.7rem; background: var(--fcie-surface);
  }
  .fcie-card__title {font-size: 0.97rem; font-weight: 620; line-height: 1.4;
                     margin-bottom: 0.2rem;}
  .fcie-card__title a {color: var(--fcie-ink); text-decoration: none;}
  .fcie-card__title a:hover {color: var(--fcie-accent); text-decoration: underline;}
  .fcie-card__meta {font-size: 0.76rem; color: var(--fcie-muted); margin-bottom: 0.5rem;}
  .fcie-card__body {font-size: 0.86rem; line-height: 1.55; margin: 0.35rem 0 0.5rem;}

  /* ── Score bar: a number you can compare at a glance ────────────────── */
  .fcie-score {display: flex; align-items: center; gap: 0.5rem; margin: 0.15rem 0;}
  .fcie-score__num {font-size: 1.05rem; font-weight: 680; min-width: 2.4rem;
                    letter-spacing: -0.02em;}
  .fcie-score__track {flex: 1; height: 5px; border-radius: 999px;
                      background: var(--fcie-line); overflow: hidden;}
  .fcie-score__fill {height: 100%; border-radius: 999px; background: var(--fcie-accent);}
  .fcie-score__label {font-size: 0.7rem; color: var(--fcie-muted);
                      text-transform: uppercase; letter-spacing: 0.04em;
                      min-width: 5.5rem;}

  /* ── Evidence vs interpretation: the core visual distinction ────────── */
  .fcie-evidence {
    border-left: 3px solid var(--fcie-evidence);
    background: color-mix(in srgb, var(--fcie-evidence) 5%, transparent);
    padding: 0.6rem 0.8rem; margin: 0.5rem 0; font-size: 0.88rem; line-height: 1.6;
    border-radius: 0 var(--fcie-radius) var(--fcie-radius) 0;
  }
  .fcie-inference {
    border-left: 3px solid var(--fcie-infer);
    background: color-mix(in srgb, var(--fcie-infer) 6%, transparent);
    padding: 0.6rem 0.8rem; margin: 0.5rem 0; font-size: 0.88rem; line-height: 1.6;
    border-radius: 0 var(--fcie-radius) var(--fcie-radius) 0;
  }
  .fcie-srcline {font-size: 0.72rem; color: var(--fcie-muted); margin-top: 0.35rem;}
  .fcie-srcline a {color: var(--fcie-accent);}

  .fcie-muted {font-size: 0.79rem; color: var(--fcie-muted);}
  .fcie-lead  {font-size: 0.95rem; line-height: 1.65;}

  /* ── Sidebar: status you can read in one pass ───────────────────────── */
  section[data-testid="stSidebar"] .fcie-status {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 0.76rem; padding: 0.26rem 0; border-bottom: 1px solid var(--fcie-line);
  }
  section[data-testid="stSidebar"] .fcie-status span:last-child {
    color: var(--fcie-muted); text-align: right; margin-left: 0.5rem;
  }

  hr {margin: 1.3rem 0; opacity: 0.4;}
  [data-testid="stExpander"] details {border-radius: var(--fcie-radius);
      border-color: var(--fcie-line);}
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
    cfg = load_config()
    with st.sidebar:
        st.markdown("### Founder Content Intelligence")
        st.caption(f"v{__version__} · independent prototype")

        rows = cfg.integration_status()
        ready = sum(1 for r in rows if r["ready"] == "yes")
        st.markdown(
            f"<div style='margin:.6rem 0 .3rem'>"
            f"<span class='fcie-muted'>Connections · {ready}/{len(rows)} live</span></div>",
            unsafe_allow_html=True,
        )
        # One line per integration: name left, state right. Six paragraphs of
        # bold headings and captions was more text than signal.
        html = []
        for row in rows:
            icon = {"yes": "🟢", "fallback": "🟡", "no": "⚪"}.get(row["ready"], "⚪")
            name = _STATUS_SHORT.get(row["integration"], row["integration"])
            html.append(
                f"<div class='fcie-status'><span>{icon} {name}</span>"
                f"<span>{row['status']}</span></div>"
            )
        st.markdown("".join(html), unsafe_allow_html=True)

        with st.expander("What do these mean?"):
            for row in rows:
                st.markdown(
                    f"**{_STATUS_SHORT.get(row['integration'], row['integration'])}** — "
                    f"{row['detail']}"
                )
        st.divider()
        st.caption(describe_backend())
        st.caption(
            "Nothing is published automatically. Every draft requires human approval."
        )
        st.caption(
            "Work sample for [Founder's Associate, Office of the CEO]"
            "(https://job-boards.greenhouse.io/podium81/jobs/7967715) — "
            "role mapping in `docs/ROLE_MAPPING.md`."
        )


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


def signal_card(signal: dict) -> None:
    """One ranked source. Replaces four stacked st.metric columns."""
    published = relative_time(signal.get("published_at"))
    theme = signal.get("theme") or "unclassified"
    meta = f"{signal.get('domain','')} · {published} · {theme}"
    body = ""
    if signal.get("problem"):
        body = f"<b>Problem in source:</b> {truncate_words(signal['problem'], 34)}"
    card(
        title=truncate_words(signal.get("title") or "(untitled)", 18),
        meta=meta, body=body, url=signal.get("url"),
        chip_html=(
            score_bar(signal.get("score"), "opportunity")
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
