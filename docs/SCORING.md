# Scoring methodology

Everything here is deterministic and reproducible from stored inputs. When the
LLM backend is active it proposes the six 0-10 component scores; the weighting,
freshness, risk, confidence and trend labelling are always arithmetic.

Configuration: [`config/scoring.yaml`](../config/scoring.yaml), editable in
Settings → Model & scoring. Implementation:
[`fcie/pipeline/scoring.py`](../fcie/pipeline/scoring.py).

---

## Opportunity score (0-100)

```
score = Σ ( component₀₋₁₀ × normalised_weight ) × 10
```

| Component | Weight | What a high score means |
|---|---:|---|
| `podium_relevance` | 25% | Directly about Podium, its named competitors, or AI agents doing lead response for local businesses |
| `founder_relevance` | 20% | A local-business SaaS founder could speak to this from operating experience |
| `evidence_strength` | 20% | Primary research, named operators, disclosed methodology |
| `freshness` | 15% | Recent, with a real publication date |
| `novelty` | 10% | A new data point, admission or reversal — not a repeated storyline |
| `business_impact` | 10% | Large commercial consequence for a local business |

Weights are **normalised before use**, so a partially-configured or non-summing
weight map still produces a score on the same 0-100 scale. Components are clamped
to 0-10; non-numeric input degrades to 0 rather than raising.

The full per-component breakdown — raw value, weight, points earned, points
available — is stored in `score_breakdown` and rendered as a table wherever a
score appears. No score is ever shown without its derivation.

### Heuristic component derivation

When no LLM is configured, components come from countable text properties:

- **Podium relevance** — Podium entity mention (+5), agentic-AI vocabulary (+2),
  named competitors (+0.8 each, cap 2), core-industry match (+2), local/SMB
  language (+1.5), theme-match depth (cap 2), lead-response vocabulary (+1.5).
- **Founder relevance** — half the Podium relevance, plus Eric Rea mention (+3.5),
  founder/CEO language (+1), operator-topic hits (+0.6 each, cap 3), **minus 2**
  for deep-tech research vocabulary (benchmarks, parameter counts, GPU clusters) —
  AI-related is not the same as founder-relevant.
- **Evidence strength** — base 2, plus verbatim passages (0.8 each, cap 3), quotes
  (0.7 each, cap 2), numerical claims (0.5 each, cap 2), long-document bonus (+1);
  minus 1.5 if under 200 words, **minus 2.5 if promotional**, **minus 2.0 if
  `summary_only`** (publisher abstract, body access-restricted), minus 1 for
  YouTube (metadata only), minus 0.5 for manual entry.
- **Business impact** — base 3, plus commercial vocabulary (cap 3.5), numerical
  claims (cap 1.5), scale language (cap 1.2), missed-demand language (+1).
- **Novelty** — base 5, minus 2.5 if a familiar narrative, minus 1.5 if
  promotional; plus numerical claims (cap 2), quotes (+1), deep single-theme
  engagement (+1).

### Freshness

| Age | Score |
|---|---|
| ≤ 7 days | 10.0 |
| 7-120 days | linear decay |
| ≥ 120 days | 0.0 |
| **no publication date** | **4.0 + an explicit `missing_publication_date` flag** |
| future-dated | 10.0, flagged as anomalous |

Undated sources are common in marketing content — all 13 Podium case studies lack
a date. They are not silently treated as fresh *or* silently discarded; they get a
neutral score and a visible flag, and no recency claim may rest on them.

---

## Risk score (0-100) — scored independently

Risk is **not** subtracted from the opportunity score. A high-value, high-risk
item is exactly what a founder's associate most needs to see; averaging the two
would bury it in the middle of the list.

| Factor | Points | Fires when |
|---|---:|---|
| `weak_sourcing` | 18 | fewer than 2 distinct domains, or a majority-vendor evidence base |
| `unverified_numbers` | 16 | any figure present without an independent primary source |
| `competitor_claims` | 14 | named competitors present — legal exposure |
| `sensitive_claims` | 14 | employment, legal, health or financial-outcome territory |
| `promotional_source` | 10 | source is vendor marketing |
| `overused_narrative` | 10 | theme is saturated / restates a familiar storyline |
| `no_original_insight` | 10 | fewer than 3 evidenced supporting points |
| `generic_tone` | 8 | draft reads like generic AI hype |
| `missing_publication_date` | 6 | no date on a supporting source |

Bands: **Low** ≤24 · **Moderate** ≤49 · **Elevated** ≤74 · **High** >74.

Every fired factor stores the *specific reason* it fired, not just the label.

---

## Confidence (0-100)

How well-supported the brief is — deliberately separate from how attractive the
opportunity is.

| Signal | Max | Formula |
|---|---:|---|
| Distinct domains | 30 | `min(domains / 3, 1) × 30` |
| Verbatim passages | 25 | `min(passages / 4, 1) × 25` |
| Avg evidence strength | 30 | `(strength / 10) × 30` |
| Source volume | 15 | `min(sources / 5, 1) × 15` |

Multipliers: **×0.65** for a single-domain evidence base, **×0.9** when no
supporting source is dated. Each contribution is stored as a human-readable
reason string.

---

## Trend labelling

Computed in `pipeline/trends.py` from database aggregates. The model, when
present, writes only the surrounding *rationale* and is explicitly forbidden from
changing the numbers.

| Label | Rule |
|---|---|
| `low_confidence` | `< min_sources_for_trend` (2) **or** `< min_domains_for_trend` (2) distinct domains |
| `emerging` | first seen inside the current period, already at the source floor |
| `saturated` | ≥6 sources but average novelty < 4/10 |
| `rising` | ≥3 sources this period **and** growth ≥ +50% |
| `declining` | ≥2 sources last period **and** growth ≤ −40% |
| `stable` | everything else |

Default periods: 21 days current vs the 21 days before.

> **A single source is never a trend. One publisher repeating itself is not
> corroboration.** Both rules are checked first, before any growth calculation,
> so a 1→3 jump inside one domain can never be labelled "rising".

Secondary theme assignments contribute at **half weight** to a theme's averages,
so an incidental mention cannot drag a cluster's scores around.

---

## Draft evidence score (0-100)

Computed by `pipeline/drafts.py::audit_draft`, sentence by sentence, using token
overlap against the verbatim evidence corpus.

| Status | Rule | Counts toward |
|---|---|---|
| `supported` | ≥60% token overlap with an evidence passage | numerator (1.0) |
| `partially_supported` | 35-60% overlap | numerator (0.5) |
| `unsupported` | <35% overlap | denominator only |
| `opinion` | contains an opinion marker | **excluded** |
| `unverifiable` | future-tense claim | **excluded** |

```
evidence_score = (supported + 0.5 × partially_supported) / factual_sentences × 100
```

Opinion is legitimate — it is the point of founder content — so it is excluded
rather than penalised. It is a claim dressed as data that gets flagged.

Independent fabrication checks run regardless of what the generator reported
about itself: figures in the draft absent from the evidence corpus, and
quotations that match no stored passage. Both are surfaced in
`verification_required`.

---

## Voice alignment (0-100)

Measured against the **approved public examples only**. Starts at 100 and
deducts: sentence-length deviation (−8 or −20), paragraph-length deviation (−12),
hype vocabulary absent from every approved example (−25, or −10 if the examples
contain some), missing figures when a majority of examples use them (−10), no
recurring theme touched (−5). A coverage warning applies a final ×0.8.

**With zero approved examples the score is 0** with an explanatory note — the
system never claims alignment it cannot evidence, and never invents a voice guide.
