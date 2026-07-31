# Claim and evidence extraction

A focused second pass over one source: separate what the source *states* from
what a reader might *conclude*, and attach a verbatim passage to every claim.

## Input

```
TITLE: {title}
URL: {url}
PUBLISHED: {published}

SOURCE TEXT:
{text}
```

## Required JSON schema

```json
{
  "claims": [
    {
      "claim": "one factual assertion, stated as the source states it",
      "claim_type": "one of: statistic, customer_outcome, product_capability, market_trend, opinion, prediction, announcement",
      "evidence_passages": ["VERBATIM sentence(s) from SOURCE TEXT that state this"],
      "attribution": "who is asserting it, if the source says — else null",
      "is_first_party": true/false,
      "verifiable_independently": true/false,
      "verification_action": "the specific check a human should run, or null"
    }
  ],
  "interpretations": [
    {
      "interpretation": "something a reader could reasonably conclude that the source does NOT state",
      "based_on": ["VERBATIM passage(s) the inference rests on"],
      "confidence": "high|medium|low"
    }
  ],
  "explicit_gaps": ["what the source conspicuously does not say, e.g. 'no sample size given', 'no time period stated'"]
}
```

## Rules specific to this task

- A claim and its evidence passage may be the same sentence. That is fine and
  preferable to inventing a summary.
- `is_first_party` is true when the asserting party has a commercial interest in
  the claim (a vendor describing its own product results).
- If a statistic appears with no methodology, sample size, or date, that belongs
  in `explicit_gaps` **and** the claim's `verification_action`.
- Predictions are never claims about the present. Mark them `prediction` and set
  `verifiable_independently` to false.
- If the document contains no substantive claims (a navigation page, a stub,
  pure marketing), return `{"claims": [], "interpretations": [], "explicit_gaps": ["Document contains no substantive claims."]}`.
