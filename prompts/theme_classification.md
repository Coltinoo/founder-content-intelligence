# Theme classification

Assign a batch of sources to a controlled theme vocabulary so that related
signals cluster together across runs.

## Input

```
ALLOWED THEMES:
{theme_list}

SOURCES:
{source_digests}
```

Each source digest contains: id, title, domain, and the extracted
`customer_problem` + `primary_claim`.

## Required JSON schema

```json
{
  "assignments": [
    {
      "source_id": 0,
      "primary_theme": "exact label from ALLOWED THEMES, or null",
      "secondary_themes": ["exact labels from ALLOWED THEMES"],
      "assignment_evidence": "the phrase in the digest that justifies this assignment",
      "confidence": "high|medium|low"
    }
  ],
  "unmatched_patterns": [
    {
      "candidate_theme": "a pattern you saw in 2+ sources that has no allowed label",
      "source_ids": [0],
      "why": "one sentence"
    }
  ]
}
```

## Rules specific to this task

- Use ONLY the exact labels supplied. Never invent, pluralise, or reword a label.
- Assign `null` rather than forcing a poor fit. An unassigned source is more
  useful than a mislabelled one, because mislabelling corrupts trend counts.
- `assignment_evidence` must quote from the digest, not from your own reasoning.
- Report genuinely recurring unmatched patterns in `unmatched_patterns` only when
  **two or more** sources show them. A single source is never a pattern.
- Do not use the number of sources you assign to a theme to make it look
  important. Assign on fit alone.
