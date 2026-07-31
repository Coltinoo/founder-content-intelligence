# Founder voice analysis

Derive a voice guide from **approved public examples that a human has manually
added** to the voice library. Every conclusion must be traceable to those
examples.

This produces "founder voice alignment based on approved public examples". It is
explicitly **not** an impersonation of any individual, and the output must say so.

## Input

```
APPROVED EXAMPLES ({example_count} total):
{examples}
```

Each example includes: title, content type, date, source URL, and full text as
pasted by a human.

## Required JSON schema

```json
{
  "hook_structure": {
    "observed_patterns": ["pattern seen in the examples"],
    "example_hooks": ["VERBATIM opening line from an example"],
    "typical_length_words": 0
  },
  "sentence_style": {
    "median_sentence_words": 0,
    "median_paragraph_sentences": 0,
    "uses_fragments": true,
    "notes": "what is distinctive"
  },
  "vocabulary": {
    "recurring_terms": ["terms that appear across multiple examples"],
    "avoided_registers": ["registers absent from the examples, e.g. 'academic hedging'"]
  },
  "confidence_level": "how assertive the writing is, with an example",
  "use_of_numbers": "how figures appear, with an example",
  "use_of_customer_stories": "how customers appear, with an example",
  "use_of_contrast": "e.g. 'X isn't the problem, Y is' — with an example",
  "use_of_founder_experience": "how first-hand operating experience appears",
  "recurring_themes": ["themes appearing in 2+ examples"],
  "tone": "3-6 adjectives grounded in the examples",
  "audience": "who the examples address",
  "typical_calls_to_action": ["observed CTA patterns"],
  "technical_detail_level": "none|light|moderate|heavy, with justification",

  "evidence_map": [
    {"conclusion": "which conclusion above", "example_titles": ["which examples support it"]}
  ],
  "coverage_warning": "string|null — set when there are too few examples to generalise",
  "unsupported_assumptions": ["default assumptions NOT confirmed by the examples"]
}
```

## Rules specific to this task

- **Base every conclusion on the supplied examples.** If a default assumption
  (direct, commercially focused, optimistic about AI, short paragraphs, avoids
  hype, prefers measurable impact) is not visible in the examples, list it under
  `unsupported_assumptions` — do not assert it.
- With fewer than 5 examples, `coverage_warning` is mandatory and must state the
  count.
- Quote example hooks **verbatim**.
- Do not claim the guide reproduces anyone's voice. It describes observable
  patterns in a small sample of public text.
- If the examples are all one content type, say that the guide may not transfer
  to other formats.
