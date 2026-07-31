# How this maps to the Founder's Associate, Office of the CEO role

*Independent candidate project. Not affiliated with, authorised by, or endorsed
by Podium or Eric Rea.*

A Founder's Associate in the Office of the CEO is a leverage function: you take
work that only exists because the founder's attention is scarce, and you make it
happen at a quality the founder would have produced themselves. This project is
that job, built rather than described.

---

## 1. Build and deploy AI agents and workflows

A five-stage automated pipeline — discovery → extraction → clustering →
scoring → generation — that runs identically from a dashboard button, a CLI
script, and a scheduled GitHub Action, all through one `run_full_pipeline()`.
Two interchangeable analysis backends behind one interface, eleven externalised
prompt files, structured JSON output with schema coercion, retry and graceful
degradation. Deployable to Streamlit Cloud, Render, or Railway with Supabase.

**The judgement on display:** knowing which parts should *not* be an LLM.
Freshness decay, score weighting, trend labelling and risk are arithmetic,
because those are the numbers a decision gets made on and a confabulated number
is worse than no number.

## 2. Capture raw content and insights at scale

40 verified RSS feeds, 9 allowlisted Podium sections including 13 customer case
studies, 16 recurring search queries across 5 pluggable providers, YouTube via
two lawful paths, and a manual-entry route. Four-layer deduplication (canonical
URL → content hash → title similarity → shingle Jaccard) so an article found six
ways is stored once with all six discovery paths preserved.

**The judgement:** the brief said forty good sources beat thousands of weak ones.
So the system caps sources per run, discards bodies under 80 words, and discounts
vendor marketing — it optimises for signal density, not row count.

## 3. Monitor public conversations and industry signals

Coverage across every vertical Podium sells into — automotive retail, home
services, aesthetics, healthcare, retail — plus AI, SaaS and the competitor blogs
of Birdeye, Weave and Thryv. The Engagement Watchlist surfaces conversations
worth a human's attention, with priority, relevance rationale, and a suggested
angle that must add a distinction or a question, never a pitch.

**The judgement:** the watchlist is deliberately incapable of acting. No
automated comment, like, repost, follow, connection or message — and it will
recommend *staying out* of a thread when that is the right answer.

## 4. Identify meaningful trends

Deterministic statistics per theme: source count, distinct domains, distinct
industries, period-over-period change, average relevance, evidence strength and
business impact, recency. Six labels: emerging, rising, stable, declining,
saturated, low confidence.

**The judgement — and the most important design decision in the project:** a
single source is never a trend, and one publisher repeating itself is not
corroboration. Both fall to `low_confidence` by rule. It is trivially easy to
build something that shouts "RISING TREND" at one blog post; that tool would
waste a CEO's time, which is the only resource this role exists to protect.

## 5. Analyse interviews, articles, transcripts, customer stories, announcements

Per source: entities, industries, customer segment, primary and secondary themes,
the customer problem, the main claim, verbatim supporting passages, verbatim
quotes with attribution, numerical claims *with their original sentence*, six
0-10 relevance scores, novelty, promotional-source and familiar-narrative flags,
and verification notes.

Not summarisation. Each cluster answers: why does this matter to Podium, why
could this founder credibly speak to it, what business problem does it reveal, is
this new or repeated, what evidence supports it, what angle exists, what must be
verified, what format fits.

## 6. Organise information into a useful knowledge base

Eight-table schema, portable between SQLite and Supabase Postgres via one
environment variable. Full-text search with filters on date, type, domain,
industry, theme and status; per-source detail separating evidence from
interpretation; extraction errors surfaced; one-click reprocessing.

## 7. Create evidence-backed content opportunities

Briefs carry title, core insight, why now, why Podium, why Eric, audience,
founder POV, hook, 3-5 supporting points *each with source ids and a verbatim
passage*, objections with honest responses, format, CTA, verification checklist,
risk notes and confidence.

**The judgement:** points that cannot be evidenced are **deleted, not softened**.
Softening is how a brief quietly becomes unfalsifiable. And every brief must
argue against itself — `potential_objections` requires at least two genuine
counter-arguments, because a brief that survives no objection is not ready for a
CEO.

## 8. Support founder-led thought leadership

Eight output formats from LinkedIn post to internal briefing note, each linked to
its opportunity and source evidence. Voice alignment derived from manually
approved public examples.

**The judgement:** the voice library refuses to overclaim. With zero examples it
reports that no voice conclusion can be drawn and scores alignment 0 rather than
inventing one. With fewer than five it warns. Default assumptions are only
asserted when the examples actually exhibit them — everything else is listed as
*unconfirmed*. And the customer-story format deliberately produces a **structure
plus interview questions**, never a story, because inventing a customer is the
single most damaging thing a tool like this could do.

## 9. Preserve the original sources behind every recommendation

Canonical URLs on every row; the full set of discovery queries retained; evidence
passages stored with source id, URL and domain; live clickable links from every
brief and draft; a unique constraint on `canonical_url`; and a test asserting that
every brief evidence passage exists verbatim in its cited source.

## 10. Use human approval before anything is published

Seven-stage pipeline status; drafts land in `pending_review`; approve / request
changes / reject with reviewer notes; approved and in-review briefs are never
overwritten by regeneration; a verification checklist that must be worked
through. **The system has no publishing capability at all** — approval records a
human decision, and posting remains a manual act.

---

## What the constraints demanded

No OpenAI key, no search key, and YouTube's public feed endpoint dead from this
network. The response was to build the LLM path properly, unit-test it, and make
the deterministic path good enough to carry a real demo — then say plainly in the
README which parts are unproven.

That is the part of this role that does not appear in a job description: shipping
the complete thing under real constraints, and being straight about where the
edges are, rather than demoing the happy path and hoping nobody checks.

## The one thing to take away

The hard problem is not collecting content. It is that language models confabulate
quotes, statistics and customer stories, and a founder cannot publish what they
cannot verify.

So the guarantee is enforced in code, not in a prompt. Every quote, evidence
passage and numerical claim is re-checked against the stored source text before
it is written to the database. A hallucinating model cannot get a fabricated
quote into this system — its worst case is returning nothing, which lowers the
evidence score, which lowers the opportunity score.

**Fabrication is structurally punished rather than merely discouraged.** That is
the difference between a content tool a founder can use and one they cannot.
