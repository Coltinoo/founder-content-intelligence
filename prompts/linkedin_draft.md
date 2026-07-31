# LinkedIn draft generation

Turn an approved content brief into a LinkedIn post draft **for human review**.

This draft will never be auto-published. It is a suggestion that a human edits,
approves, or rejects. It must not be presented as written or approved by any
named person.

## Input

```
BRIEF:
  title: {title}
  core insight: {core_insight}
  why now: {why_now}
  why podium: {why_podium}
  founder point of view: {founder_point_of_view}
  hook: {hook}
  supporting points: {supporting_points}
  call to action: {call_to_action}

EVIDENCE AVAILABLE (verbatim, with source ids — you may use ONLY these facts):
{evidence_lines}

VERIFIED NUMBERS (the only figures you may use):
{number_lines}

VOICE GUIDE (from approved public examples; may be empty):
{voice_guide}
```

## Required JSON schema

```json
{
  "draft_text": "the post, 120-220 words, with real line breaks",
  "claims_used": [
    {"claim": "each factual statement in the draft", "source_id": 1, "evidence_passage": "VERBATIM passage supporting it"}
  ],
  "unsupported_claims": ["any statement in the draft you could NOT tie to a source — be honest, this is the point"],
  "verification_required": ["what a human must confirm before posting"],
  "voice_alignment_notes": ["which voice-guide patterns you applied, and where you departed"],
  "alternative_hooks": ["2 other opening lines"]
}
```

## Rules specific to this task

1. **Every factual sentence must appear in `claims_used` with a source id and a
   verbatim passage.** If you write a sentence you cannot back, list it in
   `unsupported_claims`. An empty `unsupported_claims` list is only credible if
   the draft genuinely contains no unbacked assertion.
2. **No invented statistics.** Use only figures from `VERIFIED NUMBERS`, and
   keep their original framing.
3. **No fabricated customer stories.** Do not write "we had a customer who…".
4. **No first-person claims on behalf of a named person.** Write in a founder
   register, but never assert private experience, private conversations, or
   internal company data.
5. Opinion is allowed and encouraged — it is the point of founder content — but
   opinion must be recognisable as opinion, not dressed as data.
6. Format: short paragraphs, one idea each. No hashtag walls (max 3, or none).
   No emoji unless the voice guide shows them. No "Thoughts? 👇".
7. Banned phrases: "game-changer", "revolutionise/revolutionize", "unlock",
   "leverage" (as a verb), "in today's fast-paced", "the future of X is here",
   "10x", "let that sink in", "here's the kicker", "I'll say the quiet part".
8. Do not open with "I've been thinking about" or a one-word line followed by a
   full stop.
9. If the brief's evidence is too thin for a credible post, say so in
   `unsupported_claims` and produce a shorter, more hedged draft rather than
   padding with generic assertions.
