"""Source Library — search, filter, inspect evidence, add manual sources, reprocess."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from fcie.connectors.manual import MANUAL_TYPES, build_manual_item
from fcie.db import init_db
from fcie.pipeline.extract import run_extraction
from fcie.pipeline.ingest import ingest_manual_item
from fcie.queries import filter_options, source_detail, sources_dataframe
from fcie.utils.format import count_label, humanize_label, relative_time


from fcie.config import read_only_notice
from fcie.ui.components import (
    admin,
    empty_state,
    evidence_block,
    format_date,
    header,
    inference_block,
    method_chip,
    page_setup,
    risk_badge,
    risk_breakdown_table,
    score_breakdown_table,
    sidebar_status,
)

page_setup("Source Library", "🗂")
init_db()
sidebar_status()
header("Source Library", "Every collected source, its extracted evidence, and its provenance.")

options = filter_options()

# ── manual entry ────────────────────────────────────────────────────────────
if not admin():
    st.caption("🔒 " + read_only_notice())

if admin():
  with st.expander("➕ Add a source manually (public content only)"):
    st.caption(
        "The lawful route for anything that cannot be collected automatically: public "
        "LinkedIn post text you have copied, interview transcripts, meeting notes, or "
        "customer insights. Nothing here is scraped — you supply the text and the URL."
    )
    with st.form("manual_source"):
        col1, col2 = st.columns(2)
        manual_type = col1.selectbox(
            "Source type", list(MANUAL_TYPES), format_func=lambda k: MANUAL_TYPES[k]
        )
        manual_url = col2.text_input("Canonical URL (optional)")
        col3, col4, col5 = st.columns(3)
        manual_title = col3.text_input("Title")
        manual_author = col4.text_input("Author / speaker")
        manual_date = col5.date_input("Publication date", value=None)
        manual_description = st.text_input("Description of the source (why it matters)")
        manual_text = st.text_area("Pasted text *", height=220,
                                   placeholder="Paste the full public text here…")
        submitted = st.form_submit_button("Add source", type="primary")

    if submitted:
        try:
            item = build_manual_item(
                text=manual_text,
                source_type=manual_type,
                url=manual_url or None,
                title=manual_title or None,
                author=manual_author or None,
                published_at=datetime.combine(manual_date, datetime.min.time()) if manual_date else None,
                description=manual_description or None,
            )
            outcome = ingest_manual_item(item)
            if outcome["result"] == "stored":
                st.success(f"Stored as source #{outcome['id']}. Extracting…")
                run_extraction(source_ids=[outcome["id"]])
                st.cache_data.clear()
                st.rerun()
            elif outcome["result"] == "duplicate":
                st.warning(
                    f"Already in the library as source #{outcome['id']} "
                    f"(matched by {outcome['method']}: {outcome['detail']}). "
                    "The discovery metadata was merged rather than creating a duplicate."
                )
            else:
                st.error(f"Not stored: {outcome}")
        except ValueError as exc:
            st.error(str(exc))

# ── filters ─────────────────────────────────────────────────────────────────
st.markdown("## Filters")
f1, f2, f3 = st.columns([2, 1, 1])
search = f1.text_input("Search title, domain, URL, or discovery query")
date_window = f2.selectbox("Date window", ["All time", "Last 7 days", "Last 30 days", "Last 90 days"])
limit = f3.number_input("Max rows", 50, 2000, 300, step=50)

f4, f5, f6, f7 = st.columns(4)
selected_types = f4.multiselect("Source type", options["source_types"])
selected_domains = f5.multiselect("Domain", options["domains"])
selected_themes = f6.multiselect("Theme", options["themes"])
selected_industries = f7.multiselect("Industry", options["industries"])
selected_statuses = st.multiselect("Status", options["statuses"])

since = None
if date_window != "All time":
    days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}[date_window]
    since = datetime.utcnow() - timedelta(days=days)

frame = sources_dataframe(
    search=search, source_types=selected_types or None, domains=selected_domains or None,
    industries=selected_industries or None, themes=selected_themes or None,
    statuses=selected_statuses or None, since=since, limit=int(limit),
)

if frame.empty:
    empty_state("No sources match these filters.",
                "Clear the filters, or run discovery from the Executive Dashboard.")
    st.stop()

st.caption(f"{count_label(len(frame), 'source')} shown.")

display = frame[[
    "id", "title", "domain", "source_type", "status", "published_at", "theme",
    "podium_relevance", "evidence_strength", "opportunity_score", "risk_score",
    "evidence_count", "quote_count", "extraction_method", "url",
]].rename(columns={
    "id": "ID", "title": "Title", "domain": "Domain", "source_type": "Type",
    "status": "Status", "published_at": "Published", "theme": "Theme",
    "podium_relevance": "Podium", "evidence_strength": "Evidence",
    "opportunity_score": "Score", "risk_score": "Risk",
    "evidence_count": "Passages", "quote_count": "Quotes",
    "extraction_method": "Analyser", "url": "URL",
})

st.dataframe(
    display,
    hide_index=True,
    width="stretch",
    height=420,
    column_config={
        "URL": st.column_config.LinkColumn("URL", display_text="open"),
        "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f"),
        "Published": st.column_config.DatetimeColumn("Published", format="YYYY-MM-DD"),
    },
)

# ── errors and policy skips ─────────────────────────────────────────────────
problems = frame[frame["status"].isin(["error", "needs_review"]) | frame["status"].str.startswith("skipped")]
if not problems.empty:
    with st.expander(f"⚠️ {count_label(len(problems), 'source')} with fetch errors, policy skips, or thin content"):
        for _, row in problems.iterrows():
            st.markdown(
                f"**#{row['id']} {row['title'][:90]}** — `{row['status']}`  \n"
                f"<span class='fcie-muted'>{row['domain']} · {row['fetch_error'] or 'no error recorded'}</span>",
                unsafe_allow_html=True,
            )

st.divider()

# ── detail ──────────────────────────────────────────────────────────────────
st.markdown("## Source detail")
source_id = st.selectbox(
    "Select a source",
    frame["id"].tolist(),
    format_func=lambda i: f"#{i} — {frame[frame['id'] == i]['title'].iloc[0][:90]}",
)

detail = source_detail(int(source_id))
if detail is None:
    st.error("Source not found.")
    st.stop()

source, signal = detail["source"], detail["signal"]

c1, c2 = st.columns([2, 1])
with c1:
    st.markdown(f"### [{source['title'] or '(untitled)'}]({source['url']})")
    st.markdown(
        f"<span class='fcie-muted'>{source['domain']} · {source['source_type']} · "
        f"published {format_date(source['published_at'])} · "
        f"discovered {format_date(source['discovered_at'])} · status `{source['status']}`</span>",
        unsafe_allow_html=True,
    )
    if source["author"]:
        st.caption(f"Author: {source['author']}")
    if source["search_query"]:
        st.caption(f"Discovered via query: “{source['search_query']}”")
    metadata = source["metadata"]
    if metadata.get("discovered_by_queries"):
        st.caption("Rediscovered by queries: " + ", ".join(
            q for q in metadata["discovered_by_queries"] if q))
    if metadata.get("rediscovery_count"):
        st.caption(
            f"Seen {metadata['rediscovery_count']} additional time(s) through other channels — "
            "stored once, discovery paths preserved."
        )
    if source["fetch_error"]:
        st.warning(f"Fetch note: {source['fetch_error']}")

with c2:
    if signal:
        st.metric("Opportunity score", f"{signal['opportunity_score']:.0f}/100")
        st.markdown(f"Risk: {risk_badge(signal['risk_score'])}")
        st.markdown(method_chip(signal["extraction_method"], signal.get("extraction_model")), unsafe_allow_html=True)
        st.caption(f"Model: {signal['extraction_model']}")
    if admin() and st.button("↻ Reprocess this source"):
        with st.spinner("Re-running extraction…"):
            report = run_extraction(source_ids=[int(source_id)])
        st.success(f"Reprocessed with the {report.backend} backend.")
        st.cache_data.clear()
        st.rerun()

if signal is None:
    st.info("This source has not been analysed yet. Press *Reprocess this source*.")
    if metadata.get("extraction_skipped_reason"):
        st.caption(f"Reason: {metadata['extraction_skipped_reason']}")
else:
    if signal["extraction_error"]:
        st.error(signal["extraction_error"])

    tabs = st.tabs(["Evidence (from the source)", "Interpretation (AI)", "Scores",
                    "Verification", "Full text"])

    with tabs[0]:
        st.caption("Everything in this tab was copied verbatim from the source and re-verified "
                   "against the stored text before being saved.")
        if signal["primary_claim"]:
            st.markdown("**Primary claim stated in the source**")
            evidence_block(signal["primary_claim"], source["id"], source["url"], source["domain"])
        if signal["customer_problem"]:
            st.markdown("**Customer problem described**")
            evidence_block(signal["customer_problem"], source["id"], source["url"], source["domain"])

        st.markdown(f"**Supporting passages ({len(signal['supporting_evidence'])})**")
        if not signal["supporting_evidence"]:
            st.caption("No passage met the verbatim threshold.")
        for passage in signal["supporting_evidence"]:
            evidence_block(passage.get("passage", ""), source["id"], source["url"], source["domain"])

        st.markdown(f"**Notable quotes ({len(signal['notable_quotes'])})**")
        if not signal["notable_quotes"]:
            st.caption("No verbatim quotation found in this source.")
        for quote in signal["notable_quotes"]:
            speaker = f" — {quote['speaker']}" if quote.get("speaker") else ""
            evidence_block(quote.get("quote", "") + speaker, source["id"], source["url"], source["domain"])

        st.markdown(f"**Numerical claims ({len(signal['numerical_claims'])})**")
        if signal["numerical_claims"]:
            st.dataframe(
                pd.DataFrame(signal["numerical_claims"])[["value", "context", "needs_verification"]]
                .rename(columns={"value": "Figure", "context": "Original sentence",
                                 "needs_verification": "Needs verification"}),
                hide_index=True, width="stretch",
            )
        else:
            st.caption("No numerical claims found.")

    with tabs[1]:
        st.caption("Everything in this tab is model or rule output, not a source claim.")
        e1, e2, e3 = st.columns(3)
        e1.markdown(f"**Primary entity**  \n{signal['primary_entity'] or '—'}")
        e2.markdown(f"**Industries**  \n{', '.join(signal['industries']) or '—'}")
        e3.markdown(f"**Customer segment**  \n{signal['customer_segment'] or '—'}")
        st.markdown(f"**Primary theme:** {signal['primary_theme'] or 'unassigned'}")
        if signal["secondary_themes"]:
            st.caption("Secondary themes: " + ", ".join(signal["secondary_themes"]))
        if signal["secondary_entities"]:
            st.caption("Other entities mentioned: " + ", ".join(signal["secondary_entities"]))
        if signal["content_opportunity"]:
            inference_block(signal["content_opportunity"], "Content opportunity (inference)")
        if signal["potential_angle"]:
            inference_block(signal["potential_angle"], "Potential angle (inference)")
        st.markdown(f"**Recommended format:** `{signal['recommended_format']}`")
        flags = []
        if signal["is_promotional"]:
            flags.append("vendor marketing — evidence weight reduced")
        if signal["is_familiar"]:
            flags.append("restates a familiar narrative — novelty reduced")
        if signal.get("is_summary_only"):
            flags.append(
                "publisher RSS summary only — the full body was access-restricted "
                "and was not bypassed; evidence weight reduced"
            )
        if flags:
            st.warning(" · ".join(flags))

    with tabs[2]:
        st.markdown("**Opportunity score breakdown**")
        score_breakdown_table(signal["score_breakdown"])
        st.markdown("**Risk breakdown** (scored independently of opportunity)")
        risk_breakdown_table(signal["risk_breakdown"])

    with tabs[3]:
        if not signal["verification_notes"]:
            st.success("No verification notes recorded.")
        for note in signal["verification_notes"]:
            st.warning(note)

    with tabs[4]:
        st.caption(
            f"Cleaned text as stored ({len((source['cleaned_text'] or '').split())} words). "
            f"Content hash: `{source['content_hash']}`"
        )
        st.text_area("Cleaned text", source["cleaned_text"] or "", height=420,
                     label_visibility="collapsed")
        with st.expander("Stored metadata"):
            st.json(source["metadata"])
