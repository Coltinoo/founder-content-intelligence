#!/usr/bin/env python
"""Seed the voice library from public content already collected in the database.

**What this does and does not claim.**

The voice library is meant to hold *founder* content. This script does not have
any, and it will not invent any: fabricating text and attributing it to a named
person is exactly what this system exists to prevent.

What it does instead is bootstrap the library with **genuinely fetched, publicly
published Podium pages already in your `sources` table**, labelled
`content_type: company_public_content`, so the voice-analysis machinery is
demonstrable end to end. Every example carries its real canonical URL.

These are company-published marketing and editorial text. They are **not
verified as written by Eric Rea**, and the generated guide says so. Replace them
with genuine public founder content — interview transcripts, public posts you
have copied by hand, keynote transcripts — on the Voice Library page.

Usage:
    python scripts/seed_voice_examples.py
    python scripts/seed_voice_examples.py --count 8 --clear
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401  (sets sys.path and console encoding)

from sqlalchemy import select  # noqa: E402

from fcie.db import init_db, session_scope  # noqa: E402
from fcie.models import Source, VoiceExample  # noqa: E402
from fcie.pipeline.voice import analyse_and_store, build_voice_guide  # noqa: E402
from fcie.utils.text import word_count  # noqa: E402

DISCLAIMER = (
    "Seeded from public Podium-published content already collected by this system. "
    "This is company marketing/editorial text and is NOT verified as written by "
    "Eric Rea. Replace with genuine public founder content on the Voice Library page."
)

# Prefer editorial/thought-leadership pages over pure product pages.
PREFERRED = ("/article/", "/guides/", "/case-study/", "/whats-new/", "/about", "/careers")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the voice library from real public sources.")
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--clear", action="store_true",
                        help="Remove previously seeded examples first.")
    parser.add_argument("--min-words", type=int, default=150)
    args = parser.parse_args()

    init_db()

    with session_scope() as session:
        if args.clear:
            seeded = session.execute(
                select(VoiceExample).where(VoiceExample.added_by == "seed_script")
            ).scalars().all()
            for example in seeded:
                session.delete(example)
            print(f"Removed {len(seeded)} previously seeded example(s).")

        candidates = session.execute(
            select(Source)
            .where(Source.source_domain == "podium.com")
            .where(Source.cleaned_text.is_not(None))
        ).scalars().all()

        usable = [
            s for s in candidates
            if word_count(s.cleaned_text) >= args.min_words
        ]
        if not usable:
            print(
                "No Podium sources with enough body text found.\n"
                "Run `python scripts/run_discovery.py` first, then re-run this script."
            )
            return 1

        def rank(source: Source) -> tuple[int, int]:
            preference = next(
                (i for i, marker in enumerate(PREFERRED) if marker in source.canonical_url),
                len(PREFERRED),
            )
            return preference, -word_count(source.cleaned_text)

        usable.sort(key=rank)

        existing_urls = {
            row[0] for row in session.execute(select(VoiceExample.source_url)).all()
        }

        added = 0
        new_ids = []
        for source in usable:
            if added >= args.count:
                break
            if source.canonical_url in existing_urls:
                continue
            example = VoiceExample(
                title=f"[Company content] {source.title or source.canonical_url}",
                source_url=source.canonical_url,
                pasted_text=source.cleaned_text,
                date=source.published_at,
                content_type="company_public_content",
                approved_for_voice_library=True,
                added_by="seed_script",
                tone_notes=DISCLAIMER,
            )
            session.add(example)
            session.flush()
            new_ids.append(example.id)
            added += 1
            print(f"  + #{example.id} {source.title or source.canonical_url}")

    for example_id in new_ids:
        analyse_and_store(example_id)

    guide = build_voice_guide()
    print(f"\nSeeded {added} example(s). Voice library now holds "
          f"{guide['approved_example_count']} approved example(s).")
    if guide.get("coverage_warning"):
        print(f"  Coverage warning: {guide['coverage_warning']}")
    print(f"  Confirmed assumptions: {len(guide.get('confirmed_assumptions', []))}")
    print(f"  Unconfirmed assumptions: {len(guide.get('unsupported_assumptions', []))}")
    print(f"\n{DISCLAIMER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
