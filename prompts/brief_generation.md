# Founder content brief generation

Produce the primary output of this system: a source-grounded brief a founder's
associate could hand to a CEO. The brief argues a point of view and shows its
work.

## Input

```
THEME: {theme_name} — {theme_description}
TREND STATUS: {trend_status} ({source_count} sources, {distinct_domains} domains, {distinct_industries} industries)

SOURCES:
{source_lines}

EVIDENCE PASSAGES (verbatim, each tagged with its source id):
{evidence_lines}

QUOTES AVAILABLE (verbatim, with speaker where stated):
{quote_lines}

NUMERICAL CLAIMS FOUND (each still requires verification):
{number_lines}

FOUNDER VOICE GUIDE (derived from approved public examples; may be empty):
{voice_guide}
```

## Required JSON schema

```json
{
  "title": "a specific, arguable statement — not a topic label",
  "core_insight": "2-3 sentences. The non-obvious thing the evidence shows.",
  "why_now": "what changed recently, tied to specific dated sources",
  "why_podium": "why this bears on Podium's market and product positioning",
  "why_eric": "why a local-business SaaS founder could credibly speak to this — based on the public record only",
  "target_audience": "who this is for, specifically",
  "founder_point_of_view": "the argument being made, in one paragraph. This is an INFERENCE, not a source claim.",
  "hook": "the opening line. Concrete and specific. No 'In today's fast-paced world'.",
  "supporting_points": [
    {"point": "one supporting argument", "evidence_source_ids": [1], "evidence_passage": "VERBATIM passage backing it"}
  ],
  "potential_objections": [
    {"objection": "the strongest good-faith counter-argument", "response": "an honest response, conceding what should be conceded"}
  ],
  "recommended_format": "linkedin_post|short_form_video_outline|long_form_essay_outline|executive_talking_point|podcast_discussion_point|customer_story_angle|internal_briefing_note",
  "suggested_call_to_action": "what the reader should do or think differently about",
  "verification_checklist": [
    {"item": "a specific thing to confirm before publishing", "why": "what goes wrong if it is not checked"}
  ],
  "risk_notes": ["specific publication risks"],
  "confidence_note": "a candid sentence about how strong the evidence base actually is"
}
```

## Rules specific to this task

1. Between 3 and 5 `supporting_points`. **Every one must carry at least one
   `evidence_source_id` and a verbatim `evidence_passage`.** A point you cannot
   evidence must be deleted, not softened.
2. `why_eric` must rest only on publicly known facts about the founder's
   company and market. Never assert what he thinks, has said, or would say. Do
   not imply he has seen or approved this.
3. Never put a number in the brief that is not in `NUMERICAL CLAIMS FOUND`, and
   whenever you use one, add a matching `verification_checklist` item.
4. `potential_objections` must contain at least two genuine objections. A
   strawman objection is worse than none.
5. `founder_point_of_view` is explicitly an inference. Write it as an argument,
   not as a finding.
6. If the evidence only supports a weak brief, say so in `confidence_note` and
   keep the brief small. Do not pad.
7. No competitor may be named in a disparaging claim. Comparative statements
   need a source id.
8. Do not use: "game-changer", "revolutionise", "unlock", "leverage" (as a
   verb), "in today's world", "the future of", "10x". Write plainly.
