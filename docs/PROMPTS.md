# AI prompt documentation

All prompts live as editable markdown in [`prompts/`](../prompts) — never as
string literals in the code — and are editable from **Settings → Prompts**.
Loading is handled by [`fcie/ai/prompts.py`](../fcie/ai/prompts.py).

---

## The shared integrity contract

[`prompts/_shared_rules.md`](../prompts/_shared_rules.md) is **prepended to every
prompt at render time**, so the contract cannot be edited out of a single prompt
by accident. Missing it raises `FileNotFoundError` rather than degrading quietly.

The ten absolute rules:

1. Never invent a quotation — only exact character sequences present in the
   source text are valid; return an empty list rather than paraphrasing.
2. Never rewrite, tidy, translate, or "fix" a quote.
3. Never invent a statistic, customer story, company, person, or date.
4. Never present an inference as a fact.
5. Every claim needs a supporting passage — lower the evidence score instead of
   filling the field.
6. State explicitly when a source has no publication date; never guess one.
7. Mark vendor marketing as promotional and reduce its evidence weight — it is
   evidence of positioning, not of market reality.
8. Flag anything unverifiable from the source alone, with the specific check.
9. Do not be overconfident. A low score is a valid answer.
10. Never state or imply that a named person wrote, said, reviewed, or approved
    anything unless the source attributes it verbatim.

Plus output discipline: a single JSON object, no fences, `null` for unknown
scalars, `[]` for unknown lists, and never placeholder text like "N/A" or "TBD".

> **These rules are backed by code.** `enforce_verbatim()` re-checks every quote,
> passage and numerical context against the source before the database write, and
> `LLMBriefBuilder` drops supporting points whose source ids or passages we do not
> hold. The prompt asks; the code verifies.

---

## The eleven prompts

| Prompt | Purpose | Task-specific safeguards |
|---|---|---|
| `source_extraction` | Full structured analysis of one source | Themes constrained to an 18-label controlled vocabulary; `null` rather than a forced fit; per-dimension scoring rubrics |
| `claim_evidence` | Separate what the source *states* from what a reader could *conclude* | `is_first_party` flags interested parties; predictions can never be "verifiable"; `explicit_gaps` records what is conspicuously missing |
| `theme_classification` | Batch assignment to the controlled vocabulary | Exact labels only; `null` beats a mislabel because mislabels corrupt trend counts; unmatched patterns need 2+ sources |
| `trend_analysis` | Interpret computed statistics | **Forbidden from changing the numbers**; single-domain forces `confidence: low`; must state when a sample is too small |
| `opportunity_scoring` | Review, not calculation | Risk factors need the specific triggering text; **may not adjust the total** — disagreement goes in `component_review` |
| `brief_generation` | The primary product output | 3-5 points, each with a source id **and** a verbatim passage; ≥2 genuine objections; no number outside the supplied list; banned-phrase list |
| `voice_analysis` | Derive a guide from approved examples | Unconfirmed default assumptions must be listed as unconfirmed; <5 examples forces a coverage warning; verbatim hooks only |
| `linkedin_draft` | LinkedIn post for human review | Every factual sentence must appear in `claims_used` with a source id; honest `unsupported_claims`; no fabricated customer stories; banned phrases |
| `longform_outline` | Essay / video / podcast / talking point / etc. | Unevidenced sections labelled `[NEEDS EVIDENCE]`; the customer-story format produces a **structure and interview questions, never a story** |
| `engagement_recommendation` | Watchlist items | Only entities named in supplied sources; never construct a profile URL; no pitches; must recommend staying out when appropriate; empty list is valid |
| `factcheck_review` | Sentence-level audit of a draft | `evidence_score` computed not estimated; any fabrication forces `reject`; opinion is legitimate and excluded, not flagged |

---

## Rendering

`Prompt.render(**values)` uses a `_SafeFormatter` that leaves unknown
placeholders visible rather than blanking them, and tolerates the literal braces
in the JSON schema blocks that a plain `str.format()` would choke on. A missing
value therefore shows up as `{field_name}` in the prompt — loud, not silent.

```python
from fcie.ai.prompts import load_prompt

prompt = load_prompt("source_extraction").render(
    title=..., url=..., domain=..., published=..., source_type=...,
    search_query=..., text=..., theme_list=...,
)
```

## Model configuration

`fcie/ai/client.py` requests `response_format={"type": "json_object"}` at
temperature 0.2 (configurable), with two retries, exponential backoff, and an
immediate abort on authentication errors. Parsing is tolerant — fences stripped,
then a brace-span fallback. If everything fails the caller falls back to the
heuristic backend and records the error in `extraction_error` rather than losing
the source.

## Editing prompts

Settings → Prompts shows every file with its size, lets you read the shared
rules, and edits any prompt in place. Changes take effect on the next run
(`load_prompt` cache is cleared on write).

Two things to keep in mind when editing:

- **The code-level guarantees do not move.** Weakening a prompt's quote rule will
  not let fabricated quotes through — `enforce_verbatim` still drops them. It will
  just produce emptier extractions.
- **Theme labels must stay in sync** with `fcie/ai/taxonomy.py`. The extractor
  rejects any `primary_theme` outside `THEME_NAMES`, so inventing a label in the
  prompt silently yields `null`.
