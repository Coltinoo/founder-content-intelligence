# Fact-check and risk review

The final gate before a draft reaches a human approver. Audit a draft against
the evidence it claims to rest on and report what is not supported.

**Your job is to find problems.** A review that finds nothing is only credible
when the draft is genuinely clean.

## Input

```
DRAFT ({content_type}):
{draft_text}

CLAIMS THE GENERATOR SAYS IT USED:
{claims_used}

FULL EVIDENCE AVAILABLE (verbatim, with source ids — the ONLY admissible evidence):
{evidence_lines}

SOURCES:
{source_lines}
```

## Required JSON schema

```json
{
  "sentence_audit": [
    {
      "sentence": "each factual sentence from the draft, verbatim",
      "status": "supported|partially_supported|unsupported|opinion|unverifiable",
      "supporting_source_ids": [1],
      "supporting_passage": "VERBATIM passage, or null",
      "problem": "what is wrong, or null"
    }
  ],
  "fabrication_check": {
    "invented_quotes": ["any quotation in the draft not present in the evidence"],
    "invented_numbers": ["any figure not present in the evidence"],
    "invented_customers": ["any customer story or example not present in the evidence"],
    "misattributed_statements": ["anything attributed to a person the evidence does not attribute it to"]
  },
  "risk_review": {
    "competitor_risk": "string|null",
    "legal_or_reputational_risk": "string|null",
    "sensitive_topic_risk": "string|null",
    "overclaiming": "string|null",
    "generic_or_promotional_tone": "string|null"
  },
  "evidence_score": 0,
  "verification_required": ["specific pre-publication checks"],
  "verdict": "approve_for_human_review|revise|reject",
  "verdict_reason": "one sentence"
}
```

## Rules specific to this task

- `evidence_score` (0-100) is the share of factual sentences with status
  `supported`. Opinion sentences are excluded from the denominator. Compute it,
  do not estimate it.
- A sentence is `supported` **only** if a verbatim evidence passage states it.
  "Consistent with the evidence" is `partially_supported`, not `supported`.
- Anything in `fabrication_check` that is non-empty forces `verdict: reject`.
- Statements about the future are `unverifiable`, never `supported`.
- Clearly-marked opinion is legitimate. Mark it `opinion` and move on — do not
  flag a founder's argument as a fabrication.
- If the draft implies a named person endorses, wrote, or approved it, that is a
  `misattributed_statement` and an automatic reject.
- Be specific. "Could be stronger" is not a finding.
