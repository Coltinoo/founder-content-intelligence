# Founder Content Intelligence Engine

> **This independent prototype demonstrates how publicly available company, founder, customer, and industry signals can be converted into a source-grounded founder-content pipeline. It is not affiliated with or endorsed by Podium or Eric Rea.**
>
> Nothing in this repository has been written, reviewed, or approved by Eric Rea or anyone at Podium. Every generated draft is an AI-assisted suggestion for human review. Nothing is ever published automatically.

Built as an independent work sample for the [**Founder's Associate, Office of the CEO**](https://job-boards.greenhouse.io/podium81/jobs/7967715) role at Podium — the posting asks for someone who can *"build and deploy AI agents and workflows to capture raw material at scale"* and *"should be able to show us what they've built."* This is that. See [docs/ROLE_MAPPING.md](docs/ROLE_MAPPING.md) for the line-by-line mapping and the post-hire roadmap.

---

## What it does

It ingests genuine public web content — Podium's own pages, ~40 verified RSS feeds across AI, SaaS, automotive, home services, aesthetics and local business, plus optional web-search and YouTube discovery — and turns it into a prioritised, evidence-linked founder-content pipeline.

```
Public sites · RSS · search queries · YouTube · manually approved sources
        ↓  source discovery          ← the agent chooses its own queries
        ↓  polite crawling + article extraction   (robots.txt, rate limits, identified UA)
        ↓  cleaning, normalisation, 4-layer deduplication, metadata
        ↓  AI structured extraction               (facts, claims, quotes, problems, themes)
        ↓  theme clustering + trend detection     (deterministic statistics)
        ↓  transparent relevance + risk scoring   (100-point model, full breakdown shown)
        ↓  founder-content briefs, hooks, drafts, engagement suggestions
        ↓  HUMAN REVIEW AND APPROVAL              ← nothing leaves without this
```

A second entry point takes the raw material a founder generates in a day — a call, an interview, a podcast — and returns structured notes plus post drafts, with every quote checked word-for-word against the transcript. It runs in session and stores nothing, so it is safe to expose in a public demo (`fcie/pipeline/meetings.py`).

It does not summarise articles. For each cluster of signals it answers: *why does this matter to Podium, why could this founder credibly speak to it, what business problem does it reveal, is this new or repeated, what evidence supports it, what angle exists, what must be verified, and what format fits.*

### What is actually in the shipped database

Produced by a real run (`python scripts/report_deliverables.py`), analysed with `gpt-4o-mini`. **The crawl stage — candidate fetches, extraction, trends, briefs, watchlist — finished in 2 minutes 36 seconds**, because fetching is concurrent across unrelated hosts while each host keeps its polite per-domain delay:

| | |
|---|---|
| Sources | **166** across **60 distinct domains** (81 RSS, 51 web search, 34 Podium first-party) |
| Extracted signals | **129** |
| Verbatim evidence passages | **147** — every one re-verified against its source before the write |
| Verbatim quotes | **65** · numerical claims **290**, all flagged for verification |
| Themes | **18** — 2 rising, 7 emerging, 6 saturated, 1 stable, **2 `low_confidence`** |
| Content opportunities | **16** promoted (6 themes evaluated and skipped, with reasons) |
| Drafts | **9**, all `pending_review` |
| Access-restricted, not bypassed | **35** |

The `low_confidence` label is the point, not a gap: *Customer reactivation* and *Human-to-AI handoffs* each rest on **1 source from 1 domain**, so the system refuses to call either a trend.

The counts above move with every run. The claim worth checking is not the totals — it is that **147 of 147** stored passages verified verbatim against their source text, because the ones that did not verify were discarded rather than stored.

---

## The core design decision: evidence you can check

The hard problem in this category is not collecting content — it is that language models confabulate quotes, statistics and customer stories, and a founder cannot publish something they cannot verify.

So the anti-hallucination guarantee is enforced **in code, not just in the prompt**:

- Every quote, evidence passage and numerical claim is re-checked against the stored source text with `is_verbatim()` **before it is written to the database** (`fcie/ai/extraction.py::enforce_verbatim`).
- Anything that fails is **discarded**, and the discard is recorded in `verification_notes`.
- A hallucinating model therefore cannot get a fabricated quote into the system — the worst it can do is produce an empty evidence list, which lowers the score.
- Brief supporting points with no valid source id **or** no matching stored passage are dropped, not softened (`opportunities.py::LLMBriefBuilder.build`).
- The UI renders facts (teal rule) and AI interpretation (gold rule) with different visual treatment, and every inference field is prefixed `[Inference]`.
- Drafts are audited sentence by sentence; the `evidence_score` is *computed* as supported ÷ factual sentences, not estimated.

Two interchangeable analysis backends sit behind one interface:

| | **LLM backend** | **Heuristic backend** |
|---|---|---|
| Requires | `OPENAI_API_KEY` | nothing |
| Extraction | structured JSON via editable prompts | deterministic rules |
| Quotes/evidence | model-proposed, **verbatim-gated** | sliced verbatim from source |
| Scoring | model proposes 0-10 components, weights applied deterministically | rule-derived components, same weighting |
| Reproducible | no | yes |

Which backend produced every row is stored and always shown in the UI. The heuristic backend exists so the product is fully demonstrable and testable without credentials, and so every LLM output has a non-LLM baseline.

---

## Quick start

```bash
git clone <this-repo> && cd founder-content-intelligence
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
cp .env.example .env             # optional — the app runs with no keys at all
python scripts/init_db.py
python scripts/run_discovery.py --quick   # demo-sized run, ~2 minutes
streamlit run streamlit_app.py
```

Drop `--quick` for a full run. Fetching is concurrent across unrelated domains
while each individual host stays politely rate-limited, so a full run is
minutes, not tens of minutes. The dashboard's *Run discovery* has the same
quick/standard choice.

Open http://localhost:8501.

**The app runs with zero credentials.** RSS and first-party crawling need none; the analysis falls back to the deterministic backend. Every unconfigured integration is displayed in the sidebar and on Settings with the exact variable to set — nothing fails silently.

---

## Environment variables

All optional. See [`.env.example`](.env.example).

| Variable | Purpose | Without it |
|---|---|---|
| `FCIE_DATABASE_URL` | Supabase/Postgres connection string | local SQLite at `data/fcie.db` |
| `OPENAI_API_KEY` | LLM extraction, briefs, drafts | deterministic heuristic backend |
| `FCIE_OPENAI_MODEL` | model id (default `gpt-4o-mini`) | default |
| `TAVILY_API_KEY` / `BRAVE_SEARCH_API_KEY` / `BING_SEARCH_API_KEY` / `GOOGLE_CSE_API_KEY`+`GOOGLE_CSE_CX` | recurring web-search queries (first configured wins) | search discovery skipped with a setup message |
| `FCIE_OPENAI_WEB_SEARCH=1` | use the OpenAI Responses `web_search` tool instead | — |
| `YOUTUBE_API_KEY` | keyword video discovery | falls back to public channel Atom feeds |
| `FCIE_USER_AGENT`, `FCIE_CRAWL_DELAY_SECONDS`, `FCIE_RESPECT_ROBOTS`, `FCIE_REQUEST_TIMEOUT`, `FCIE_MAX_SOURCES_PER_RUN` | crawler etiquette | sensible defaults |

No secret is ever read from a YAML file or committed.

---

## Project structure

```
founder-content-intelligence/
├── streamlit_app.py              # Executive Dashboard (entry point)
├── pages/                        # 1 Daily Brief · 2 Meeting to Content
│                                 # 3 Source Library
├── _pages_advanced/              # Trend Radar, Content Pipeline, Content Brief,
│                                 # Watchlist, Voice Library, Settings — complete and
│                                 # tested, kept out of pages/ so the nav stays at four
├── fcie/
│   ├── config.py                 # layered YAML + env config, integration status
│   ├── db.py                     # SQLite ⇄ Supabase abstraction
│   ├── models.py                 # 8 SQLAlchemy models, dialect-neutral JSON columns
│   ├── queries.py                # read-only dashboard queries
│   ├── connectors/               # base · podium_site · rss · web_search · youtube · manual
│   ├── ai/
│   │   ├── client.py             # OpenAI wrapper, never raises on a missing key
│   │   ├── prompts.py            # loads prompts/*.md, prepends shared rules
│   │   ├── taxonomy.py           # 18-theme controlled vocabulary + entity dictionary
│   │   └── extraction.py         # LLM + heuristic backends, verbatim gate
│   ├── pipeline/
│   │   ├── ingest.py             # discover → fetch → clean → dedupe → store
│   │   ├── extract.py            # structured signal extraction
│   │   ├── trends.py             # deterministic theme statistics + labelling
│   │   ├── scoring.py            # 100-point opportunity model + risk + confidence
│   │   ├── opportunities.py      # content brief generation
│   │   ├── drafts.py             # draft writing + sentence-level evidence audit
│   │   ├── voice.py              # manual voice library + derived guide
│   │   ├── engagement.py         # watchlist (review only, never automated)
│   │   ├── brief_export.py       # daily brief + Markdown export
│   │   └── run.py                # full-pipeline orchestrator
│   ├── ui/components.py          # shared Streamlit components
│   └── utils/                    # urls · hashing · text · dedupe · http · article
├── prompts/                      # 11 editable prompt files + _shared_rules.md
├── config/                       # settings · scoring · sources · queries · feeds (YAML)
├── scripts/                      # init_db · run_discovery · verify_feeds · verify_youtube
├── tests/                        # 211 tests
└── .github/workflows/discovery.yml
```

---

## Data sources implemented

| Connector | Credentials | Status |
|---|---|---|
| **Podium first-party crawl** | none | 9 allowlisted sections — About, Careers, AI Employee, product pages, 13 customer case studies, Resource Center/blog, 4 industry pages, release notes, press/guides, public job board. Allowlisted-domain only, robots.txt enforced. |
| **RSS / Atom** | none | 36 working feeds (39 configured, 3 disabled because they 403 this client — not worked around), each verified by `scripts/verify_feeds.py`: AI/tech, SaaS, small business, automotive, home services, aesthetics, retail/CX, and competitor blogs (Birdeye, Weave, Thryv — auto-flagged as vendor marketing). |
| **Web search** | one of 5 providers | Tavily, Brave, Bing, Google CSE, or OpenAI Responses `web_search`. 16 recurring queries in `config/queries.yaml`, editable in the dashboard. **Search-engine result pages are never scraped.** |
| **YouTube** | `YOUTUBE_API_KEY` (optional) | Data API keyword search + `videos.list` metadata + caption *availability* check. Falls back to public per-channel Atom feeds. Transcripts only via lawful, supported routes — unavailable captions are never bypassed. |
| **Manual entry** | none | URL, pasted text, public social post, transcript, meeting note, customer insight. The lawful route for LinkedIn content. |

---

## Ethics & platform compliance

Enforced in code, not just documented:

- **robots.txt** fetched and cached per host; a disallow is fatal for that URL and recorded as `skipped_robots` (`utils/http.py::RobotsCache`).
- **`Crawl-delay`** from robots.txt overrides our configured delay when it is larger.
- **Per-domain rate limiting** — 2s default between requests to the same host.
- **Identified user agent**, contactable and descriptive.
- **Allowlisted crawling only** — first-party crawling touches only hosts in `allowed_domains`.
- **Access restrictions are never bypassed.** HTTP 401/402/403/407/451 and login-wall, paywall or captcha markers abandon the fetch and record the restriction. There is no captcha handling, no cookie injection, no header spoofing, no retry with a spoofed user agent.
  - Where a publisher blocks the article body but syndicates a full summary in its own RSS feed, that summary is kept and analysed as `summary_only` — carrying a −2.0 evidence penalty and a mandatory caveat naming the restriction. The restriction is respected; the content the publisher chose to syndicate is not thrown away.
- **LinkedIn, X, Facebook, Instagram, TikTok, Threads are on a hard blocklist** and refused before any request, regardless of the allowlist. There is no LinkedIn scraper, and no LinkedIn action — comment, like, repost, connect, message — is ever automated.
- **The engagement watchlist recommends only.** It links to sources already in the library and never constructs or looks up a profile URL.
- **No fabricated quotations, statistics, customer stories or attributions** — see the verbatim gate above.
- **Facts are stored separately from interpretation** and rendered differently.
- **Every major claim stores its evidence**; claims needing verification are flagged; inferences are labelled.
- **Human approval is required** before anything is publication-ready.
- **No claim of endorsement.** The disclaimer appears on every page and in every export.

---

## Scoring methodology

**Opportunity score (0-100)** — `config/scoring.yaml`, editable in Settings. Weights are normalised, so they need not sum to 1.

| Component | Weight | Meaning |
|---|---|---|
| Podium relevance | 25% | how directly this bears on Podium's market and product |
| Founder relevance | 20% | how credibly a local-business SaaS founder could speak to it |
| Evidence strength | 20% | quality of the customer/market evidence in the source |
| Freshness | 15% | linear decay: 10 at ≤7 days → 0 at ≥120 days; **4 with an explicit flag when undated** |
| Novelty | 10% | new data point vs repeated narrative |
| Business impact | 10% | size of the commercial problem implied |

`score = Σ(component₀₋₁₀ × normalised_weight) × 10`. The full per-component breakdown is stored and displayed.

**Risk score (0-100), scored independently** — deliberately *not* subtracted from opportunity, so a high-value, high-risk item stays visible instead of being averaged away. Additive factors: weak sourcing (18), unverified numbers (16), competitor claims (14), sensitive claims (14), promotional source (10), overused narrative (10), no original insight (10), generic tone (8), missing publication date (6). Bands: Low ≤24, Moderate ≤49, Elevated ≤74, High >74.

**Confidence (0-100)** — how well-supported the brief is, separate from how attractive it is: distinct domains (30), verbatim passages (25), average evidence strength (30), source volume (15); ×0.65 for a single-domain evidence base, ×0.9 when no source is dated.

**Trend labelling** — deterministic, and *a single source is never a trend*:

| Label | Rule |
|---|---|
| `low_confidence` | < `min_sources_for_trend` (2) sources **or** < `min_domains_for_trend` (2) distinct domains |
| `emerging` | first seen inside the current period and already at threshold |
| `rising` | ≥3 sources this period **and** ≥50% growth over the previous period |
| `saturated` | ≥6 sources but average novelty < 4/10 |
| `declining` | ≥2 sources last period and ≥40% decline |
| `stable` | everything else |

---

## Deduplication

Four layers, cheapest first (`utils/dedupe.py`). An article found by six different queries produces **one** row, while every query that surfaced it is preserved in `metadata_json.discovered_by_queries`.

1. **Canonical URL** — after normalisation (scheme, `www.`, 30+ tracking params, fragment, trailing slash, default ports, `index.html`, param sorting; `http`/`https` collapse to one identity), plus the page's own `<link rel=canonical>` when same-host.
2. **Content hash** — SHA-256 over aggressively normalised text (unicode NFKC, smart quotes, boilerplate stripped).
3. **Title similarity** — `token_set_ratio` ≥ 92, with site suffixes stripped and titles under 4 words never matched (so every "About" page on a marketing site does not collapse into one).
4. **Body near-duplicate** — 5-word shingle Jaccard ≥ 0.72, for syndicated reprints and mirrored press releases.

---

## AI prompts

Eleven editable prompt files in `prompts/`, never string literals in code, all editable from Settings → Prompts:

`source_extraction` · `claim_evidence` · `theme_classification` · `trend_analysis` · `opportunity_scoring` · `brief_generation` · `voice_analysis` · `linkedin_draft` · `longform_outline` · `engagement_recommendation` · `factcheck_review`

`prompts/_shared_rules.md` is prepended to **all** of them, so the ten absolute integrity rules (never invent a quote, never rewrite a quote, never invent a statistic or customer, never present inference as fact, every claim needs a passage, state missing dates, flag promotional sources, flag unverifiable claims, do not be overconfident, never imply endorsement) cannot be edited out of one prompt by accident.

---

## Founder voice library

Public examples are added **only by a human pasting public text and its URL**. Nothing is scraped.

The engine measures hook structure, sentence and paragraph length, vocabulary, confidence, use of numbers, customer stories, contrast constructions, founder experience, recurring themes, tone, audience, CTAs and technical depth — then produces an editable guide labelled **"Founder voice alignment based on approved public examples."**

Critically, the default assumptions (direct, commercially focused, optimistic about AI, short paragraphs, avoids hype, prefers measurable impact…) are **only asserted when the approved examples actually exhibit them**. Everything else is listed under *unsupported assumptions*. With fewer than five examples a coverage warning is mandatory, and with zero examples the system reports that no voice conclusion can be drawn and scores voice alignment 0 rather than inventing one. The system never claims to imitate any individual.

---

## Scheduling

The dashboard button, the CLI and the GitHub Action all call the same `run_full_pipeline()`.

```bash
python scripts/run_discovery.py --max-sources 60
python scripts/run_discovery.py --stage ingest --stage extract --json
python scripts/run_discovery.py --force-heuristic --no-search
```

```cron
0 6 * * 1-5  cd /path/to/founder-content-intelligence && .venv/bin/python scripts/run_discovery.py
```

[`.github/workflows/discovery.yml`](.github/workflows/discovery.yml) runs weekdays at 06:00 UTC with `workflow_dispatch`, uploads a JSON run summary, and warns when `FCIE_DATABASE_URL` is unset (ephemeral SQLite would discard the results).

---

## Deployment

**Streamlit Community Cloud** (simplest)
1. Push to GitHub → share.streamlit.io → point at `streamlit_app.py`.
2. Add secrets under *App settings → Secrets* (same names as `.env`).
3. Set `FCIE_DATABASE_URL` to Supabase — the container filesystem is ephemeral, so SQLite would be lost on restart.
4. Schedule ingestion with the included GitHub Action; the app reads the shared database.

**Render / Railway**
```
Build:  pip install -r requirements.txt
Start:  streamlit run streamlit_app.py --server.port $PORT --server.address 0.0.0.0
```
Set the same environment variables. Add a Render Cron Job / Railway cron running `python scripts/run_discovery.py`.

**Supabase** — create a project, take the session-pooler URI, set `FCIE_DATABASE_URL=postgresql+psycopg2://...`, run `python scripts/init_db.py`. No code changes; the ORM is dialect-neutral.

---

## Testing

```bash
python -m pytest tests -q
```

211 tests covering URL normalisation and canonicalisation, content hashing and near-duplicate similarity, all four dedupe layers plus rediscovery merging, the verbatim gate (fabricated quotes/passages/numbers are dropped), heuristic extraction completeness and determinism, LLM output coercion (out-of-taxonomy themes rejected, scores clamped, placeholders nulled), score/risk/confidence calculation, missing-API-key behaviour, unsupported-source handling (blocked domains, non-HTTP schemes, unknown prompts), database creation and JSON round-trips, ingest-time deduplication, channel interleaving (undated first-party sources must not be starved by dated feed items), bounded feed fetching, restricted-body handling (`summary_only`), draft attribution (a verbatim source sentence is never rendered as the author's own words), trend guards (single source and single domain are never trends), voice-library honesty, and brief↔source linkage (every brief evidence passage must exist verbatim in its cited source).

---

## Known limitations

These are the honest edges of the build, several discovered by actually running it.

1. **No LLM key was available while building this.** The whole corpus was processed on the deterministic backend. The LLM path is fully implemented, coerced, verbatim-gated and unit-tested, but its live output quality is unproven. Heuristic briefs are honest and evidence-linked but **templated** — the framing sentences ("My read: …", the scope summary) are formulaic, which is exactly why they show up as *unsupported* in the draft audit. A key improves the prose, not the evidence.
2. **No search-API key was available**, so recurring query discovery never ran. The connector is implemented for five providers; the corpus here comes from first-party crawling and RSS only.
3. **YouTube's public Atom endpoint returned HTTP 404 for every channel ID from this network** — including known-good channels, so it is not a bad channel ID. The no-credential fallback therefore yielded nothing. Both paths are implemented; the Data API path is untested against a live key. The connector reports the failure rather than hiding it.
4. **The corpus skews heavily to first-party content.** 29 of 74 sources are Podium's own pages, because they are reliably crawlable while much trade media is not. Every one is flagged `is_promotional_source`, discounted 2.5 points of evidence strength, and counted separately in each brief ("N of those sources are independent of any vendor") — but a brief built mostly on vendor pages is weak, and the system says so rather than hiding it. **The top-ranked opportunity in the current database is exactly this case**: score 70, but confidence 50 and risk 74, with "2 of 2 sources are vendor marketing" in its risk notes.
5. **Theme assignment is keyword-based.** Word-boundary matching and per-theme negative keywords fixed the worst failures (`"spa"` matching *space*; "after-hours **trading**" filed under missed calls), but it will still miss a theme expressed in unusual vocabulary. Secondary themes carry half weight in trend averages to limit the damage.
6. **Publication dates are frequently missing** from marketing pages — none of the Podium case studies carry one. These score 4/10 freshness, are explicitly flagged, and block any recency claim.
7. **Body extraction still leaks some page furniture.** `looks_like_prose()` rejects CTAs, shouty banners, title-case navigation and obfuscated paywall text, but marketing pages occasionally yield a feature-list line that reads like a sentence. The number extractor also picks up list artefacts (`"22,"`), which land in the verification checklist as noise.
8. **Ten sources were access-restricted** (Inc., Dermatology Times). Nothing was bypassed; where the publisher syndicated a summary it was kept as `summary_only` with an evidence penalty, otherwise the row records the refusal.
9. **No semantic embedding deduplication.** Layer 4 is lexical shingling, which catches reprints but not a genuine paraphrase.
10. **Voice alignment is a style-distance metric**, measured against a small manual sample — not a judgement of authenticity. The six seeded examples are Podium *company* content, clearly labelled as not verified as founder writing.
11. **Politeness now costs minutes, not tens of minutes.** Fetching is concurrent across unrelated hosts while each host keeps its per-domain delay, and extreme robots `Crawl-delay` values (searchengineland.com declares 600s/page) are honoured by *deferring* those items to a future run — or keeping the publisher's own RSS summary — rather than sleeping behind them. A host that effectively forbids bulk crawling therefore contributes little content per run; that is its choice, respected.
12. **Single-process Streamlit with no auth.** Fine for a demo; not multi-tenant, no user accounts, **not production-ready**.

## Future improvements

- Embedding-based clustering and semantic dedupe (pgvector on Supabase).
- A real fact-check pass wiring `prompts/factcheck_review.md` into the draft gate as a blocking check.
- Cross-source corroboration scoring: reward a claim two independent domains state, penalise a single-vendor claim.
- Historical theme time-series so the Trend Radar shows trajectory rather than one comparison.
- Named-entity linking to a company/person registry instead of a keyword dictionary.
- Draft revision loops that feed reviewer notes back into regeneration.
- Slack/email delivery of the daily brief.
- Per-user auth and an audit trail of approval decisions.

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layering, the eight key design decisions, per-source data flow, failure-isolation table |
| [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) | Every connector, the compliance rules enforced in code, and the provenance stored per source |
| [`docs/SCORING.md`](docs/SCORING.md) | Opportunity, risk, confidence, freshness, trend labelling, evidence and voice scoring — with formulas |
| [`docs/PROMPTS.md`](docs/PROMPTS.md) | The shared integrity contract and all eleven prompts |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Streamlit Cloud, Supabase, Render, Railway, Docker, scheduling, checklist |
| [`docs/DEMO.md`](docs/DEMO.md) | Two-minute demo script, plus answers to the questions it invites |
| [`docs/ROLE_MAPPING.md`](docs/ROLE_MAPPING.md) | How each capability maps to the Founder's Associate role |

## Demo

See [`docs/DEMO.md`](docs/DEMO.md) for the full two-minute script, or:

1. **Dashboard** → *How it works* in four steps, then what it found, then the one
   idea to write today.
2. Scroll to **The agent, and what it did** → 550 candidates considered, 60 kept,
   79 duplicates merged, 49 refused on policy; where it looked, and the twelve
   queries it chose to run. Read from the run log, not asserted in prose.
3. **Daily Brief** → what arrived since the last run, then the strongest thing to
   publish, its draft posts, and the exact source quote behind every point.
4. Note the honesty: our own pages are labelled and excluded from corroboration,
   and a draft scoring 6/100 says so rather than hiding it.
5. **Meeting to Content** → paste any transcript (a synthetic sample is loaded)
   → notes, decisions, action items, verbatim-checked quotes, and post drafts.
   Nothing is stored, which is why it is live in a read-only demo.
6. **Source Library** → every page, who wrote it, and the query that found it.

---

*Independent candidate project. Not affiliated with, authorised by, or endorsed by Podium or Eric Rea.*
