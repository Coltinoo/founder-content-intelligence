# Trend analysis

Interpret the computed statistics for one theme and write the rationale a human
reviewer reads. **You do not compute the numbers and you must not contradict
them** — they are calculated deterministically in `fcie/pipeline/trends.py`.

## Input

```
THEME: {theme_name}
DESCRIPTION: {theme_description}

COMPUTED STATISTICS (authoritative — do not change these):
  total sources:            {source_count}
  distinct domains:         {distinct_domains}
  distinct industries:      {distinct_industries}
  current period count:     {current_count}  (last {current_days} days)
  previous period count:    {previous_count}  (the {previous_days} days before that)
  growth rate:              {growth_rate}
  avg Podium relevance:     {avg_relevance}/10
  avg founder relevance:    {avg_founder_relevance}/10
  avg evidence strength:    {avg_evidence}/10
  avg business impact:      {avg_impact}/10
  days since most recent:   {recency_days}
  assigned trend status:    {trend_status}

REPRESENTATIVE SOURCES:
{source_lines}
```

## Required JSON schema

```json
{
  "rationale": "2-3 sentences explaining the assigned status using the numbers above",
  "what_is_actually_new": "string|null — what changed recently, or null if nothing did",
  "counter_evidence": "string|null — anything in the sources that argues against this being a trend",
  "confidence": "high|medium|low",
  "caveats": ["specific limitations of this theme's evidence base"]
}
```

## Rules specific to this task

- **Never call something a trend on the strength of one source or one domain.**
  If `distinct_domains` is 1, `confidence` must be `low` and the first caveat
  must say the signal comes from a single publisher.
- If `source_count` is below 3, say plainly that the sample is too small to
  generalise from.
- A high growth rate from 1 → 3 sources is not a trend. Say so.
- If most sources are vendor marketing, the caveat must name that.
- Do not restate the numbers as prose. Explain what they mean.
- Never write promotional language about Podium. This is an internal analytic
  note, not copy.
