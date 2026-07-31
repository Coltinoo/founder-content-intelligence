"""Extraction stage: run the analyser over stored sources and persist signals."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from ..ai.extraction import Extractor
from ..db import session_scope
from ..models import ExtractedSignal, Source
from ..utils.text import naive_utc

log = logging.getLogger(__name__)

EXTRACTABLE_STATUSES = {"fetched", "extracted", "needs_review", "summary_only"}


@dataclass
class ExtractReport:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    backend: str = "heuristic"
    backend_note: str = ""
    errors: list[str] = field(default_factory=list)
    signal_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "backend": self.backend,
            "backend_note": self.backend_note,
            "errors": self.errors[:50],
        }


def run_extraction(
    *,
    source_ids: list[int] | None = None,
    only_new: bool = True,
    limit: int | None = None,
    force_heuristic: bool = False,
    progress=None,
) -> ExtractReport:
    """Extract structured signals from sources that do not yet have one."""
    extractor = Extractor(force_heuristic=force_heuristic)
    report = ExtractReport(backend=extractor.backend, backend_note=extractor.backend_note)

    def emit(message: str) -> None:
        log.info(message)
        if progress:
            try:
                progress(message)
            except Exception:  # noqa: BLE001
                pass

    with session_scope() as session:
        query = select(Source).where(Source.status.in_(EXTRACTABLE_STATUSES))
        if source_ids:
            query = select(Source).where(Source.id.in_(source_ids))
        if only_new and not source_ids:
            already = select(ExtractedSignal.source_id)
            query = query.where(Source.id.not_in(already))
        query = query.order_by(Source.discovered_at.desc())
        if limit:
            query = query.limit(limit)
        targets = session.execute(query).scalars().all()
        payloads = [
            {
                "id": s.id,
                "text": s.cleaned_text or "",
                "title": s.title,
                "url": s.canonical_url,
                "published_at": s.published_at,
                "source_type": s.source_type,
                "domain": s.source_domain,
                "metadata": dict(s.metadata_json or {}),
                "search_query": s.search_query,
            }
            for s in targets
        ]

    emit(f"Extracting {len(payloads)} source(s) using the {report.backend} backend.")

    for index, payload in enumerate(payloads, start=1):
        if not payload["text"] or len(payload["text"].split()) < 25:
            report.skipped += 1
            _mark_unextractable(payload["id"], "Body text too short to analyse.")
            continue

        report.processed += 1
        metadata = payload["metadata"]
        metadata["search_query"] = payload["search_query"]

        try:
            result = extractor.extract(
                text=payload["text"],
                title=payload["title"],
                url=payload["url"],
                published_at=payload["published_at"],
                source_type=payload["source_type"],
                domain=payload["domain"],
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001
            message = f"source {payload['id']}: {exc.__class__.__name__}: {exc}"
            log.exception(message)
            report.errors.append(message)
            report.failed += 1
            _mark_unextractable(payload["id"], message)
            continue

        signal_id = _persist(payload["id"], result)
        report.signal_ids.append(signal_id)
        report.succeeded += 1

        if index % 10 == 0:
            emit(f"  extracted {index}/{len(payloads)}")

    emit(f"Extraction complete: {report.succeeded} succeeded, {report.failed} failed, "
         f"{report.skipped} skipped.")
    return report


def _persist(source_id: int, result) -> int:
    """Insert or replace the signal for a source (reprocessing is idempotent)."""
    with session_scope() as session:
        existing = session.execute(
            select(ExtractedSignal).where(ExtractedSignal.source_id == source_id)
        ).scalars().all()
        for row in existing:
            session.delete(row)

        signal = ExtractedSignal(
            source_id=source_id,
            primary_entity=result.primary_entity,
            secondary_entities=result.secondary_entities,
            industries=result.industries,
            customer_segment=result.customer_segment,
            primary_theme=result.primary_theme,
            secondary_themes=result.secondary_themes,
            customer_problem=result.customer_problem,
            primary_claim=result.primary_claim,
            supporting_evidence=result.supporting_evidence,
            notable_quotes=result.notable_quotes,
            numerical_claims=result.numerical_claims,
            founder_relevance=result.founder_relevance,
            podium_relevance=result.podium_relevance,
            novelty_score=result.novelty_score,
            freshness_score=result.freshness_score,
            evidence_strength=result.evidence_strength,
            business_impact=result.business_impact,
            risk_score=result.risk_score,
            opportunity_score=result.opportunity_score,
            score_breakdown=result.score_breakdown,
            risk_breakdown=result.risk_breakdown,
            content_opportunity=result.content_opportunity,
            potential_angle=result.potential_angle,
            recommended_format=result.recommended_format,
            is_familiar_narrative=result.is_familiar_narrative,
            is_promotional_source=result.is_promotional_source,
            is_summary_only=result.is_summary_only,
            verification_notes=result.verification_notes,
            extraction_model=result.extraction_model,
            extraction_method=result.extraction_method,
            extraction_error=result.extraction_error,
            extracted_at=naive_utc(result.extracted_at),
        )
        session.add(signal)

        source = session.get(Source, source_id)
        if source is not None and source.status in EXTRACTABLE_STATUSES:
            source.status = "extracted"
            session.add(source)

        session.flush()
        return signal.id


def _mark_unextractable(source_id: int, reason: str) -> None:
    with session_scope() as session:
        source = session.get(Source, source_id)
        if source is None:
            return
        metadata = dict(source.metadata_json or {})
        metadata["extraction_skipped_reason"] = reason
        source.metadata_json = metadata
        if source.status == "fetched":
            source.status = "needs_review"
        session.add(source)
