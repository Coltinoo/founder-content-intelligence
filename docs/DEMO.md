# Two-minute demo script

For the [Founder's Associate, Office of the CEO](https://job-boards.greenhouse.io/podium81/jobs/7967715)
interview. The posting says the candidate *"should be able to show us what
they've built or tinkered with"* — this walkthrough is that moment, so drive it
yourself rather than narrating screenshots.

**Setup before you present:** run `python scripts/run_discovery.py` at least once
so the library has real data, then `streamlit run streamlit_app.py`.

**Running it live:** the *Quick demo* preset (~25 sources) finishes in about two
minutes — start it at the top of the conversation and let the log scroll while
you talk over it. Fetches run concurrently across unrelated domains while each
host stays politely rate-limited, which is itself worth one sentence: "it's fast
because it parallelises across sites, not because it hammers any one of them."

---

### 0:00 — Frame it (15s)

> "This is an independent prototype — not affiliated with Podium, and nothing in
> it was written or approved by Eric Rea. It takes public signals about Podium,
> its market and its competitors, and turns them into founder-content briefs
> where **every claim links back to the source it came from**. That last part is
> the whole point."

*Executive Dashboard is on screen: sources, domains, extracted signals, themes,
opportunities, drafts pending — plus the sidebar showing exactly which
integrations are configured and which are not.*

### 0:15 — Run discovery (20s)

Open **Run discovery** → press it. Let the live log run for a few seconds.

> "Same code path as the CLI script and the scheduled GitHub Action. It's
> fetching Podium's public pages and forty verified trade and tech feeds —
> respecting robots.txt, rate-limited, identified user agent. Watch it merge
> duplicates: an article found by three different queries becomes one row, but
> all three queries are kept, because repeated independent discovery is signal."

*Don't wait for it to finish — press on with the data already loaded.*

### 0:35 — Trend Radar (25s)

> "Themes are clusters of signals, and the statistics are computed
> deterministically — the model never touches the numbers. The rule that matters:
> **a single source is never a trend, and one publisher repeating itself is not
> corroboration.** Those get labelled low-confidence instead."

Point at the relevance-vs-evidence scatter.

> "Top right is where founder content should come from — high Podium relevance,
> high evidence quality."

Open a rising theme → scroll to supporting sources.

> "Every source behind it, with the verbatim passage that put it in this cluster."

### 1:00 — The brief (35s)

**Content Pipeline** → pick a high-scoring opportunity → **Content Brief Detail**.

> "This is the primary output. Core insight, why now, why it matters to Podium,
> why a founder in this seat could credibly speak to it — and the argument, which
> is labelled as an inference, not a finding."

Scroll to supporting points.

> "Every supporting point carries a source id and the verbatim passage behind it.
> If a point can't be evidenced, it's **dropped** — not softened."

**Score breakdown** tab.

> "Transparent hundred-point model: Podium relevance 25, founder relevance 20,
> evidence 20, freshness 15, novelty 10, impact 10 — and you can change those
> weights in Settings. Risk is scored **separately**, deliberately, so a
> high-value high-risk item stays visible instead of being averaged into the
> middle."

**Verification checklist** tab.

> "Nothing is publication-ready until a human works through this."

### 1:35 — Draft and approval (20s)

**Drafts** tab → generate a LinkedIn post → show the result.

> "Evidence score is *computed* — supported sentences over factual sentences, not
> a vibe. Anything it couldn't tie to a source is listed as unsupported, right
> there in the UI, arguing against its own output."

Point at the approve / request changes / reject buttons.

> "A human decides. And approval only records the decision — the system never
> publishes anything, anywhere."

### 1:55 — Close (10s)

> "The hard problem here isn't collecting content, it's that models confabulate
> quotes and statistics, and a founder can't publish what they can't verify. So
> the guarantee is enforced in code, not in a prompt: every quote and passage is
> re-checked against the stored source text before it's written to the database.
> A hallucinating model literally cannot get a fake quote in — the worst it can
> do is return nothing, which lowers the score."

---

## If asked: "show me it can't fabricate"

Two options, both fast:

**Live** — Source Library → any source → **Evidence** tab. Copy a quote, Ctrl+F it
in the **Full text** tab. It's there, character for character. That's not
coincidence — `enforce_verbatim()` dropped anything that wasn't.

**Code** — `fcie/ai/extraction.py::enforce_verbatim`, ~40 lines, runs on both
backends unconditionally. Then `python -m pytest tests/test_extraction.py -k Verbatim -v`:
the tests feed it a real source plus fabricated quotes, passages and statistics,
and assert every fabrication is discarded and recorded.

## If asked: "what if there's no OpenAI key?"

There wasn't one when this was built — the whole corpus was processed on the
deterministic backend. Settings → Integrations shows every unconfigured
integration with the exact variable to set. Nothing fails silently; nothing is
faked. The LLM path is implemented, coerced, verbatim-gated and unit-tested, and
turning the key on improves the prose, not the evidence.

## If asked: "why not just use an LLM for everything?"

Three reasons, all visible in the code:
1. **Reproducibility** — the heuristic backend gives every LLM output a
   deterministic baseline to diff against.
2. **Demonstrability** — the product has to work with zero credentials.
3. **Trust boundaries** — freshness, weighting, trend labelling and risk are
   arithmetic. Letting a model produce those numbers would mean they could be
   confabulated too, and they're the numbers a decision gets made on.

## If asked: "how does this map to the job?"

See `docs/ROLE_MAPPING.md`.
