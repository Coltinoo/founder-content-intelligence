#!/usr/bin/env python
"""Print a handover summary of what the system actually found and produced.

Everything printed here is read from the database — nothing is composed by this
script. Use it to sanity-check a run, or to produce the summary you hand to a
reviewer.

Usage:
    python scripts/report_deliverables.py
    python scripts/report_deliverables.py --top 3 --markdown > handover.md
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401  (sets sys.path and console encoding)

from sqlalchemy import func, select  # noqa: E402

from fcie.db import describe_backend, session_scope  # noqa: E402
from fcie.models import (  # noqa: E402
    ContentDraft,
    ContentOpportunity,
    EngagementWatchlistItem,
    ExtractedSignal,
    Source,
    Theme,
    VoiceExample,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarise what the system produced.")
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()

    h1 = (lambda t: f"\n# {t}\n") if args.markdown else (lambda t: f"\n{'=' * 78}\n{t}\n{'=' * 78}")
    h2 = (lambda t: f"\n## {t}\n") if args.markdown else (lambda t: f"\n--- {t} " + "-" * max(0, 70 - len(t)))

    with session_scope() as session:
        print(h1("Founder Content Intelligence Engine — run summary"))
        print(f"Database: {describe_backend()}")

        # ── coverage ────────────────────────────────────────────────────
        print(h2("Coverage"))
        total = session.scalar(select(func.count(Source.id))) or 0
        domains = session.scalar(select(func.count(func.distinct(Source.source_domain)))) or 0
        signals = session.scalar(select(func.count(ExtractedSignal.id))) or 0
        themes = session.scalar(select(func.count(Theme.id))) or 0
        opportunities = session.scalar(select(func.count(ContentOpportunity.id))) or 0
        drafts = session.scalar(select(func.count(ContentDraft.id))) or 0
        voice = session.scalar(select(func.count(VoiceExample.id))) or 0
        watch = session.scalar(select(func.count(EngagementWatchlistItem.id))) or 0
        print(f"  sources            {total}   across {domains} distinct domains")
        print(f"  extracted signals  {signals}")
        print(f"  themes             {themes}")
        print(f"  opportunities      {opportunities}")
        print(f"  drafts             {drafts}")
        print(f"  voice examples     {voice}")
        print(f"  watchlist items    {watch}")

        print("\n  by source type:")
        for source_type, count in session.execute(
            select(Source.source_type, func.count(Source.id))
            .group_by(Source.source_type).order_by(func.count(Source.id).desc())
        ).all():
            print(f"    {source_type:<16} {count}")

        print("\n  by status:")
        for status, count in session.execute(
            select(Source.status, func.count(Source.id))
            .group_by(Source.status).order_by(func.count(Source.id).desc())
        ).all():
            print(f"    {status:<20} {count}")

        # ── evidence integrity ──────────────────────────────────────────
        print(h2("Evidence integrity"))
        rows = session.execute(
            select(ExtractedSignal.supporting_evidence, ExtractedSignal.notable_quotes,
                   ExtractedSignal.numerical_claims)
        ).all()
        passages = sum(len(r[0] or []) for r in rows)
        quotes = sum(len(r[1] or []) for r in rows)
        numbers = sum(len(r[2] or []) for r in rows)
        verified = sum(1 for r in rows for p in (r[0] or []) if p.get("verified_verbatim"))
        print(f"  verbatim evidence passages stored  {passages}  (verbatim-verified: {verified})")
        print(f"  verbatim quotes stored             {quotes}")
        print(f"  numerical claims (all flagged)     {numbers}")
        print("  Every passage above was re-checked against the stored source text before")
        print("  the database write. Anything that failed was discarded, not stored.")

        # ── themes ──────────────────────────────────────────────────────
        print(h2("Themes by trend status"))
        for theme in session.execute(
            select(Theme).order_by(Theme.source_count.desc())
        ).scalars().all():
            print(f"  [{theme.trend_status:<15}] {theme.name:<42} "
                  f"{theme.source_count:>3} src / {theme.distinct_domain_count:>2} domains  "
                  f"rel {theme.average_relevance:.1f}  ev {theme.average_evidence_strength:.1f}")

        # ── opportunities ───────────────────────────────────────────────
        print(h1(f"Top {args.top} content opportunities"))
        top = session.execute(
            select(ContentOpportunity)
            .order_by(ContentOpportunity.opportunity_score.desc())
            .limit(args.top)
        ).scalars().all()

        for rank, opportunity in enumerate(top, start=1):
            theme = session.get(Theme, opportunity.theme_id) if opportunity.theme_id else None
            print(h2(f"{rank}. {opportunity.title}"))
            print(f"  score {opportunity.opportunity_score:.0f}/100 · "
                  f"confidence {opportunity.confidence_score:.0f}/100 · "
                  f"risk {opportunity.risk_score:.0f}/100 · "
                  f"built by {opportunity.generation_method}")
            if theme:
                print(f"  theme: {theme.name} ({theme.trend_status}, "
                      f"{theme.source_count} sources / {theme.distinct_domain_count} domains)")
            print(f"\n  CORE INSIGHT\n    {opportunity.core_insight}")
            print(f"\n  WHY NOW\n    {opportunity.why_now}")
            print(f"\n  WHY PODIUM\n    {opportunity.why_podium}")
            print(f"\n  HOOK\n    {opportunity.hook}")
            print(f"\n  SUPPORTING POINTS ({len(opportunity.supporting_points or [])}) "
                  "— each with source id and verbatim passage")
            for point in (opportunity.supporting_points or []):
                ids = ", ".join(f"#{i}" for i in point.get("evidence_source_ids", []))
                print(f"    [{ids}] {point.get('point', '')[:150]}")
                print(f"          evidence: \"{point.get('evidence_passage', '')[:150]}\"")
                print(f"          {point.get('evidence_url', '')}")
            print(f"\n  SOURCES ({len(opportunity.supporting_source_ids or [])})")
            for source_id in (opportunity.supporting_source_ids or [])[:10]:
                source = session.get(Source, source_id)
                if source:
                    date = source.published_at.date().isoformat() if source.published_at else "no date"
                    print(f"    #{source.id} {source.source_domain} · {date} · "
                          f"{(source.title or '')[:70]}")
                    print(f"        {source.canonical_url}")
            print(f"\n  RISK NOTES")
            for note in (opportunity.risk_notes or [])[:6]:
                print(f"    - {note}")
            print(f"\n  VERIFICATION CHECKLIST ({len(opportunity.verification_checklist or [])} items)")
            for item in (opportunity.verification_checklist or [])[:6]:
                print(f"    [ ] {item.get('item', '')}")

        # ── drafts ──────────────────────────────────────────────────────
        print(h1("Drafts"))
        for draft in session.execute(
            select(ContentDraft).order_by(ContentDraft.id.desc()).limit(4)
        ).scalars().all():
            opportunity = session.get(ContentOpportunity, draft.content_opportunity_id)
            print(h2(f"Draft #{draft.id} — {draft.content_type}"))
            print(f"  opportunity: {opportunity.title if opportunity else '?'}")
            print(f"  evidence score {draft.evidence_score:.0f}/100 · "
                  f"voice {draft.voice_score:.0f}/100 · "
                  f"status {draft.approval_status} · built by {draft.generation_method}")
            print(f"  cited sources: {draft.cited_source_ids}")
            print("\n" + "\n".join("  | " + line for line in (draft.draft_text or "").split("\n")))
            if draft.unsupported_claims:
                print(f"\n  UNSUPPORTED SENTENCES FLAGGED ({len(draft.unsupported_claims)}):")
                for claim in draft.unsupported_claims[:5]:
                    print(f"    - {claim[:150]}")
            if draft.verification_required:
                print(f"\n  VERIFICATION REQUIRED ({len(draft.verification_required)}):")
                for item in draft.verification_required[:6]:
                    print(f"    - {item[:150]}")

    print("\n" + "=" * 78)
    print("Independent candidate project. Not affiliated with, authorised by, or")
    print("endorsed by Podium or Eric Rea. Nothing here has been published.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
