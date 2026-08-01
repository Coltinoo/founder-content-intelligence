"""Daily brief assembly and Markdown export."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..db import session_scope
from ..models import ContentDraft, ExtractedSignal, Source
from ..queries import (
    dashboard_counters,
    diversify_by_domain,
    is_aggregator,
    opportunities_list,
    themes_dataframe,
    watchlist_items,
)


def build_daily_brief(*, lookback_hours: int = 48, top_n: int = 5) -> dict:
    """Assemble the daily brief payload from the database."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=lookback_hours)
    counters = dashboard_counters()

    with session_scope() as session:
        rows = session.execute(
            select(Source, ExtractedSignal)
            .join(ExtractedSignal, ExtractedSignal.source_id == Source.id)
            .where(Source.discovered_at >= cutoff)
            .order_by(ExtractedSignal.opportunity_score.desc())
            .limit(top_n * 3)
        ).all()
        # Directory and funding-database pages score well on freshness and
        # relevance without saying anything about the market. They are already
        # filtered out of the dashboard's signal panel; the brief used a
        # different query and let them back in, so a company-profile listing
        # ranked as the day's second most important source.
        rows = [(s, sig) for s, sig in rows if not is_aggregator(s.source_domain)]
        # Same per-publisher cap the dashboard applies, so the two pages cannot
        # disagree about what the day's top sources were. On the current corpus
        # it changes nothing — no publisher exceeds the cap — but the brief was
        # the one ranked list in the app with no ceiling on how much of it a
        # single outlet could occupy.
        rows = diversify_by_domain(rows, top_n)
        new_sources = [
            {
                "id": s.id, "title": s.title or "(untitled)", "url": s.canonical_url,
                "domain": s.source_domain, "published_at": s.published_at,
                "theme": sig.primary_theme, "score": sig.opportunity_score,
                "risk": sig.risk_score, "problem": sig.customer_problem,
                "claim": sig.primary_claim,
                "evidence": (sig.supporting_evidence or [])[:1],
                "verification_notes": (sig.verification_notes or [])[:2],
                "method": sig.extraction_method,
            }
            for s, sig in rows[:top_n]
        ]

        pending = session.execute(
            select(ContentDraft)
            .where(ContentDraft.approval_status == "pending_review")
            .order_by(ContentDraft.created_at.desc())
            .limit(6)
        ).scalars().all()
        pending_drafts = [
            {
                "id": d.id, "type": d.content_type, "opportunity_id": d.content_opportunity_id,
                "evidence_score": d.evidence_score, "voice_score": d.voice_score,
                "unsupported": len(d.unsupported_claims or []),
                "verification": len(d.verification_required or []),
            }
            for d in pending
        ]

    themes = themes_dataframe()
    rising = []
    if not themes.empty:
        rising_frame = themes[themes["trend_status"].isin(["rising", "emerging"])]
        if rising_frame.empty:
            rising_frame = themes[themes["trend_status"] == "stable"]
        rising = rising_frame.sort_values(
            ["source_count", "avg_relevance"], ascending=False
        ).head(3).to_dict("records")

    opportunities = [
        o for o in opportunities_list()
        if o["status"] not in {"archived"}
    ][:top_n]

    watchlist = [w for w in watchlist_items(statuses=["unreviewed"])][:5]

    # Verification warnings across everything currently in flight.
    warnings: list[str] = []
    for source in new_sources:
        for note in source["verification_notes"]:
            warnings.append(f"[source #{source['id']}] {note}")
    for opportunity in opportunities:
        if (opportunity.get("risk") or 0) >= 50:
            warnings.append(
                f"[opportunity #{opportunity['id']}] Risk score {opportunity['risk']:.0f}/100 — "
                f"review risk notes before drafting."
            )
        if (opportunity.get("confidence") or 0) < 45:
            warnings.append(
                f"[opportunity #{opportunity['id']}] Confidence {opportunity['confidence']:.0f}/100 — "
                "evidence base is thin."
            )
    for draft in pending_drafts:
        if draft["unsupported"]:
            warnings.append(
                f"[draft #{draft['id']}] {draft['unsupported']} unsupported sentence(s) flagged."
            )

    return {
        "generated_at": datetime.now(timezone.utc),
        "lookback_hours": lookback_hours,
        "counters": counters,
        "new_sources": new_sources,
        "rising_themes": rising,
        "opportunities": opportunities,
        "watchlist": watchlist,
        "pending_drafts": pending_drafts,
        "warnings": warnings[:20],
    }


def brief_to_markdown(brief: dict) -> str:
    from .. import DISCLAIMER

    generated = brief["generated_at"].strftime("%Y-%m-%d %H:%M UTC")
    counters = brief["counters"]
    lines = [
        f"# Founder Content Intelligence — Daily Brief",
        f"_Generated {generated} · covering the last {brief['lookback_hours']} hours_",
        "",
        f"> {DISCLAIMER}",
        "",
        "## At a glance",
        "",
        f"- **{counters['total_sources']}** sources in the library "
        f"({counters['sources_24h']} added in the last 24h) across "
        f"**{counters['distinct_domains']}** domains",
        f"- **{counters['extracted_signals']}** extracted signals · "
        f"**{counters['themes']}** themes ({counters['rising_themes']} rising or emerging)",
        f"- **{counters['opportunities']}** content opportunities · "
        f"**{counters['drafts_pending']}** draft(s) awaiting human approval",
        f"- **{counters['needs_review']}** source(s) need review · "
        f"**{counters['policy_skipped']}** skipped by crawl policy",
        "",
    ]

    lines += ["## Most important new sources", ""]
    if brief["new_sources"]:
        for source in brief["new_sources"]:
            date = source["published_at"].date().isoformat() if source["published_at"] else "no date"
            lines.append(
                f"### {source['title']}\n"
                f"{source['domain']} · {date} · score **{source['score']:.0f}/100** · "
                f"risk {source['risk']:.0f}/100 · theme: {source['theme'] or 'unassigned'}\n"
            )
            if source["problem"]:
                lines.append(f"**Problem identified:** {source['problem']}\n")
            for passage in source["evidence"]:
                lines.append(f"> {passage.get('passage', '')}\n")
            lines.append(f"[Open source]({source['url']})\n")
    else:
        lines.append("_No new sources in this window._\n")

    lines += ["## Top three rising themes", ""]
    if brief["rising_themes"]:
        for theme in brief["rising_themes"]:
            lines.append(
                f"### {theme['name']} — {theme['trend_status']}\n"
                f"{theme['source_count']} source(s) across {theme['domains']} domain(s) and "
                f"{theme['industries']} industry/ies · "
                f"{theme['current_period']} this period vs {theme['previous_period']} last "
                f"({theme['growth_rate']:+.0%})\n"
            )
            if theme.get("rationale"):
                lines.append(f"{theme['rationale']}\n")
    else:
        lines.append("_No themes have met the trend threshold yet._\n")

    lines += ["## Recommended content actions", ""]
    if brief["opportunities"]:
        for opportunity in brief["opportunities"]:
            lines.append(
                f"- **{opportunity['title']}**  \n"
                f"  score {opportunity['score']:.0f}/100 · confidence "
                f"{opportunity['confidence']:.0f}/100 · risk {opportunity['risk']:.0f}/100 · "
                f"{opportunity['source_count']} source(s) · status: {opportunity['status']} · "
                f"suggested format: {opportunity['format']}"
            )
    else:
        lines.append("_No content opportunities have been generated yet._")
    lines.append("")

    lines += ["## Engagement opportunities (human review only)", ""]
    if brief["watchlist"]:
        for item in brief["watchlist"]:
            lines.append(
                f"- **{item['person_or_company']}** ({item['priority']} priority) — "
                f"{item['topic']}  \n"
                f"  {item['suggested_response_angle']}  \n"
                f"  [{item['url']}]({item['url']})"
            )
    else:
        lines.append("_Watchlist is empty._")
    lines.append("")
    lines.append(
        "_The system never comments, likes, reposts, follows, or messages. "
        "These are suggestions for a human to act on._"
    )
    lines.append("")

    lines += ["## Drafts awaiting approval", ""]
    if brief["pending_drafts"]:
        for draft in brief["pending_drafts"]:
            lines.append(
                f"- Draft #{draft['id']} ({draft['type']}) for opportunity "
                f"#{draft['opportunity_id']} — evidence {draft['evidence_score']:.0f}/100, "
                f"voice {draft['voice_score']:.0f}/100, "
                f"{draft['unsupported']} unsupported sentence(s), "
                f"{draft['verification']} verification item(s)"
            )
    else:
        lines.append("_No drafts pending._")
    lines.append("")

    lines += ["## Verification warnings", ""]
    if brief["warnings"]:
        for warning in brief["warnings"]:
            lines.append(f"- ⚠️ {warning}")
    else:
        lines.append("_No outstanding verification warnings._")
    lines += [
        "",
        "---",
        "",
        "**Nothing in this brief has been published. Nothing has been written or approved by "
        "Eric Rea or Podium. Every claim above is linked to the public source it came from; "
        "interpretation is labelled separately from evidence.**",
    ]
    return "\n".join(lines)
