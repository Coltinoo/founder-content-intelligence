# Source extraction

Analyse ONE public source document and return structured intelligence about it.

## Context you are serving

The reader is preparing founder-led thought leadership for the CEO of Podium, a
company selling AI "employees" (agents that answer inbound leads, follow up, and
book work) to local businesses — automotive dealerships, home-services
contractors, medspas, healthcare practices and retail.

You are judging: does this document tell us something real about that market?

## Input

```
TITLE: {title}
URL: {url}
DOMAIN: {domain}
PUBLISHED: {published}
SOURCE TYPE: {source_type}
DISCOVERED VIA: {search_query}

SOURCE TEXT:
{text}
```

## Allowed theme labels

Choose `primary_theme` and `secondary_themes` ONLY from this list. If nothing
fits, use `null` for `primary_theme` — do not invent a new theme name.

{theme_list}

## Required JSON schema

```json
{
  "primary_entity": "string|null — the main organisation or person the document is about",
  "secondary_entities": ["other named organisations or people actually mentioned"],
  "industries": ["from: Automotive, Home services, Aesthetics & medspa, Healthcare, Retail, Professional services, B2B SaaS, Local business (general), Cross-industry"],
  "customer_segment": "string|null — who the document is about, e.g. 'Local SMB (single location)'",

  "primary_theme": "one label from the allowed list, or null",
  "secondary_themes": ["further labels from the allowed list"],

  "customer_problem": "string|null — the concrete business problem described IN THE SOURCE, in one sentence. Not your opinion of the problem.",
  "primary_claim": "string|null — the single most important factual assertion the source makes",
  "supporting_evidence": [
    {"passage": "VERBATIM sentence(s) copied from SOURCE TEXT", "supports": "which claim this backs"}
  ],
  "notable_quotes": [
    {"quote": "VERBATIM quotation", "speaker": "name if stated in source, else null"}
  ],
  "numerical_claims": [
    {"value": "the figure as written", "context": "the VERBATIM sentence containing it", "needs_verification": true}
  ],

  "podium_relevance": 0-10,
  "founder_relevance": 0-10,
  "novelty_score": 0-10,
  "evidence_strength": 0-10,
  "business_impact": 0-10,

  "is_familiar_narrative": true/false,
  "is_promotional_source": true/false,

  "content_opportunity": "string|null — INFERENCE: what founder content this could support",
  "potential_angle": "string|null — INFERENCE: the specific point of view worth taking",
  "recommended_format": "one of: linkedin_post, short_form_video_outline, long_form_essay_outline, executive_talking_point, podcast_discussion_point, customer_story_angle, engagement_comment, internal_briefing_note",

  "verification_notes": ["specific checks a human must perform before publication"]
}
```

## Scoring guidance

- **podium_relevance** — 9-10: directly about Podium, its named competitors, or
  AI agents doing lead response for local businesses. 5-7: about the industries
  Podium serves, or about agentic AI in a way that transfers. 1-3: general
  technology news with only a loose connection. 0: unrelated.
- **founder_relevance** — how credibly a local-business SaaS founder could speak
  to this from operating experience. General AI research: low. Local-business
  revenue operations: high.
- **novelty_score** — 8-10: a genuinely new data point, admission, or reversal.
  4-6: a fresh example of a known pattern. 0-3: a narrative that has been
  repeated many times ("AI is transforming X").
- **evidence_strength** — 9-10: primary research, named operators, disclosed
  methodology. 5-7: reported specifics with named sources. 2-4: assertions with
  no attribution. 0-1: pure marketing copy.
- **business_impact** — the size of the commercial consequence implied for a
  local business, not the size of the company mentioned.

Set `is_familiar_narrative` to true when the source restates a widely-published
storyline without adding a new data point. Being familiar is not disqualifying —
it lowers novelty and is important for trend counting.
