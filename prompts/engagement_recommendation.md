# Engagement recommendation

Identify public conversations a **human** may want to review and respond to.

This system never comments, likes, reposts, follows, connects, or messages. It
produces a review queue. Every item ends with a human deciding.

## Input

```
RECENT SOURCES:
{source_lines}

THEMES CURRENTLY RISING:
{theme_lines}
```

## Required JSON schema

```json
{
  "watchlist": [
    {
      "person_or_company": "the publisher, author, or organisation — as named in the source",
      "profile_or_source_url": "the canonical source URL (never a scraped profile URL)",
      "source_id": 1,
      "topic": "what they are discussing",
      "recent_signal": "the specific recent thing, quoted or closely paraphrased from the source",
      "why_relevant": "why this is worth a founder's attention",
      "podium_connection": "the honest connection to Podium's market — or 'adjacent only'",
      "suggested_response_angle": "what a substantive human reply could add. Not a pitch.",
      "priority": "high|medium|low",
      "risk_notes": "what could go wrong in replying here, or null"
    }
  ]
}
```

## Rules specific to this task

1. Only include entities **named in the supplied sources**. Never look up or
   infer a person's social profile, employer, or contact details.
2. `profile_or_source_url` must be the source URL we already hold. Do not
   construct LinkedIn, X, or other profile URLs.
3. `suggested_response_angle` must add something — a counter-example, a
   distinction, a question. Never "great post!", never a product pitch, never a
   link drop.
4. Set `priority: high` only when the topic directly touches the founder's
   demonstrable operating domain AND the conversation is recent.
5. `risk_notes` is mandatory when the item involves a competitor, an unhappy
   customer, layoffs, litigation, or anything politically charged. Recommend
   staying out when that is the right answer.
6. Never suggest engaging with a private individual, a personal grievance, or a
   thread about someone's employment.
7. If nothing in the sources merits engagement, return `{"watchlist": []}`. An
   empty queue is a valid and useful answer.
