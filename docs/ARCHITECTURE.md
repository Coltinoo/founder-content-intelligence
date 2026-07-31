# Architecture

## Layering

```
┌──────────────────────────────────────────────────────────────────────┐
│  Streamlit UI — streamlit_app.py + pages/1-8                         │
│  Presentational only. Reads through fcie/queries.py, writes through   │
│  pipeline functions. No SQL and no business logic in a page.          │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  Pipeline — fcie/pipeline/                                            │
│  ingest → extract → trends → opportunities → drafts → engagement      │
│  Orchestrated by run.py. Every stage is fault-isolated.               │
└──────┬──────────────────────┬──────────────────────┬─────────────────┘
       │                      │                      │
┌──────▼──────────┐  ┌────────▼─────────┐  ┌─────────▼────────────────┐
│  Connectors     │  │  AI layer        │  │  Scoring                 │
│  podium_site    │  │  client (OpenAI) │  │  opportunity / risk /    │
│  rss            │  │  prompts (files) │  │  confidence / freshness  │
│  web_search     │  │  taxonomy        │  │  Pure functions.         │
│  youtube        │  │  extraction      │  │  No I/O, no LLM.         │
│  manual         │  │   ├ LLMExtractor │  └──────────────────────────┘
└──────┬──────────┘  │   └ Heuristic…   │
       │             └────────┬─────────┘
┌──────▼─────────────────────▼─────────────────────────────────────────┐
│  Utils — urls · hashing · text · dedupe · http · article              │
│  Pure and I/O-isolated. All four dedupe layers and the verbatim       │
│  checker live here, so they are unit-testable without a database.     │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  Persistence — fcie/db.py + fcie/models.py                            │
│  SQLite (dev) ⇄ Supabase Postgres (prod), switched by one env var.    │
└──────────────────────────────────────────────────────────────────────┘
```

## Key decisions

### 1. The verbatim gate is code, not prompt text

`fcie/ai/extraction.py::enforce_verbatim` runs unconditionally on the output of
**both** backends before anything is written. Every quote, evidence passage and
numerical-claim context is re-checked against the source with
`utils/text.py::is_verbatim` (whitespace- and smart-quote-insensitive, minimum
12 characters). Failures are dropped and the drop is recorded in
`verification_notes`.

Consequence: a hallucinating model cannot get a fabricated quote into the
database. Its worst case is an empty evidence list, which lowers
`evidence_strength`, which lowers the opportunity score. **Fabrication is
structurally punished rather than merely discouraged.**

### 2. Two backends behind one interface

`Extractor` picks `LLMExtractor` when `OPENAI_API_KEY` is present and
`ai.enable_llm` is true, otherwise `HeuristicExtractor`. Both return
`ExtractionResult`. `extraction_method` and `extraction_model` are persisted and
surfaced in the UI on every row.

The heuristic backend is not a stub. It slices verbatim evidence with keyword-
ranked sentence selection, matches an 18-theme controlled vocabulary, extracts
quotes by regex with attribution capture, extracts numbers *with their original
sentence*, and derives all six score components from countable text properties.
It is deterministic, so it doubles as the test oracle.

### 3. Scores are computed the same way regardless of backend

The LLM proposes 0-10 component scores; the deterministic weighting in
`pipeline/scoring.py` turns them into the 0-100 total. Freshness is *always*
computed from the publication date, never asked of the model. So LLM and
heuristic rows are directly comparable, and weight changes in Settings apply
uniformly.

### 4. Risk is orthogonal to opportunity

Risk is not subtracted from the opportunity score. A high-value, high-risk item
must stay at the top of the list *with its risk visible*, because that is the
item a founder's associate most needs to see. Averaging them would hide it.

### 5. Facts and interpretation are separated in the schema, not just the UI

`ExtractedSignal` splits into a FACTS block (`primary_claim`,
`supporting_evidence`, `notable_quotes`, `numerical_claims` — all verbatim-gated)
and an INTERPRETATION block (`content_opportunity`, `potential_angle`, relevance
scores). The UI renders them with different visual treatments, and heuristic
interpretation strings are literally prefixed `[Inference]`.

### 6. Deduplication preserves discovery paths

An article found by six queries is one row. The queries that found it accumulate
in `metadata_json.discovered_by_queries`, and `rediscovery_count` increments —
because repeated independent discovery is itself signal, and throwing it away
would lose information the trend layer wants.

### 7. Config is layered and secrets are one-way

YAML in `config/` is the editable surface (Settings page writes it back). `FCIE_*`
env vars override. Secrets are read **only** from the environment and never
written to YAML, so the Settings page cannot leak a key into a committed file.

### 8. Connectors never raise

Every connector returns `ConnectorResult` with `configured`, `setup_message`,
`errors` and `skipped`. A dead feed, a 403, or a missing key produces a visible,
attributable message — never a silent zero. `run_ingestion` catches even a
connector crash and continues.

## Data flow for one source

```
DiscoveredItem (connector)
   → PoliteFetcher.fetch      robots.txt → rate limit → restriction check
   → parse_html               trafilatura, BeautifulSoup fallback, JSON-LD metadata
   → clean_text               whitespace/nav normalisation (raw_text preserved)
   → content_hash             SHA-256 over aggressively normalised text
   → find_duplicate           canonical URL → hash → title → body shingles
        ├─ duplicate → merge_discovery_metadata into the existing row, stop
        └─ new       → INSERT sources
   → Extractor.extract        LLM or heuristic
   → enforce_verbatim         drop anything not present in the source
   → compute_opportunity_score / compute_risk_score
   → INSERT extracted_signals
   → run_trend_analysis       aggregate into themes, label deterministically
   → generate_opportunities   collect evidence → build brief → score → persist
   → generate_draft           write → audit_draft sentence-by-sentence → persist
   → HUMAN APPROVAL           set_approval() — the only path to "approved"
```

## Database

Eight tables. Portable JSON columns (`JSONList`/`JSONDict` encode to `TEXT`) so
SQLite and Postgres behave identically and no dialect-specific type is used.

| Table | Purpose |
|---|---|
| `sources` | retrieved documents, raw + cleaned text, provenance, status |
| `extracted_signals` | structured analysis; facts and interpretation separated |
| `themes` | aggregated clusters with deterministic trend statistics |
| `content_opportunities` | briefs — the primary product output |
| `content_drafts` | format-specific drafts with evidence and voice audits |
| `voice_examples` | manually pasted public examples + measured analysis |
| `engagement_watchlist` | review queue; never actioned by the system |
| `run_log` | per-run observability for scheduled ingestion |

`sources.canonical_url` carries a UNIQUE constraint — the database itself is the
last line of defence against duplicates.

## Failure isolation

| Failure | Behaviour |
|---|---|
| Missing API key | connector reports `configured=False` + setup message; pipeline continues |
| Feed 404 / malformed | recorded in `ConnectorResult.errors`; other feeds unaffected |
| robots.txt disallow | `status='skipped_robots'`, reason stored, never retried around |
| Paywall / login wall / 403 | fetch abandoned, restriction recorded in `fetch_error`, **never bypassed** |
| Body blocked but an RSS summary exists | `status='summary_only'` — the publisher's own syndicated abstract is kept and analysed, with a −2.0 evidence penalty and a mandatory caveat naming the restriction. Lawfully published content is not discarded; the restriction is not circumvented. |
| Body blocked and no usable summary | `status='skipped_restricted'`, stored with its reason, not analysed |
| LLM call fails | falls back to heuristic, records the error in `extraction_error` |
| LLM returns bad JSON | tolerant parse, then retry, then heuristic fallback |
| LLM invents a source id | supporting point dropped in `LLMBriefBuilder.build` |
| Body under 25 words | skipped, `status='needs_review'`, reason stored |
| Unresponsive publisher | every feed and page fetch goes through `httpx` with an explicit timeout, plus a 45s socket-level backstop set in `config.py`. `feedparser`'s own urllib fetcher has **no timeout** and is never used to make the request — we fetch the bytes and hand it a string. |
| Connector crashes | caught in `run_ingestion`, logged, run continues |
| Whole stage crashes | caught in `run_full_pipeline`, recorded, later stages still run |
