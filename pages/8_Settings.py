"""Settings — edit queries, feeds, domains, crawl rate, model, weights, and prompts."""

from __future__ import annotations

import pandas as pd
import streamlit as st
import yaml

from fcie.ai.prompts import PromptLibrary
from fcie.config import load_config, reload_config, write_yaml
from fcie.db import describe_backend, init_db
from fcie.queries import recent_runs
from fcie.ui.components import header, page_setup, sidebar_status

page_setup("Settings", "⚙")
init_db()
sidebar_status()
header("Settings", "Everything the pipeline reads is editable here or in `config/*.yaml`.")

cfg = load_config()

tabs = st.tabs([
    "Integrations", "Search queries", "RSS feeds", "Domains & crawl",
    "Model & scoring", "Prompts", "Run history",
])

# ── integrations ────────────────────────────────────────────────────────────
with tabs[0]:
    st.markdown("### Integration status")
    st.caption("Secrets are read from environment variables only — never from these YAML files.")
    frame = pd.DataFrame(cfg.integration_status())
    st.dataframe(
        frame.rename(columns={"integration": "Integration", "status": "Status",
                              "detail": "Detail", "ready": "Ready"}),
        hide_index=True, width="stretch",
    )
    st.markdown(f"**Database:** {describe_backend()}")
    st.markdown("### Enabling what is missing")
    st.code(
        "# .env  (copy from .env.example)\n"
        "OPENAI_API_KEY=sk-...              # LLM extraction, briefs, drafts\n"
        "TAVILY_API_KEY=tvly-...            # or BRAVE_SEARCH_API_KEY / BING_SEARCH_API_KEY\n"
        "GOOGLE_CSE_API_KEY=...             # with GOOGLE_CSE_CX=...\n"
        "YOUTUBE_API_KEY=...                # keyword video discovery\n"
        "FCIE_DATABASE_URL=postgresql+psycopg2://...   # Supabase\n",
        language="bash",
    )
    st.caption(
        "The application runs with none of these set. Each unconfigured connector reports "
        "itself and is skipped — nothing fails silently."
    )

# ── queries ─────────────────────────────────────────────────────────────────
with tabs[1]:
    st.markdown("### Recurring search queries")
    st.caption(
        "Executed through a lawful search API. Search-engine result pages are never scraped."
    )
    queries = cfg.queries.get("queries", [])
    frame = pd.DataFrame(queries) if queries else pd.DataFrame(
        columns=["query", "category", "enabled"]
    )
    edited = st.data_editor(
        frame, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "query": st.column_config.TextColumn("Query", required=True),
            "category": st.column_config.SelectboxColumn("Category", options=cfg.categories),
            "enabled": st.column_config.CheckboxColumn("Enabled", default=True),
        },
        key="queries_editor",
    )
    if st.button("Save queries"):
        payload = dict(cfg.queries)
        payload["queries"] = [
            {"query": r["query"], "category": r.get("category"), "enabled": bool(r.get("enabled", True))}
            for r in edited.to_dict("records") if r.get("query")
        ]
        write_yaml("queries.yaml", payload)
        reload_config()
        st.success(f"Saved {len(payload['queries'])} query/ies to config/queries.yaml.")
        st.rerun()

# ── feeds ───────────────────────────────────────────────────────────────────
with tabs[2]:
    st.markdown("### RSS / Atom feeds")
    st.caption("No credentials required. Feeds that fail are recorded and skipped.")
    feeds = cfg.feeds.get("feeds", [])
    frame = pd.DataFrame(feeds) if feeds else pd.DataFrame(
        columns=["name", "url", "category", "industry", "enabled"]
    )
    edited = st.data_editor(
        frame, num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "name": st.column_config.TextColumn("Name", required=True),
            "url": st.column_config.TextColumn("Feed URL", required=True),
            "category": st.column_config.SelectboxColumn("Category", options=cfg.categories),
            "industry": st.column_config.SelectboxColumn("Industry", options=cfg.industries),
            "enabled": st.column_config.CheckboxColumn("Enabled", default=True),
        },
        key="feeds_editor",
    )
    if st.button("Save feeds"):
        payload = {"feeds": [
            {"name": r.get("name"), "url": r.get("url"), "category": r.get("category"),
             "industry": r.get("industry"), "enabled": bool(r.get("enabled", True))}
            for r in edited.to_dict("records") if r.get("url")
        ]}
        write_yaml("feeds.yaml", payload)
        reload_config()
        st.success(f"Saved {len(payload['feeds'])} feed(s) to config/feeds.yaml.")
        st.rerun()

    if st.button("Verify all feeds now"):
        import feedparser

        rows = []
        with st.spinner("Fetching each feed…"):
            for feed in cfg.feeds.get("feeds", []):
                try:
                    parsed = feedparser.parse(feed["url"], agent=cfg.crawl.user_agent)
                    rows.append({
                        "name": feed.get("name"),
                        "entries": len(parsed.entries),
                        "status": getattr(parsed, "status", "?"),
                        "ok": len(parsed.entries) > 0,
                        "note": str(getattr(parsed, "bozo_exception", ""))[:80],
                    })
                except Exception as exc:  # noqa: BLE001
                    rows.append({"name": feed.get("name"), "entries": 0, "status": "error",
                                 "ok": False, "note": str(exc)[:80]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# ── domains & crawl ─────────────────────────────────────────────────────────
with tabs[3]:
    st.markdown("### Allowed domains")
    st.caption("First-party crawling only ever touches these hosts.")
    allowed = st.text_area(
        "One per line", "\n".join(sorted(cfg.allowed_domains)), height=130
    )
    st.markdown("### Blocked domains")
    st.caption(
        "Never fetched programmatically, regardless of the allowlist. LinkedIn content "
        "enters only through the manual Voice Library form."
    )
    blocked = st.text_area(
        "One per line ", "\n".join(sorted(cfg.blocked_domains)), height=110
    )

    st.markdown("### Podium seed sections")
    sections = cfg.podium_sections
    st.caption(f"{len(sections)} section(s) configured in `config/sources.yaml`.")
    st.dataframe(
        pd.DataFrame([
            {"Section": s.get("name"), "Category": s.get("category"),
             "Follow links": s.get("follow_links"), "Seeds": len(s.get("seeds", []))}
            for s in sections
        ]),
        hide_index=True, width="stretch",
    )

    st.markdown("### Crawl etiquette")
    c1, c2, c3 = st.columns(3)
    delay = c1.number_input("Per-domain delay (s)", 0.0, 30.0, float(cfg.crawl.delay_seconds), 0.5)
    timeout = c2.number_input("Request timeout (s)", 5, 120, int(cfg.crawl.request_timeout))
    max_sources = c3.number_input("Max sources per run", 10, 500, int(cfg.crawl.max_sources_per_run), 10)
    c4, c5 = st.columns(2)
    respect_robots = c4.checkbox("Respect robots.txt", value=cfg.crawl.respect_robots)
    max_pages = c5.number_input("Max pages per Podium section", 1, 60,
                                int(cfg.crawl.max_pages_per_podium_section))
    user_agent = st.text_input("User agent", cfg.crawl.user_agent)

    if not respect_robots:
        st.error(
            "Disabling robots.txt compliance is strongly discouraged and is not how this "
            "project is intended to run."
        )

    st.markdown("### Discovery windows")
    d1, d2, d3, d4 = st.columns(4)
    lookback = d1.number_input("Lookback days", 1, 365, int(cfg.discovery.lookback_days))
    per_query = d2.number_input("Results per query", 1, 30, int(cfg.discovery.search_results_per_query))
    per_feed = d3.number_input("Items per feed", 1, 50, int(cfg.discovery.rss_items_per_feed))
    per_video = d4.number_input("Videos per query", 1, 30, int(cfg.discovery.youtube_results_per_query))

    if st.button("Save crawl settings"):
        sources_payload = dict(cfg.sources)
        sources_payload["allowed_domains"] = [d.strip() for d in allowed.splitlines() if d.strip()]
        sources_payload["blocked_domains"] = [d.strip() for d in blocked.splitlines() if d.strip()]
        write_yaml("sources.yaml", sources_payload)

        settings_payload = {
            "crawl": {
                "delay_seconds": float(delay), "request_timeout": int(timeout),
                "respect_robots": bool(respect_robots),
                "max_sources_per_run": int(max_sources),
                "max_pages_per_podium_section": int(max_pages),
                "user_agent": user_agent,
            },
            "ai": {
                "model": cfg.ai.model, "temperature": cfg.ai.temperature,
                "max_extraction_chars": cfg.ai.max_extraction_chars,
                "enable_llm": cfg.ai.enable_llm,
            },
            "discovery": {
                "lookback_days": int(lookback),
                "search_results_per_query": int(per_query),
                "rss_items_per_feed": int(per_feed),
                "youtube_results_per_query": int(per_video),
            },
            "trends": {
                "current_period_days": cfg.trends.current_period_days,
                "previous_period_days": cfg.trends.previous_period_days,
                "min_sources_for_trend": cfg.trends.min_sources_for_trend,
                "min_domains_for_trend": cfg.trends.min_domains_for_trend,
            },
            "pipeline": {
                "min_opportunity_score": cfg.pipeline.min_opportunity_score,
                "max_opportunities_per_run": cfg.pipeline.max_opportunities_per_run,
            },
        }
        write_yaml("settings.yaml", settings_payload)
        reload_config()
        st.success("Crawl settings saved.")
        st.rerun()

# ── model & scoring ─────────────────────────────────────────────────────────
with tabs[4]:
    st.markdown("### OpenAI model")
    c1, c2, c3 = st.columns(3)
    model = c1.text_input("Model", cfg.ai.model)
    temperature = c2.number_input("Temperature", 0.0, 1.5, float(cfg.ai.temperature), 0.1)
    max_chars = c3.number_input("Max extraction chars", 2000, 60000,
                                int(cfg.ai.max_extraction_chars), 1000)
    enable_llm = st.checkbox(
        "Enable the LLM backend when a key is present", value=cfg.ai.enable_llm,
        help="Turn off to force the deterministic heuristic analyser everywhere.",
    )

    st.markdown("### Opportunity scoring weights")
    st.caption("Weights are normalised before use, so they need not sum to exactly 1.0.")
    weights = cfg.scoring_weights or {}
    w1, w2, w3 = st.columns(3)
    w_podium = w1.slider("Podium relevance", 0.0, 0.5, float(weights.get("podium_relevance", 0.25)), 0.01)
    w_founder = w2.slider("Founder relevance", 0.0, 0.5, float(weights.get("founder_relevance", 0.20)), 0.01)
    w_evidence = w3.slider("Evidence strength", 0.0, 0.5, float(weights.get("evidence_strength", 0.20)), 0.01)
    w4, w5, w6 = st.columns(3)
    w_fresh = w4.slider("Freshness", 0.0, 0.5, float(weights.get("freshness", 0.15)), 0.01)
    w_novel = w5.slider("Novelty", 0.0, 0.5, float(weights.get("novelty", 0.10)), 0.01)
    w_impact = w6.slider("Business impact", 0.0, 0.5, float(weights.get("business_impact", 0.10)), 0.01)
    total = w_podium + w_founder + w_evidence + w_fresh + w_novel + w_impact
    st.caption(f"Sum: {total:.2f} (normalised to 1.00 at scoring time)")

    st.markdown("### Trend and pipeline thresholds")
    t1, t2, t3, t4 = st.columns(4)
    current_days = t1.number_input("Current period (days)", 1, 180, int(cfg.trends.current_period_days))
    previous_days = t2.number_input("Previous period (days)", 1, 180, int(cfg.trends.previous_period_days))
    min_sources = t3.number_input("Min sources for a trend", 1, 20, int(cfg.trends.min_sources_for_trend))
    min_domains = t4.number_input("Min domains for a trend", 1, 20, int(cfg.trends.min_domains_for_trend))
    p1, p2 = st.columns(2)
    min_score = p1.number_input("Min opportunity score to promote", 0, 100,
                                int(cfg.pipeline.min_opportunity_score))
    max_opps = p2.number_input("Max opportunities per run", 1, 50,
                               int(cfg.pipeline.max_opportunities_per_run))

    if st.button("Save model & scoring"):
        scoring_payload = dict(cfg.scoring)
        scoring_payload["weights"] = {
            "podium_relevance": w_podium, "founder_relevance": w_founder,
            "evidence_strength": w_evidence, "freshness": w_fresh,
            "novelty": w_novel, "business_impact": w_impact,
        }
        write_yaml("scoring.yaml", scoring_payload)

        settings_payload = {
            "crawl": {
                "delay_seconds": cfg.crawl.delay_seconds,
                "request_timeout": cfg.crawl.request_timeout,
                "respect_robots": cfg.crawl.respect_robots,
                "max_sources_per_run": cfg.crawl.max_sources_per_run,
                "max_pages_per_podium_section": cfg.crawl.max_pages_per_podium_section,
                "user_agent": cfg.crawl.user_agent,
            },
            "ai": {
                "model": model, "temperature": float(temperature),
                "max_extraction_chars": int(max_chars), "enable_llm": bool(enable_llm),
            },
            "discovery": {
                "lookback_days": cfg.discovery.lookback_days,
                "search_results_per_query": cfg.discovery.search_results_per_query,
                "rss_items_per_feed": cfg.discovery.rss_items_per_feed,
                "youtube_results_per_query": cfg.discovery.youtube_results_per_query,
            },
            "trends": {
                "current_period_days": int(current_days),
                "previous_period_days": int(previous_days),
                "min_sources_for_trend": int(min_sources),
                "min_domains_for_trend": int(min_domains),
            },
            "pipeline": {
                "min_opportunity_score": int(min_score),
                "max_opportunities_per_run": int(max_opps),
            },
        }
        write_yaml("settings.yaml", settings_payload)
        reload_config()
        st.success("Saved. Re-run trend analysis and brief generation to apply the new weights.")
        st.rerun()

    with st.expander("Full scoring configuration (risk factors and bands)"):
        st.code(yaml.safe_dump(cfg.scoring, sort_keys=False), language="yaml")

# ── prompts ─────────────────────────────────────────────────────────────────
with tabs[5]:
    st.markdown("### AI prompts")
    st.caption(
        "Every prompt is a file in `prompts/`, not a string buried in the code. "
        "`_shared_rules.md` is prepended to all of them, so the anti-hallucination contract "
        "cannot be edited out of a single prompt by accident."
    )
    st.dataframe(pd.DataFrame(PromptLibrary.status()), hide_index=True, width="stretch")

    with st.expander("Shared integrity rules (applied to every prompt)"):
        st.markdown(PromptLibrary.read_shared_rules())

    name = st.selectbox("Edit a prompt", PromptLibrary.names())
    body = st.text_area("Prompt body", PromptLibrary.read(name), height=460, key=f"prompt_{name}")
    if st.button("Save prompt"):
        PromptLibrary.write(name, body)
        st.success(f"Saved prompts/{name}.md")

# ── run history ─────────────────────────────────────────────────────────────
with tabs[6]:
    st.markdown("### Pipeline runs")
    st.caption(
        "The same code path runs from the dashboard button, "
        "`python scripts/run_discovery.py`, and the scheduled GitHub Action."
    )
    runs = recent_runs(25)
    if not runs:
        st.caption("No runs recorded yet.")
    else:
        st.dataframe(
            pd.DataFrame(runs)[[
                "id", "trigger", "started_at", "finished_at", "stored", "duplicates",
                "signals", "themes", "opportunities", "errors",
            ]].rename(columns={
                "id": "Run", "trigger": "Trigger", "started_at": "Started",
                "finished_at": "Finished", "stored": "Stored", "duplicates": "Dupes",
                "signals": "Signals", "themes": "Themes",
                "opportunities": "Opportunities", "errors": "Errors",
            }),
            hide_index=True, width="stretch",
        )
        selected = st.selectbox("Inspect a run", [r["id"] for r in runs])
        run = next(r for r in runs if r["id"] == selected)
        st.json(run["stages"])

    st.markdown("### Scheduling")
    st.code(
        "# One-off / cron\n"
        "python scripts/run_discovery.py --max-sources 60\n\n"
        "# Windows Task Scheduler / cron entry (daily at 06:00)\n"
        "0 6 * * *  cd /path/to/founder-content-intelligence && "
        ".venv/bin/python scripts/run_discovery.py\n\n"
        "# GitHub Actions: .github/workflows/discovery.yml (already included)",
        language="bash",
    )
