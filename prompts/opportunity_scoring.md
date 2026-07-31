# Opportunity scoring review

The 100-point opportunity score is computed deterministically from the weights
in `config/scoring.yaml`. Your job is **review, not calculation**: sanity-check
the component inputs and surface risk the arithmetic cannot see.

## Input

```
CANDIDATE: {title}
THEME: {theme_name}  (status: {trend_status}, {source_count} sources across {distinct_domains} domains)

COMPUTED COMPONENTS (0-10 each):
  podium_relevance:   {podium_relevance}   × {w_podium}
  founder_relevance:  {founder_relevance}  × {w_founder}
  evidence_strength:  {evidence_strength}  × {w_evidence}
  freshness:          {freshness}          × {w_freshness}
  novelty:            {novelty}            × {w_novelty}
  business_impact:    {business_impact}    × {w_impact}
  → total: {total_score}/100

SUPPORTING SOURCES:
{source_lines}

EVIDENCE PASSAGES:
{evidence_lines}
```

## Required JSON schema

```json
{
  "component_review": [
    {"component": "podium_relevance", "computed": 0, "assessment": "supported|too_high|too_low", "why": "one sentence citing the evidence"}
  ],
  "risk_factors": [
    {
      "factor": "one of: weak_sourcing, unverified_numbers, competitor_claims, sensitive_claims, promotional_source, overused_narrative, no_original_insight, generic_tone, missing_publication_date",
      "detected": true,
      "why": "the specific thing in the sources that triggers it"
    }
  ],
  "publication_blockers": ["anything that must be resolved before this could be published at all"],
  "confidence_in_score": "high|medium|low",
  "recommendation": "one of: promote, needs_more_sources, needs_verification, drop"
}
```

## Rules specific to this task

- Only report a risk factor when you can point at the specific text that
  triggers it. Do not list factors speculatively.
- `weak_sourcing` applies when the evidence comes from fewer than two distinct
  domains, or entirely from parties selling the thing being discussed.
- `competitor_claims` applies to any assertion about a named competitor's
  product, performance, or customers — these carry legal risk and always need a
  primary source.
- `sensitive_claims` covers employment/job-loss, health, legal, and financial
  outcomes.
- Recommend `drop` when the content would only restate what the source already
  says, with no founder point of view available.
- Do not adjust the total score. Report disagreement in `component_review`.
