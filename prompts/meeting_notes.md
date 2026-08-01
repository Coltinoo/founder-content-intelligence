# Meeting notes and content extraction

Turn a raw meeting, interview, or podcast transcript into structured notes and
founder-content ideas. The transcript is the **only** permitted source of fact.

## Input

```
TITLE: {title}
TRANSCRIPT:
{transcript}
```

## Required JSON schema

```json
{
  "summary": "3-4 sentences on what this meeting was actually about",
  "decisions": [{"decision": "", "owner": "", "quote": "VERBATIM"}],
  "action_items": [{"action": "", "owner": "", "due": "", "quote": "VERBATIM"}],
  "open_questions": ["questions raised and left unresolved"],
  "quotes": [{"quote": "VERBATIM", "speaker": "", "why_notable": ""}],
  "content_ideas": [
    {
      "idea": "the argument this meeting could support publicly",
      "audience": "who it is for",
      "why_it_works": "why this is worth saying now",
      "evidence_quote": "VERBATIM line from the transcript that grounds it",
      "suggested_post": "a complete draft post, 80-160 words",
      "needs_verification": ["anything a reader would want checked first"]
    }
  ],
  "sensitivity_notes": ["anything that should not be published, and why"]
}
```

## Coverage

- **Decisions** are anything the group settled on, including soft ones: what to
  pilot, what to measure, what not to say publicly. "We'll pilot X for two weeks"
  is a decision. Do not restrict this to formal approvals — most real meetings
  contain no formal approvals and this section should rarely be empty.
- **Content ideas**: return **three** where the transcript supports three. A
  meeting usually contains more than one publishable argument — a problem worth
  naming, a counter-intuitive observation, and a lesson from how the team
  reasoned about it. Return fewer only when the material genuinely is not there.
- Prefer the argument that is true beyond this company. "Our close rate slipped"
  is a status update; "the leads you already paid for are sitting in a queue
  overnight" is an argument other people can use.

## Rules specific to this task

- Every `quote`, and every `evidence_quote`, must be **copied character for
  character** from the transcript. Do not tidy grammar, merge two lines, or
  paraphrase. Anything that is not an exact copy is discarded by the code that
  reads your output, and the idea it belonged to loses its evidence.
- `suggested_post` is your own prose and may synthesise — but every *fact* in it
  must trace to the transcript. No invented numbers, customers, or outcomes.
- A meeting is internal by default. Anything about unreleased products, named
  customers, headcount, pricing, legal matters, or personal remarks goes in
  `sensitivity_notes` and must not appear in `suggested_post`.
- Attribute nothing to a named person unless they said it in the transcript.
- If the transcript does not support a section, return it empty. An empty list
  is a correct answer; an invented one is not.
- Do not write in the first person as any named individual, and never imply a
  named person has written or approved the post.
- Write plainly. These phrases are rejected on sight and flagged back to the
  reader: *game-changer, revolutionize, unlock, in today's fast-paced, the future
  of, 10x, let that sink in, here's the kicker, paradigm shift, supercharge,
  seismic shift*. State the observation and stop.
