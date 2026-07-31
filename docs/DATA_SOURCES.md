# Data sources & platform compliance

Every source in this system is public, lawfully accessible, and fetched under the
constraints below. Compliance is enforced in code (`fcie/utils/http.py`,
`fcie/utils/urls.py`, `config/sources.yaml`), not only described here.

---

## Rules the crawler enforces

| Rule | Where | Behaviour |
|---|---|---|
| `robots.txt` respected | `RobotsCache` | fetched once per host and cached; a disallow is fatal for that URL and stored as `status='skipped_robots'` with the reason |
| `Crawl-delay` honoured | `RobotsCache.crawl_delay` | overrides our configured delay whenever it is larger |
| Per-domain rate limit | `RateLimiter` | 2.0s default between requests to the same host, thread-safe |
| Identified user agent | `PoliteFetcher` | `FounderContentIntelligenceEngine/0.1 (independent candidate project)` — descriptive and contactable |
| Allowlisted crawling | `is_allowed()` | first-party crawling touches only hosts in `allowed_domains`; checked before every request |
| Blocklist wins | `is_allowed()` | blocklist is evaluated *before* the allowlist, so a mistake in the allowlist cannot expose a blocked platform |
| No access-restriction bypass | `_looks_restricted` | HTTP 401/402/403/407/451 and login-wall / paywall / captcha markers abandon the fetch as `skipped_restricted` |
| No captcha handling | — | there is none, by design |
| No header or cookie spoofing | — | one honest UA, no session injection, no `Referer` faking |
| Canonical URLs preserved | `canonicalize()` | the page's own `<link rel=canonical>` is preferred when same-host |
| Source limits | `max_sources_per_run` | default 60 per run, capped in the UI |

### Platforms excluded from all automated collection

`linkedin.com`, `x.com`, `twitter.com`, `facebook.com`, `instagram.com`,
`tiktok.com`, `threads.net`.

These are refused before a request is made. **There is no LinkedIn scraper in
this repository.** No LinkedIn action — comment, like, repost, follow, connect,
message — is ever automated. LinkedIn content enters only when a human copies
public text and pastes it into the Voice Library or the manual source form.

---

## 1. Podium first-party public content

**Credentials:** none. **Domains:** `podium.com`, `job-boards.greenhouse.io`.

Nine allowlisted sections in `config/sources.yaml`. Seed URLs are direct; link
following is capped by `max_pages_per_podium_section` and confined to the same
domain, so this is allowlisted-section crawling rather than a site-wide spider.

| Section | Category | Seeds |
|---|---|---|
| Company / About | `company` | `/about`, `/careers`, `/` |
| AI Employee product | `product_ai_employee` | `/product/ai-employee` (+ follows) |
| Product pages | `product` | `/phones`, `/reviews`, `/payments`, `/pricing` |
| Customer stories | `customer_story` | 13 `/case-study/*` pages across automotive, home services, aesthetics, retail |
| Resource Center / blog | `resource` | `/resource-center`, `/blog`, 8 `/article/*` (+ follows) |
| Industry pages | `industry` | `/automotive`, `/home-services`, `/healthcare`, `/retail` |
| What's New | `whats_new` | `/whats-new` + monthly release notes (+ follows) |
| Press, guides & reports | `press` | `/press`, `/guides/2022-local-business-trends`, `/ebooks/the-new-rules-of-local` |
| Public job descriptions | `jobs` | `job-boards.greenhouse.io/podium81` (+ follows) |

Every seed was verified to return HTTP 200 with real content. Seeds that later
404 are recorded as `skipped` with the reason and do not fail the run.

> **All Podium-owned content is automatically flagged `is_promotional_source`.**
> This reduces `evidence_strength` by 2.5 points and adds a `promotional_source`
> risk factor. Podium's own pages are treated as evidence of *positioning*, not
> evidence of market reality — including the case studies, whose figures are
> vendor-reported and always flagged for verification.

## 2. RSS / Atom feeds

**Credentials:** none. This is the primary zero-credential source of genuine
public data. 39 feeds are configured; **36 return entries** and are enabled.

Feed documents are fetched with `httpx` under our own timeout, rate limiter and
user agent, then handed to `feedparser` as bytes. `feedparser.parse(url)` does
its own HTTP through urllib **with no timeout**, so a single unresponsive
publisher could otherwise hang a scheduled run indefinitely. (Doing the fetch
ourselves also turned a multi-minute verification pass into ~15 seconds.)

Three feeds — **Gartner newsroom, Constant Contact, Dermatology Times** — return
HTTP 403 to this client and are set `enabled: false` with the reason recorded in
`config/feeds.yaml`. They are **not** worked around: no header spoofing, no
proxy, no alternate user agent.

| Vertical | Feeds |
|---|---|
| AI / technology (9) | TechCrunch AI, VentureBeat AI, MIT Technology Review AI, Ars Technica AI, The Verge AI, ZDNet AI, Latent Space, Forrester, Gartner |
| SaaS / B2B (2) | SaaStr, Sifted |
| Small & local business (7) | Small Business Trends, Search Engine Land, Street Fight, Inc., Entrepreneur, SmallBizDaily, Constant Contact |
| Automotive retail (4) | CBT News, Auto Remarketing, Auto Dealer Today, Digital Dealer |
| Home services (7) | ACHR News, Contracting Business, Plumbing & Mechanical, PHCP Pros, Plumber Magazine, HVAC Insider, Housecall Pro |
| Aesthetics / medspa (4) | American Spa, Dermatology Times, Plastic Surgery Practice, Beauty Independent |
| Retail / CX (3) | CX Today, Retail Dive, Modern Retail |
| Competitor blogs (3) | Birdeye, Weave, Thryv |

Competitor blogs are included deliberately — competitor positioning is a signal
the brief explicitly asks for. They are vendor marketing and are flagged as such,
which lowers their evidence weight and raises the risk score of any brief that
leans on them.

Feed items supply title, link, author, date and summary. Article bodies are
fetched separately, subject to robots.txt.

### When an article body is not accessible

Some publishers (Inc. and Dermatology Times, in practice) return HTTP 403 on
article pages while publishing a full summary in their own RSS feed. The system
does two things, and it is worth being precise about the distinction:

- **It does not bypass the restriction.** No retry with a spoofed user agent, no
  cookie injection, no proxy. The 403 is recorded verbatim in `fetch_error`.
- **It does keep the publisher's own syndicated summary**, because that is
  content the publisher deliberately made available for syndication. The row is
  marked `status='summary_only'`, carries a **−2.0 evidence-strength penalty**,
  and every extraction from it gets a mandatory verification note naming the
  restriction and telling the reader to open the original before citing it.

If the summary is under 40 words it is not worth analysing, and the row stays
`skipped_restricted`.

Re-verify at any time:
```bash
python scripts/verify_feeds.py
python scripts/verify_feeds.py --disable-broken
```

## 3. Public web search

**Credentials:** one of five providers, checked in preference order.

| Provider | Variable |
|---|---|
| Tavily | `TAVILY_API_KEY` |
| Brave Search | `BRAVE_SEARCH_API_KEY` |
| Bing Web Search | `BING_SEARCH_API_KEY` (+ `BING_SEARCH_ENDPOINT`) |
| Google Programmable Search | `GOOGLE_CSE_API_KEY` + `GOOGLE_CSE_CX` |
| OpenAI Responses `web_search` | `OPENAI_API_KEY` + `FCIE_OPENAI_WEB_SEARCH=1` |

**Search-engine result pages are never scraped.** All five paths are lawful APIs.
Results are filtered against the blocklist before storage.

Sixteen recurring queries ship in `config/queries.yaml`, editable in Settings:
*Eric Rea · Eric Rea Podium · Podium CEO · Podium AI Employee · Podium AI agents ·
AI employees for local businesses · AI agents for automotive dealerships · AI for
HVAC companies · AI for plumbing companies · AI for medspas · AI for local
business lead response · small business missed calls AI · AI customer follow-up
local business · AI revenue generation local business · agentic AI SaaS · AI
implementation for small businesses.*

When no provider is configured the connector reports `configured=False` with the
exact variables to set, and the rest of the pipeline runs unaffected.

## 4. YouTube

**Two lawful paths. No scraping, no caption bypassing.**

1. **YouTube Data API v3** (`YOUTUBE_API_KEY`) — `search.list` across seven video
   queries, `videos.list` for full snippet metadata, and `contentDetails.caption`
   to record *whether* captions exist.
2. **Public per-channel Atom feeds** (no credentials) —
   `youtube.com/feeds/videos.xml?channel_id=…`, a published unauthenticated
   endpoint.

Stored per video: video id, URL, title, description, channel, channel id,
published date, search query, thumbnail URL, and `transcript_status`
(`captions_available_not_ingested` · `no_captions_published` ·
`not_checked_no_api_key`).

> **Transcripts are only ingested through lawful, supported routes.** When
> captions are unavailable the status is recorded and the connector moves on. It
> never attempts to extract captions YouTube has not made available, and never
> uses a third-party transcript-ripping service.

Resolve a channel id: `python scripts/verify_youtube.py --resolve @handle`

## 5. Manual source entry

**Credentials:** none. The lawful route for anything that cannot be collected
automatically.

Types: public URL with pasted text, pasted text, public social post, transcript,
meeting note, customer insight. Fields: URL, title, author, date, description,
and the text itself.

Nothing here fetches a page — the human supplies the content. Manual sources go
through the same deduplication and extraction path as everything else and are
marked `human_supplied`, with `evidence_strength` reduced 0.5 because the system
has not verified them.

---

## Provenance stored for every source

| Field | Meaning |
|---|---|
| `source_url` / `canonical_url` | as discovered / after normalisation and `rel=canonical` |
| `source_domain` | for grouping and corroboration counting |
| `search_query` | the query that first surfaced it |
| `metadata_json.discovered_by_queries` | **every** query that has surfaced it |
| `metadata_json.discovered_by_channels` | which connectors found it |
| `metadata_json.alternate_urls` | other URLs that resolved to this document |
| `metadata_json.rediscovery_count` | how often it has been rediscovered |
| `metadata_json.duplicate_detections` | which layer matched, its score, and when |
| `content_hash` | SHA-256 over normalised text |
| `status` | `fetched` · `extracted` · `summary_only` · `needs_review` · `error` · `skipped_robots` · `skipped_restricted` · `skipped_blocked_domain` |
| `fetch_error` | the exact reason, never swallowed |
| `raw_text` / `cleaned_text` | original HTML and extracted body, both kept |

Because the canonical URL is preserved on every row, every claim in every brief
resolves to a live, clickable link back to the page it came from.
