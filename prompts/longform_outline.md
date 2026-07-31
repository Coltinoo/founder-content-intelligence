# Long-form outline generation

Produce an essay, video, podcast, or talking-point outline from an approved
brief. The requested `format` is supplied and changes the shape, not the rules.

## Input

```
FORMAT: {content_type}
BRIEF: {brief_json}
EVIDENCE AVAILABLE (verbatim, with source ids):
{evidence_lines}
VERIFIED NUMBERS:
{number_lines}
VOICE GUIDE:
{voice_guide}
```

## Required JSON schema

```json
{
  "draft_text": "the outline as markdown",
  "claims_used": [{"claim": "", "source_id": 1, "evidence_passage": "VERBATIM"}],
  "unsupported_claims": [],
  "verification_required": [],
  "voice_alignment_notes": []
}
```

## Format shapes

- **short_form_video_outline** — 45-75 seconds. Give: hook (first 3 seconds),
  3 beats with an on-screen line each, and a close. Note where a visual or a
  number appears. State the spoken word count.
- **long_form_essay_outline** — working title, thesis in one sentence, 4-6
  sections each with its argument and the source ids that support it, and a
  closing. Flag which sections currently lack evidence.
- **executive_talking_point** — the position in 3 sentences, the 3 facts that
  support it with source ids, the strongest objection and the response, and the
  one number worth citing (or "none verified").
- **podcast_discussion_point** — the question a host would ask, a 60-second
  answer, one concrete example drawn only from the evidence, and the natural
  follow-up question.
- **customer_story_angle** — the *structure* a real customer story would take
  and the questions to ask a real customer. **Never write the story itself and
  never invent a customer.** State explicitly that a real, consented customer
  and real numbers are required.
- **internal_briefing_note** — what we now know, what changed, what we do not
  know, and the recommended next action. Written for internal readers.
- **engagement_comment** — a 40-80 word comment adding a genuine point to
  someone else's public post. Never sycophantic, never a pitch. Must be posted
  by a human.

## Rules specific to this task

- The evidence rules from the shared rules apply in full: no invented numbers,
  quotes, or customers.
- Sections that lack evidence must be labelled `[NEEDS EVIDENCE]` in the outline
  text rather than filled with plausible-sounding assertions.
- Do not pad to reach a length. A short, well-evidenced outline is the goal.
