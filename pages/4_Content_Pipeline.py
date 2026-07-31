"""Content Pipeline — kanban of opportunities by status, with generation controls."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from fcie.db import init_db
from fcie.models import OPPORTUNITY_STATUSES
from fcie.pipeline.opportunities import generate_opportunities
from fcie.queries import opportunities_list, set_opportunity_status, themes_dataframe
from fcie.ui.components import (
    STATUS_LABELS,
    empty_state,
    format_date,
    header,
    page_setup,
    risk_badge,
    sidebar_status,
)

page_setup("Content Pipeline", "🧭")
init_db()
sidebar_status()
header("Content Pipeline", "Opportunities from New through to Approved. Nothing leaves this "
                          "system without a human decision.")

# ── generation ──────────────────────────────────────────────────────────────
with st.expander("⚙ Generate or regenerate briefs"):
    themes = themes_dataframe()
    theme_choices = themes["name"].tolist() if not themes.empty else []
    selected = st.multiselect(
        "Limit to specific themes (leave empty to use every promotable theme)",
        theme_choices,
    )
    col1, col2, col3 = st.columns(3)
    regenerate = col1.checkbox("Overwrite existing briefs", value=False,
                              help="Approved and in-review briefs are never overwritten.")
    heuristic = col2.checkbox("Force heuristic builder", value=False)
    max_count = col3.number_input("Max briefs", 1, 30, 10)

    if st.button("Generate briefs", type="primary"):
        with st.spinner("Building evidence-backed briefs…"):
            report = generate_opportunities(
                theme_names=selected or None,
                max_opportunities=int(max_count),
                force_regenerate=regenerate,
                force_heuristic=heuristic,
            )
        st.success(f"{report.created} created, {report.updated} updated "
                   f"(backend: {report.backend}).")
        if report.skipped:
            with st.expander(f"{len(report.skipped)} theme(s) skipped and why"):
                for reason in report.skipped:
                    st.caption(f"· {reason}")
        if report.errors:
            for error in report.errors:
                st.error(error)
        st.cache_data.clear()
        st.rerun()

opportunities = opportunities_list()
if not opportunities:
    empty_state(
        "No content opportunities yet.",
        "Run discovery from the Executive Dashboard, then press *Generate briefs* above.",
    )
    st.stop()

# ── summary ─────────────────────────────────────────────────────────────────
counts = {status: 0 for status in OPPORTUNITY_STATUSES}
for opportunity in opportunities:
    counts[opportunity["status"]] = counts.get(opportunity["status"], 0) + 1

cols = st.columns(len(OPPORTUNITY_STATUSES))
for col, status in zip(cols, OPPORTUNITY_STATUSES):
    col.metric(STATUS_LABELS[status], counts.get(status, 0))

st.divider()

view_mode = st.radio("View", ["Board", "Table"], horizontal=True, label_visibility="collapsed")

if view_mode == "Table":
    frame = pd.DataFrame(opportunities)[[
        "id", "title", "theme", "trend_status", "status", "score", "confidence",
        "risk", "source_count", "evidence_count", "points", "drafts",
        "format", "generation_method", "created_at",
    ]].rename(columns={
        "id": "ID", "title": "Title", "theme": "Theme", "trend_status": "Trend",
        "status": "Status", "score": "Score", "confidence": "Confidence", "risk": "Risk",
        "source_count": "Sources", "evidence_count": "Passages", "points": "Points",
        "drafts": "Drafts", "format": "Format", "generation_method": "Built by",
        "created_at": "Created",
    })
    st.dataframe(
        frame, hide_index=True, width="stretch", height=500,
        column_config={
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
            "Created": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
        },
    )
else:
    board_statuses = ["new", "research_needed", "ready_for_brief", "drafting", "review", "approved"]
    board_cols = st.columns(len(board_statuses))
    for col, status in zip(board_cols, board_statuses):
        with col:
            st.markdown(f"##### {STATUS_LABELS[status]}")
            items = [o for o in opportunities if o["status"] == status]
            if not items:
                st.caption("—")
            for opportunity in items:
                st.markdown(
                    f"**#{opportunity['id']}** {opportunity['title'][:70]}  \n"
                    f"<span class='fcie-muted'>score {opportunity['score']:.0f} · "
                    f"risk {opportunity['risk']:.0f} · {opportunity['source_count']} src · "
                    f"{opportunity['drafts']} draft(s)</span>",
                    unsafe_allow_html=True,
                )
                st.markdown("<hr>", unsafe_allow_html=True)

    archived = [o for o in opportunities if o["status"] == "archived"]
    if archived:
        with st.expander(f"Archived ({len(archived)})"):
            for opportunity in archived:
                st.caption(f"#{opportunity['id']} {opportunity['title']}")

st.divider()

# ── status control ──────────────────────────────────────────────────────────
st.markdown("## Move an opportunity")
col1, col2, col3 = st.columns([2, 1, 2])
target_id = col1.selectbox(
    "Opportunity",
    [o["id"] for o in opportunities],
    format_func=lambda i: f"#{i} — " + next(o["title"] for o in opportunities if o["id"] == i)[:80],
)
current = next(o for o in opportunities if o["id"] == target_id)
new_status = col2.selectbox(
    "New status", OPPORTUNITY_STATUSES,
    index=OPPORTUNITY_STATUSES.index(current["status"]),
    format_func=lambda s: STATUS_LABELS[s],
)
notes = col3.text_input("Reviewer note (optional)")

if st.button("Update status"):
    if set_opportunity_status(int(target_id), new_status, notes):
        st.success(f"Opportunity #{target_id} moved to {STATUS_LABELS[new_status]}.")
        st.cache_data.clear()
        st.rerun()
    else:
        st.error("Update failed.")

st.info(
    f"Open **Content Brief Detail** to read the full brief for #{target_id}, see its score "
    "breakdown and evidence, generate drafts, and approve or reject them."
)
st.caption(f"Selected: **{current['title']}** — {risk_badge(current['risk'])} risk, "
           f"built by {current['generation_method']}, created {format_date(current['created_at'])}.")
