# How this maps to the role

**Founder's Associate, Office of the CEO** — [job posting](https://job-boards.greenhouse.io/podium81/jobs/7967715)

*Independent candidate project. Not affiliated with, authorised by, or endorsed
by Podium or Eric Rea.*

The posting has one line that this repository exists to answer:

> "Deep AI fluency and genuine hunger to build agents and workflows — not just
> a user, a builder; **should be able to show us what they've built or tinkered
> with**."

This is what I built. Below, each responsibility from the posting, mapped to the
running system — and, where the prototype deliberately stops short of the job,
why, and what changes after hire.

---

## "Build and deploy AI agents and workflows to capture raw material at scale; monitor what's being said across channels, surface relevant trends, capture insights from meeting transcripts and customer conversations, and feed the content pipeline."

This sentence *is* the product. A five-stage pipeline — discovery → structured
extraction → theme clustering → transparent scoring → brief/draft generation —
that runs identically from a dashboard button, a CLI, and a scheduled GitHub
Action:

- **Capture at scale:** 36 verified RSS feeds across AI, SaaS, SMB, automotive,
  home services and aesthetics; allowlisted crawling of Podium's public pages;
  web search across five pluggable providers; YouTube via two lawful paths.
  Concurrent fetching across domains with per-domain rate limiting, so a full
  run finishes in minutes while every individual host sees polite traffic.
- **Meeting transcripts and customer conversations:** a dedicated manual-entry
  path (transcript / meeting note / customer insight types) that runs the same
  dedupe and extraction as everything else. In the prototype it's fed by hand;
  in the job it's fed by the calls the posting says I'd be sitting in on.
- **Surface relevant trends:** deterministic theme statistics with six labels —
  and a hard rule that **a single source is never a trend, and one publisher
  repeating itself is not corroboration**. A tool that shouts "rising trend" at
  one blog post wastes exactly the attention this role exists to protect.

## "Write and publish a consistent drumbeat of high-impact, founder-led content… This is the core job."

The system's primary output is the **evidence-linked content brief**: title,
core insight, why now, why Podium, why Eric could credibly say it, founder POV,
hook, 3–5 supporting points *each carrying a source id and a verbatim passage*,
objections, verification checklist, and a transparent 100-point score. From a
brief it generates eight formats — LinkedIn post, short-form video outline,
long-form essay outline, executive talking points, podcast prep, customer-story
structure, engagement comment, internal briefing note.

The judgment on display: **the machine drafts, the human publishes.** Every
draft lands in `pending_review` with a *computed* evidence score and its own
unsupported sentences flagged. Nothing in this system can post anywhere. The
"consistent drumbeat" comes from the associate shipping daily from a pipeline
that always has evidence-backed material ready — not from automation pretending
to be the founder.

## "Own social engagement end-to-end… maintaining a hit list of influential voices in the business, AI, and SMB space."

The **Engagement Watchlist is that hit list**, generated from the corpus:
person/company, the specific recent signal, why it matters, the honest
connection to Podium ("adjacent only" when that's the truth), a suggested
response angle that must add a distinction or a question — never a pitch — a
priority, and risk notes that sometimes say *stay out of this thread*.

One deliberate line: the prototype **suggests, and a human acts**. Automating
comments/likes/reposts on LinkedIn or X violates platform terms, and a
detected-automated founder account is a category-authority write-off. The
workflow the posting asks for is real — it's the associate working the queue
every morning, at a cadence the tool makes sustainable. That's also the
compliant reading of "showing up in the right conversations": *showing up* is
the human part.

## "Develop a distinct founder voice and narrative…"

The Voice Library measures approved public examples — hook structure, sentence
rhythm, use of numbers, customer stories, contrast framing, CTAs — and produces
an editable guide the draft generator scores against. Its defining property is
honesty: with zero examples it says no voice conclusion can be drawn; with
fewer than five it warns; default assumptions the examples don't exhibit are
listed as *unconfirmed*, not asserted. It never claims to imitate anyone — the
label is "founder voice alignment based on approved public examples."

## "Stay obsessively current on trends in AI, SaaS, SMB, and the verticals Podium serves…"

The feed configuration is that sentence turned into YAML: TechCrunch/VentureBeat/
Verge/ZDNet/Latent Space for AI, SaaStr and Sifted for SaaS, seven home-services
trade publications, four automotive-retail outlets, four aesthetics titles —
plus the public blogs of Birdeye, Weave and Thryv, because competitor
positioning is a signal, auto-flagged as vendor marketing so it can never
masquerade as independent evidence. The Daily Brief page compresses it into a
morning read with a Markdown export.

## "Write long-form content when needed: essays, op-eds, bylines…"

The long-form essay outline format produces a thesis, sections each pinned to
source ids, and — critically — sections *labelled `[NEEDS EVIDENCE]`* rather
than padded with plausible-sounding filler when the corpus can't support them.

## "High output, low ego — produces a lot, takes feedback fast, not precious about drafts."

Built into the architecture: every draft ships with its own audit arguing
against it — evidence score computed sentence-by-sentence, unsupported claims
listed, verification items enumerated, banned-hype phrases flagged. Briefs are
required to contain at least two genuine objections to themselves. The system
treats its own output as a starting point for review, which is the only honest
way to treat AI-drafted founder content.

## Nice-to-haves

- *"Experience building agentic content workflows (not just using AI tools, but
  wiring them together)"* — five connectors, two swappable analysis backends,
  eleven externalised prompts, a verbatim evidence gate enforced in code, four-
  layer deduplication, transparent scoring, and one orchestrator shared by UI,
  CLI and scheduler. 211 tests.
- *"Familiarity with vertical industries (auto, home services, healthcare/
  aesthetics)"* — the theme taxonomy, industry classifier, and feed roster are
  built specifically around Podium's verticals, including per-theme negative
  keywords so "after-hours trading" never gets filed under missed customer
  calls.

---

## The one design decision to ask me about

The hard problem in founder content isn't collection — it's that LLMs
confabulate quotes, statistics and customer stories, and a CEO cannot publish
what he can't verify. So the anti-hallucination guarantee is enforced **in
code, not in a prompt**: every quote, passage and figure is re-checked verbatim
against the stored source before the database write; failures are discarded and
the discard recorded. A hallucinating model's worst case is returning nothing —
which lowers the evidence score, which lowers the ranking. **Fabrication is
structurally punished, not politely discouraged.** That's the difference
between a content engine a CEO can trust with his name and one he can't.

---

## Post-hire roadmap: prototype → the actual job

What changes on day one inside the company, in priority order:

1. **Real raw material.** Replace public-web scraping as the primary input with
   what the posting describes: meeting transcripts, customer calls, product
   reviews, front-line interviews — ingested through the transcript path that
   already exists, with consent and internal-use rules replacing the crawler's
   robots.txt rules.
2. **Real founder voice.** Swap the placeholder voice examples for Eric's
   actual public posts and interview transcripts (pasted or API-sourced with
   authorisation), so voice alignment scores mean something.
3. **Official channel APIs.** LinkedIn and X publishing/analytics through their
   sanctioned APIs under company accounts — draft → human approve → publish
   becomes one workflow, with the approval gate kept.
4. **The feedback loop the prototype can't have:** which posts drove inbound,
   deal credibility mentions, and follower-quality growth — fed back into
   opportunity scoring so "what worked" becomes a scoring input.
5. **Engagement cadence:** the watchlist becomes a daily working queue with
   SLAs (reviewed every morning, acted on by a human, logged), and the hit list
   grows from real conversations, not just crawled sources.
6. **Infra:** Supabase + scheduled runs (already built), auth, and the LLM
   backend turned on (already built, verbatim-gated, waiting for a key).

The prototype's constraints — no platform automation, no fabricated voice, no
unverifiable claims — aren't limitations to outgrow. They're the operating
principles that make founder-led content durable, and they carry into the job
unchanged.
