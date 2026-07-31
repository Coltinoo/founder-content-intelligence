"""Content Brief Detail — the primary product output, with evidence and approval controls."""

from __future__ import annotations

import streamlit as st

from fcie.db import init_db
from fcie.models import DRAFT_FORMATS
from fcie.pipeline.drafts import FORMAT_LABELS, generate_draft, set_approval
from fcie.pipeline.opportunities import generate_opportunities
from fcie.queries import (
    opportunities_list,
    opportunity_detail,
    set_opportunity_status,
    update_checklist,
)
from fcie.ui.components import (
    STATUS_LABELS,
    empty_state,
    evidence_block,
    format_date,
    header,
    inference_block,
    page_setup,
    risk_badge,
    score_breakdown_table,
    sidebar_status,
    trend_badge,
)

page_setup("Content Brief", "📝")
init_db()
sidebar_status()
header("Content Brief Detail", "Every claim linked to the source it came from.")

opportunities = opportunities_list()
if not opportunities:
    empty_state("No content opportunities yet.",
                "Generate briefs on the Content Pipeline page.")
    st.stop()

selected_id = st.selectbox(
    "Content opportunity",
    [o["id"] for o in opportunities],
    format_func=lambda i: (
        f"#{i} · {next(o['score'] for o in opportunities if o['id'] == i):.0f}/100 — "
        + next(o["title"] for o in opportunities if o["id"] == i)[:90]
    ),
)

detail = opportunity_detail(int(selected_id))
if detail is None:
    st.error("Opportunity not found.")
    st.stop()

opportunity = detail["opportunity"]
theme = detail["theme"]
sources = detail["sources"]
drafts = detail["drafts"]

# ── header ──────────────────────────────────────────────────────────────────
st.markdown(f"# {opportunity['title']}")
meta = [f"Status: **{STATUS_LABELS.get(opportunity['status'], opportunity['status'])}**"]
if theme:
    meta.append(f"Theme: **{theme['name']}** {trend_badge(theme['trend_status'])}")
meta.append(f"Built by: `{opportunity['generation_method']}`")
meta.append(f"Created {format_date(opportunity['created_at'])}")
st.markdown(" · ".join(meta))

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Opportunity score", f"{opportunity['opportunity_score']:.0f}/100")
m2.metric("Confidence", f"{opportunity['confidence_score']:.0f}/100")
m3.metric("Risk", f"{opportunity['risk_score']:.0f}/100")
m4.metric("Sources", len(sources))
m5.metric("Verbatim passages", len(opportunity["evidence_passages"]))
st.markdown(f"Risk band: {risk_badge(opportunity['risk_score'])}")

st.divider()

tabs = st.tabs([
    "Brief", "Score breakdown", "Evidence & sources",
    "Verification checklist", "Drafts & approval",
])

# ── 1. brief ────────────────────────────────────────────────────────────────
with tabs[0]:
    st.markdown("### Core insight")
    st.markdown(opportunity["core_insight"] or "_Not generated._")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Why now")
        st.markdown(opportunity["why_now"] or "_Not generated._")
        st.markdown("### Why it matters to Podium")
        st.markdown(opportunity["why_podium"] or "_Not generated._")
    with c2:
        st.markdown("### Why Eric could credibly discuss it")
        st.markdown(opportunity["why_eric"] or "_Not generated._")
        st.markdown("### Intended audience")
        st.markdown(opportunity["target_audience"] or "_Not generated._")

    st.markdown("### Founder point of view")
    inference_block(opportunity["founder_point_of_view"] or "_Not generated._",
                    "Argument — an inference, not a source finding")

    st.markdown("### Suggested opening hook")
    st.markdown(f"> {opportunity['hook'] or '_Not generated._'}")

    st.markdown(f"### Supporting points ({len(opportunity['supporting_points'])})")
    st.caption("Each point carries at least one source id and a verbatim evidence passage. "
               "Points that could not be evidenced were dropped, not softened.")
    for index, point in enumerate(opportunity["supporting_points"], start=1):
        ids = ", ".join(f"#{i}" for i in point.get("evidence_source_ids", []))
        st.markdown(f"**{index}. {point.get('point', '')}**  \n"
                    f"<span class='fcie-muted'>evidence: source {ids}</span>",
                    unsafe_allow_html=True)
        evidence_block(
            point.get("evidence_passage", ""),
            (point.get("evidence_source_ids") or [None])[0],
            point.get("evidence_url"),
            point.get("evidence_domain"),
        )

    st.markdown("### Potential objections")
    if not opportunity["potential_objections"]:
        st.caption("None recorded.")
    for objection in opportunity["potential_objections"]:
        st.markdown(f"**{objection.get('objection', '')}**")
        st.markdown(f"↳ {objection.get('response', '')}")

    c3, c4 = st.columns(2)
    c3.markdown(f"### Recommended format\n`{opportunity['recommended_format']}`")
    c4.markdown(f"### Suggested call to action\n{opportunity['suggested_call_to_action'] or '—'}")

    if opportunity["risk_notes"]:
        st.markdown("### Risk notes")
        for note in opportunity["risk_notes"]:
            st.warning(note)

    with st.expander("Regenerate this brief"):
        force_heuristic = st.checkbox("Force heuristic builder", key="regen_heur")
        if st.button("Regenerate", type="secondary"):
            if theme:
                with st.spinner("Rebuilding from the stored evidence…"):
                    report = generate_opportunities(
                        theme_names=[theme["name"]], force_regenerate=True,
                        force_heuristic=force_heuristic,
                    )
                st.success(f"Rebuilt ({report.backend}).")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("This opportunity has no linked theme, so it cannot be rebuilt.")

# ── 2. score ────────────────────────────────────────────────────────────────
with tabs[1]:
    st.markdown("### Opportunity score")
    st.caption("A transparent 100-point model. Weights live in `config/scoring.yaml` and are "
               "editable on the Settings page.")
    score_breakdown_table(opportunity["score_breakdown"])

    st.markdown("### Risk")
    st.caption("Risk is scored independently of opportunity, so a high-value, high-risk item "
               "stays visible instead of being averaged away.")
    st.metric("Risk score", f"{opportunity['risk_score']:.0f}/100  ({risk_badge(opportunity['risk_score'])})")
    for note in opportunity["risk_notes"]:
        st.markdown(f"- {note}")

    st.markdown("### Confidence")
    st.metric("Confidence", f"{opportunity['confidence_score']:.0f}/100")
    st.caption(
        "Confidence reflects how well-supported the brief is — distinct domains, number of "
        "verbatim passages, average evidence strength, and source volume. It is deliberately "
        "separate from how attractive the opportunity is."
    )

# ── 3. evidence ─────────────────────────────────────────────────────────────
with tabs[2]:
    st.markdown(f"### Supporting sources ({len(sources)})")
    for source in sources:
        flags = []
        if source.get("is_promotional"):
            flags.append("vendor marketing")
        flag_text = f" · <span class='fcie-muted'>{', '.join(flags)}</span>" if flags else ""
        st.markdown(
            f"**#{source['id']} [{(source['title'] or '(untitled)')[:110]}]({source['url']})**  \n"
            f"<span class='fcie-muted'>{source['domain']} · {source['source_type']} · "
            f"{format_date(source['published_at'])} · "
            f"evidence {source['evidence_strength'] or 0:.0f}/10 · "
            f"analysed by {source['extraction_method']}</span>{flag_text}",
            unsafe_allow_html=True,
        )

    st.markdown(f"### Verbatim evidence passages ({len(opportunity['evidence_passages'])})")
    st.caption("Each passage was re-checked against the stored source text before being saved. "
               "Any passage that failed the check was discarded.")
    for passage in opportunity["evidence_passages"]:
        evidence_block(passage.get("passage", ""), passage.get("source_id"),
                       passage.get("url"), passage.get("domain"))

# ── 4. checklist ────────────────────────────────────────────────────────────
with tabs[3]:
    st.markdown("### Pre-publication verification checklist")
    st.caption("Nothing here is publication-ready until a human has worked through this list.")
    checklist = list(opportunity["verification_checklist"])
    if not checklist:
        st.caption("No checklist generated.")
    updated = []
    for index, item in enumerate(checklist):
        done = st.checkbox(item.get("item", ""), value=bool(item.get("done")),
                           key=f"chk_{selected_id}_{index}")
        if item.get("why"):
            st.caption(f"↳ {item['why']}")
        updated.append({**item, "done": done})

    if checklist and st.button("Save checklist"):
        update_checklist(int(selected_id), updated)
        st.success("Checklist saved.")
        st.cache_data.clear()

    remaining = sum(1 for item in updated if not item["done"])
    if checklist:
        if remaining:
            st.warning(f"{remaining} verification item(s) still outstanding.")
        else:
            st.success("All verification items complete. A human may now decide on publication.")

# ── 5. drafts ───────────────────────────────────────────────────────────────
with tabs[4]:
    st.markdown("### Generate a draft")
    col1, col2, col3 = st.columns([2, 1, 1])
    content_type = col1.selectbox("Format", DRAFT_FORMATS,
                                  format_func=lambda f: FORMAT_LABELS.get(f, f))
    heuristic = col2.checkbox("Force heuristic writer", key="draft_heur")
    if col3.button("Generate draft", type="primary"):
        with st.spinner("Writing and auditing the draft…"):
            result = generate_draft(int(selected_id), content_type, force_heuristic=heuristic)
        if result.get("ok"):
            st.success(f"Draft #{result['draft_id']} created "
                       f"(evidence {result['evidence_score']:.0f}/100, "
                       f"voice {result['voice_score']:.0f}/100).")
            st.cache_data.clear()
            st.rerun()
        else:
            st.error(result.get("error", "Draft generation failed."))

    st.divider()
    st.markdown(f"### Drafts ({len(drafts)})")
    if not drafts:
        st.caption("No drafts yet.")

    for draft in drafts:
        with st.container(border=True):
            st.markdown(
                f"**Draft #{draft['id']} — {FORMAT_LABELS.get(draft['content_type'], draft['content_type'])}**  \n"
                f"<span class='fcie-muted'>built by `{draft['generation_method']}` · "
                f"{format_date(draft['created_at'])} · status: **{draft['approval_status']}**</span>",
                unsafe_allow_html=True,
            )
            d1, d2, d3 = st.columns(3)
            d1.metric("Evidence score", f"{draft['evidence_score']:.0f}/100")
            d2.metric("Voice alignment", f"{draft['voice_score']:.0f}/100")
            d3.metric("Unsupported sentences", len(draft["unsupported_claims"]))

            st.text_area("Draft text", draft["draft_text"], height=340,
                         key=f"draft_text_{draft['id']}")

            if draft["unsupported_claims"]:
                with st.expander(f"⚠️ {len(draft['unsupported_claims'])} sentence(s) with no "
                                 "supporting evidence passage"):
                    for claim in draft["unsupported_claims"]:
                        st.markdown(f"- {claim}")

            if draft["verification_required"]:
                with st.expander(f"Verification required ({len(draft['verification_required'])})"):
                    for item in draft["verification_required"]:
                        st.markdown(f"- {item}")

            if draft["voice_notes"]:
                with st.expander("Voice alignment notes"):
                    for note in draft["voice_notes"]:
                        st.caption(f"· {note}")

            if draft["cited_source_ids"]:
                st.caption("Cited sources: " + ", ".join(f"#{i}" for i in draft["cited_source_ids"]))

            st.markdown("**Human decision**")
            a1, a2, a3, a4 = st.columns([1, 1, 1, 2])
            reviewer_note = a4.text_input("Reviewer note", key=f"note_{draft['id']}",
                                          value=draft.get("reviewer_notes") or "")
            if a1.button("✓ Approve", key=f"approve_{draft['id']}"):
                set_approval(draft["id"], "approved", reviewer_note)
                set_opportunity_status(int(selected_id), "approved", reviewer_note)
                st.success("Approved for publication by a human. The system will not publish it.")
                st.cache_data.clear()
                st.rerun()
            if a2.button("↻ Request changes", key=f"changes_{draft['id']}"):
                set_approval(draft["id"], "changes_requested", reviewer_note)
                set_opportunity_status(int(selected_id), "review", reviewer_note)
                st.info("Marked as changes requested.")
                st.cache_data.clear()
                st.rerun()
            if a3.button("✕ Reject", key=f"reject_{draft['id']}"):
                set_approval(draft["id"], "rejected", reviewer_note)
                st.warning("Rejected.")
                st.cache_data.clear()
                st.rerun()

st.divider()
st.caption(
    "This system never publishes. Approval records a human decision inside the tool; "
    "posting anywhere remains a manual action. No draft has been written or approved by "
    "Eric Rea or Podium."
)
