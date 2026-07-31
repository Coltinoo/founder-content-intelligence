"""Voice Library — manually added public examples and the derived voice guide."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from fcie.db import init_db
from fcie.pipeline.voice import add_voice_example, analyse_and_store, build_voice_guide
from fcie.queries import delete_voice_example, set_voice_approval, voice_examples
from fcie.ui.components import empty_state, format_date, header, page_setup, sidebar_status

page_setup("Voice Library", "🗣")
init_db()
sidebar_status()
header(
    "Voice Library",
    "Founder voice alignment based on approved public examples.",
)

st.info(
    "**Nothing here is scraped.** Public LinkedIn posts and other platform content enter this "
    "system only when a human copies the public text and pastes it below, together with its "
    "URL. No LinkedIn action is ever automated. The resulting guide describes measurable "
    "patterns in a small sample of public text — it does not reproduce, imitate, or represent "
    "any individual's voice, and no generated draft may be presented as written or approved "
    "by them.",
    icon="ℹ️",
)

CONTENT_TYPES = ["linkedin_post", "interview", "podcast", "press_quote", "keynote",
                 "blog_post", "earnings_or_investor_comment", "other"]

# ── add ─────────────────────────────────────────────────────────────────────
with st.expander("➕ Add an approved public example", expanded=False):
    with st.form("add_voice"):
        c1, c2 = st.columns(2)
        title = c1.text_input("Title / description *")
        content_type = c2.selectbox("Content type", CONTENT_TYPES)
        c3, c4 = st.columns(2)
        url = c3.text_input("Public source URL")
        date = c4.date_input("Date published", value=None)
        text = st.text_area(
            "Pasted public text *", height=260,
            placeholder="Paste the full public text you have permission to reference…",
        )
        approve_now = st.checkbox("Approve for the voice library immediately", value=True)
        confirm = st.checkbox(
            "I confirm this text is publicly available and that I copied it manually.",
            value=False,
        )
        submitted = st.form_submit_button("Add example", type="primary")

    if submitted:
        if not confirm:
            st.error("Please confirm the text is public and manually copied.")
        elif not text.strip():
            st.error("Pasted text is required.")
        else:
            try:
                example_id = add_voice_example(
                    title=title or "(untitled)",
                    text=text,
                    source_url=url or None,
                    date=datetime.combine(date, datetime.min.time()) if date else None,
                    content_type=content_type,
                    approved=approve_now,
                )
                st.success(f"Added and analysed example #{example_id}.")
                st.cache_data.clear()
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

examples = voice_examples()
approved = [e for e in examples if e["approved"]]

m1, m2, m3 = st.columns(3)
m1.metric("Examples stored", len(examples))
m2.metric("Approved for the guide", len(approved))
m3.metric("Content types", len({e["content_type"] for e in approved}) if approved else 0)

if not examples:
    empty_state(
        "No voice examples yet.",
        "Add at least five approved public examples above. Until then the system will not "
        "assert a voice guide — it reports that it cannot draw a conclusion.",
    )
    st.stop()

st.divider()

tab_examples, tab_guide = st.tabs(["Examples", "Derived voice guide"])

# ── examples ────────────────────────────────────────────────────────────────
with tab_examples:
    for example in examples:
        with st.container(border=True):
            head, actions = st.columns([3, 1])
            head.markdown(
                f"**{example['title']}** {'✅' if example['approved'] else '⏸'}  \n"
                f"<span class='fcie-muted'>{example['content_type']} · "
                f"{format_date(example['date'])} · "
                f"{len(example['pasted_text'].split())} words</span>",
                unsafe_allow_html=True,
            )
            if example["source_url"]:
                head.markdown(f"[Open public source]({example['source_url']})")

            with actions:
                if example["approved"]:
                    if st.button("Unapprove", key=f"unap_{example['id']}"):
                        set_voice_approval(example["id"], False)
                        st.cache_data.clear()
                        st.rerun()
                else:
                    if st.button("Approve", key=f"ap_{example['id']}"):
                        set_voice_approval(example["id"], True)
                        st.cache_data.clear()
                        st.rerun()
                if st.button("Re-analyse", key=f"re_{example['id']}"):
                    analyse_and_store(example["id"])
                    st.cache_data.clear()
                    st.rerun()
                if st.button("Delete", key=f"del_{example['id']}"):
                    delete_voice_example(example["id"])
                    st.cache_data.clear()
                    st.rerun()

            if example["hook_style"]:
                a1, a2 = st.columns(2)
                a1.caption(f"**Hook:** {example['hook_style']}")
                a1.caption(f"**Sentences:** {example['sentence_style']}")
                a2.caption(f"**Evidence:** {example['evidence_style']}")
                a2.caption(f"**Tone:** {example['tone_notes']}")
            if example["recurring_themes"]:
                st.caption("Themes detected: " + ", ".join(example["recurring_themes"]))

            with st.expander("Pasted text"):
                st.text(example["pasted_text"])
            if example["analysis"]:
                with st.expander("Full analysis"):
                    st.json(example["analysis"])

# ── guide ───────────────────────────────────────────────────────────────────
with tab_guide:
    use_llm = st.checkbox("Also run the LLM voice analysis (needs OPENAI_API_KEY)", value=False)
    guide = build_voice_guide(use_llm=use_llm)

    if guide.get("status") == "empty":
        st.warning(guide["message"])
        st.markdown("**Default assumptions that remain unconfirmed:**")
        for assumption in guide["unsupported_assumptions"]:
            st.markdown(f"- {assumption}")
        st.stop()

    st.markdown(f"### {guide['label']}")
    st.caption(guide["disclaimer"])
    if guide.get("coverage_warning"):
        st.warning(guide["coverage_warning"])

    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Approved examples", guide["approved_example_count"])
    g2.metric("Median sentence", f"{guide['median_sentence_words']} words")
    g3.metric("Median paragraph", f"{guide['median_paragraph_sentences']} sentences")
    g4.metric("Median post length", f"{guide['median_word_count']} words")

    st.markdown("#### Hook structure")
    for pattern in guide["hook_patterns"]:
        st.markdown(f"- {pattern}")
    if guide["example_hooks"]:
        st.caption("Observed hooks (verbatim from the approved examples):")
        for hook in guide["example_hooks"]:
            st.markdown(f"> {hook}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Observed patterns")
        st.markdown(f"- **Tone:** {guide['tone']}")
        st.markdown(f"- **Numbers:** {guide['use_of_numbers']}")
        st.markdown(f"- **Customer stories:** {guide['use_of_customer_stories']}")
        st.markdown(f"- **Contrast:** {guide['use_of_contrast']}")
        st.markdown(f"- **Founder experience:** {guide['use_of_founder_experience']}")
        st.markdown(f"- **Technical detail:** {guide['technical_detail_level']}")
        st.markdown(f"- **Calls to action:** {guide['cta_share']}")
        if guide["typical_calls_to_action"]:
            for cta in guide["typical_calls_to_action"]:
                st.caption(f"· “{cta}”")
    with c2:
        st.markdown("#### Recurring themes (in 2+ examples)")
        if guide["recurring_themes"]:
            for theme in guide["recurring_themes"]:
                st.markdown(f"- {theme}")
        else:
            st.caption("No theme appears in two or more examples yet.")
        if guide["hype_terms_found"]:
            st.warning("Hype vocabulary present in the examples: "
                       + ", ".join(guide["hype_terms_found"]))
        else:
            st.success("No hype vocabulary found in any approved example.")

    st.divider()
    st.markdown("#### Assumption audit")
    st.caption(
        "Default assumptions are only asserted when the approved examples actually exhibit "
        "them. Everything else is reported as unconfirmed rather than claimed."
    )
    a1, a2 = st.columns(2)
    with a1:
        st.markdown("**Confirmed by the examples**")
        for assumption in guide["confirmed_assumptions"] or ["_none yet_"]:
            st.markdown(f"- ✅ {assumption}")
    with a2:
        st.markdown("**Not confirmed by the examples**")
        for assumption in guide["unsupported_assumptions"] or ["_none_"]:
            st.markdown(f"- ⚪ {assumption}")

    if guide.get("llm_analysis"):
        with st.expander("LLM voice analysis (full JSON)"):
            st.json(guide["llm_analysis"])

    with st.expander("Full guide JSON (editable source of truth for drafting)"):
        st.json(guide)
