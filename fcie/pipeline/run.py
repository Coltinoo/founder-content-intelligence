"""Full-pipeline orchestrator.

One entry point used by the dashboard button, the CLI script, and the scheduled
GitHub Action, so all three run exactly the same code path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..db import init_db, session_scope
from ..models import RunLog
from .engagement import build_watchlist
from .extract import run_extraction
from .ingest import run_ingestion
from .opportunities import generate_opportunities
from .trends import run_trend_analysis

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    run_id: int | None = None
    stages: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    setup_messages: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def summary_line(self) -> str:
        ingest = self.stages.get("ingest", {})
        extract = self.stages.get("extract", {})
        trends = self.stages.get("trends", {})
        opportunities = self.stages.get("opportunities", {})
        return (
            f"{ingest.get('stored', 0)} new source(s), "
            f"{ingest.get('duplicates', 0)} duplicate(s) merged, "
            f"{extract.get('succeeded', 0)} signal(s) extracted, "
            f"{trends.get('themes_updated', 0)} theme(s) updated, "
            f"{opportunities.get('created', 0)} new opportunity/ies."
        )


def run_full_pipeline(
    *,
    trigger: str = "manual",
    include_podium: bool = True,
    include_rss: bool = True,
    include_search: bool = True,
    include_youtube: bool = True,
    max_sources: int | None = None,
    force_heuristic: bool = False,
    build_engagement: bool = True,
    regenerate_opportunities: bool = False,
    progress=None,
) -> PipelineResult:
    """Discovery → extraction → trends → opportunities → watchlist."""
    started = datetime.now(timezone.utc)
    init_db()
    result = PipelineResult()

    def emit(message: str) -> None:
        log.info(message)
        if progress:
            try:
                progress(message)
            except Exception:  # noqa: BLE001
                pass

    with session_scope() as session:
        run = RunLog(trigger=trigger, started_at=started.replace(tzinfo=None))
        session.add(run)
        session.flush()
        result.run_id = run.id

    # ── 1. ingest ───────────────────────────────────────────────────────
    emit("── Stage 1/5: source discovery and ingestion")
    try:
        ingest = run_ingestion(
            include_podium=include_podium, include_rss=include_rss,
            include_search=include_search, include_youtube=include_youtube,
            max_sources=max_sources, progress=progress,
        )
        result.stages["ingest"] = ingest.as_dict()
        result.errors.extend(ingest.errors[:20])
        result.setup_messages.extend(ingest.setup_messages)
    except Exception as exc:  # noqa: BLE001
        message = f"Ingestion stage failed: {exc.__class__.__name__}: {exc}"
        log.exception(message)
        result.errors.append(message)
        result.stages["ingest"] = {"error": message}

    # ── 2. extract ──────────────────────────────────────────────────────
    emit("── Stage 2/5: AI structured extraction")
    try:
        extract = run_extraction(force_heuristic=force_heuristic, progress=progress)
        result.stages["extract"] = extract.as_dict()
        result.errors.extend(extract.errors[:20])
        if extract.backend == "heuristic":
            result.setup_messages.append(f"extraction: {extract.backend_note}")
    except Exception as exc:  # noqa: BLE001
        message = f"Extraction stage failed: {exc.__class__.__name__}: {exc}"
        log.exception(message)
        result.errors.append(message)
        result.stages["extract"] = {"error": message}

    # ── 3. trends ───────────────────────────────────────────────────────
    emit("── Stage 3/5: theme clustering and trend detection")
    try:
        trends = run_trend_analysis(progress=progress)
        result.stages["trends"] = trends.as_dict()
        result.errors.extend(trends.errors[:20])
    except Exception as exc:  # noqa: BLE001
        message = f"Trend stage failed: {exc.__class__.__name__}: {exc}"
        log.exception(message)
        result.errors.append(message)
        result.stages["trends"] = {"error": message}

    # ── 4. opportunities ────────────────────────────────────────────────
    emit("── Stage 4/5: content opportunity and brief generation")
    try:
        opportunities = generate_opportunities(
            force_heuristic=force_heuristic,
            force_regenerate=regenerate_opportunities,
            progress=progress,
        )
        result.stages["opportunities"] = opportunities.as_dict()
        result.errors.extend(opportunities.errors[:20])
    except Exception as exc:  # noqa: BLE001
        message = f"Opportunity stage failed: {exc.__class__.__name__}: {exc}"
        log.exception(message)
        result.errors.append(message)
        result.stages["opportunities"] = {"error": message}

    # ── 5. engagement watchlist ─────────────────────────────────────────
    if build_engagement:
        emit("── Stage 5/5: engagement watchlist")
        try:
            engagement = build_watchlist(force_heuristic=force_heuristic)
            result.stages["engagement"] = engagement.as_dict()
            result.errors.extend(engagement.errors[:10])
        except Exception as exc:  # noqa: BLE001
            message = f"Engagement stage failed: {exc.__class__.__name__}: {exc}"
            log.exception(message)
            result.errors.append(message)
            result.stages["engagement"] = {"error": message}

    finished = datetime.now(timezone.utc)
    result.duration_seconds = round((finished - started).total_seconds(), 1)

    with session_scope() as session:
        run = session.get(RunLog, result.run_id)
        if run is not None:
            run.finished_at = finished.replace(tzinfo=None)
            run.stages = result.stages
            run.errors = result.errors[:50]
            run.sources_discovered = result.stages.get("ingest", {}).get("discovered", 0)
            run.sources_fetched = result.stages.get("ingest", {}).get("stored", 0)
            run.sources_duplicate = result.stages.get("ingest", {}).get("duplicates", 0)
            run.signals_extracted = result.stages.get("extract", {}).get("succeeded", 0)
            run.themes_updated = result.stages.get("trends", {}).get("themes_updated", 0)
            run.opportunities_created = result.stages.get("opportunities", {}).get("created", 0)
            run.notes = "; ".join(result.setup_messages[:5])
            session.add(run)

    emit(f"── Pipeline finished in {result.duration_seconds}s: {result.summary_line()}")
    return result
