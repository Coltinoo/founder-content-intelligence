"""Ingestion: discovery → fetch → clean → deduplicate → store.

Every stage is fault-tolerant. A dead feed, a 403, or a robots disallow is
recorded against the source or the run and the pipeline continues.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from ..config import load_config
from ..connectors.base import ConnectorResult, DiscoveredItem
from ..connectors.podium_site import PodiumSiteConnector
from ..connectors.social import SocialDiscoveryConnector
from ..connectors.rss import RSSConnector
from ..connectors.web_search import WebSearchConnector
from ..connectors.youtube import YouTubeConnector
from ..db import session_scope
from ..models import Source
from ..utils.article import parse_html
from ..utils.dedupe import CandidateRecord, find_duplicate, merge_discovery_metadata
from ..utils.hashing import content_hash
from ..utils.http import PoliteFetcher
from ..utils.text import clean_text, naive_utc, word_count
from ..utils.urls import canonicalize, domain_of, normalize_url

log = logging.getLogger(__name__)

MIN_BODY_WORDS = 80      # below this we keep the row but mark it needs_review
MIN_SUMMARY_WORDS = 40   # publisher-supplied RSS summary worth analysing on its own

# Longest we will sleep for one host's polite slot inside a run. Hosts whose
# robots Crawl-delay puts the next slot further out than this get their items
# deferred (or their RSS summary used) instead of stalling the whole run —
# searchengineland.com declares Crawl-delay: 600, i.e. ten minutes per page.
MAX_POLITE_WAIT_SECONDS = 30.0


@dataclass
class IngestReport:
    discovered: int = 0
    stored: int = 0
    duplicates: int = 0
    fetch_errors: int = 0
    skipped_policy: int = 0
    needs_review: int = 0
    deferred: int = 0    # host crawl-delay too large to queue behind this run
    connector_summaries: list[str] = field(default_factory=list)
    connector_status: dict[str, dict] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    setup_messages: list[str] = field(default_factory=list)
    stored_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "discovered": self.discovered,
            "stored": self.stored,
            "duplicates": self.duplicates,
            "fetch_errors": self.fetch_errors,
            "skipped_policy": self.skipped_policy,
            "needs_review": self.needs_review,
            "deferred": self.deferred,
            "connectors": self.connector_status,
            "errors": self.errors[:50],
            "setup_messages": self.setup_messages,
        }


def run_ingestion(
    *,
    include_podium: bool = True,
    include_rss: bool = True,
    include_search: bool = True,
    include_youtube: bool = True,
    max_sources: int | None = None,
    fetch_bodies: bool = True,
    progress=None,
) -> IngestReport:
    """Discover from every enabled connector and persist new sources."""
    cfg = load_config()
    report = IngestReport()
    limit = max_sources or cfg.crawl.max_sources_per_run
    fetcher = PoliteFetcher()

    def emit(message: str) -> None:
        log.info(message)
        if progress:
            try:
                progress(message)
            except Exception:  # noqa: BLE001 - UI callback must never break a run
                pass

    connectors: list = []
    if include_podium:
        connectors.append(PodiumSiteConnector(fetcher=fetcher))
    if include_rss:
        connectors.append(RSSConnector(fetcher=fetcher))
    if include_search:
        connectors.append(WebSearchConnector(fetcher=fetcher))
        connectors.append(SocialDiscoveryConnector(fetcher=fetcher))
    if include_youtube:
        connectors.append(YouTubeConnector(fetcher=fetcher))

    # Connectors hit disjoint hosts, so running them concurrently is pure win:
    # per-domain politeness is enforced inside the shared PoliteFetcher (its
    # RateLimiter and RobotsCache are thread-safe), while the Podium crawl no
    # longer has to finish before the first RSS feed is even opened.
    all_items: list[DiscoveredItem] = []
    emit("Discovering from " + ", ".join(c.name for c in connectors) + " (concurrent) …")

    def _discover(connector) -> ConnectorResult:
        return connector.discover()

    with ThreadPoolExecutor(max_workers=max(len(connectors), 1),
                            thread_name_prefix="discover") as pool:
        futures = {pool.submit(_discover, c): c for c in connectors}
        for future in as_completed(futures):
            connector = futures[future]
            try:
                result: ConnectorResult = future.result()
            except Exception as exc:  # noqa: BLE001
                message = f"{connector.name} crashed: {exc.__class__.__name__}: {exc}"
                log.exception(message)
                report.errors.append(message)
                report.connector_status[connector.name] = {"ok": False, "error": message}
                continue

            report.connector_summaries.append(result.summary())
            report.connector_status[connector.name] = {
                "ok": result.configured,
                "configured": result.configured,
                "items": result.count,
                "errors": result.errors[:10],
                "skipped": result.skipped[:10],
                "requests": result.requests_made,
                "setup_message": result.setup_message,
            }
            if not result.configured:
                report.setup_messages.append(f"{connector.name}: {result.setup_message}")
                emit(f"  {connector.name}: not configured — skipped")
                continue

            report.errors.extend(f"{connector.name}: {e}" for e in result.errors[:10])
            report.skipped_policy += len(result.skipped)
            all_items.extend(result.items)
            emit(f"  {connector.name}: {result.count} candidate(s)")

    report.discovered = len(all_items)
    emit(f"Discovered {report.discovered} candidate source(s); storing up to {limit}.")
    all_items = _interleave_by_channel(all_items)

    # Cap fetch *attempts*, not just stored rows. Without this a run that hits a
    # long tail of duplicates or errors keeps fetching (and rate-limiting) through
    # every candidate, which can take far longer than the source cap implies.
    max_attempts = max(limit * 3, limit + 40)
    attempts = 0
    processed = 0

    # Two-phase batches: prefetch article bodies concurrently (network-bound,
    # spread across many domains — the per-domain limiter keeps each host
    # polite), then dedupe and write sequentially (SQLite wants one writer).
    # This is where the run time lives: serial fetching of ~60 bodies at 1-2s
    # politeness each is minutes of pure waiting for unrelated hosts.
    batch_size = 16

    def _prepare(item: DiscoveredItem) -> tuple[DiscoveredItem, dict | None, str | None]:
        try:
            return item, _prepare_item(
                item, fetcher=fetcher, fetch_bodies=fetch_bodies,
                polite_max_wait=MAX_POLITE_WAIT_SECONDS,
            ), None
        except Exception as exc:  # noqa: BLE001
            return item, None, f"{exc.__class__.__name__}: {exc}"

    position = 0
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="fetch") as pool:
        while position < len(all_items):
            if len(report.stored_ids) >= limit:
                emit(f"Reached the {limit}-source cap for this run.")
                break
            if attempts >= max_attempts:
                emit(
                    f"Reached the {max_attempts}-attempt ceiling after storing "
                    f"{len(report.stored_ids)} source(s); {len(all_items) - position} "
                    "candidate(s) left for the next run."
                )
                report.errors.append(
                    f"Attempt ceiling ({max_attempts}) reached — remaining candidates deferred."
                )
                break

            batch = all_items[position: position + batch_size]
            position += len(batch)
            attempts += len(batch)

            # Phase 1: fetch bodies in parallel, preserving batch order so the
            # interleaved channel fairness survives into the store phase.
            prepared = list(pool.map(_prepare, batch))

            # Phase 2: sequential dedupe + write.
            for item, payload, error in prepared:
                if len(report.stored_ids) >= limit:
                    break
                if error is not None or payload is None:
                    message = f"{item.source_url}: {error or 'prepare failed'}"
                    log.error(message)
                    report.errors.append(message)
                    continue
                try:
                    outcome = _store_prepared(payload)
                except Exception as exc:  # noqa: BLE001
                    message = f"{item.source_url}: {exc.__class__.__name__}: {exc}"
                    log.exception(message)
                    report.errors.append(message)
                    continue

                processed += 1
                if outcome["result"] == "stored":
                    report.stored += 1
                    report.stored_ids.append(outcome["id"])
                    if outcome.get("needs_review"):
                        report.needs_review += 1
                elif outcome["result"] == "duplicate":
                    report.duplicates += 1
                elif outcome["result"] == "fetch_error":
                    report.fetch_errors += 1
                elif outcome["result"] == "policy_skip":
                    report.skipped_policy += 1
                elif outcome["result"] == "deferred":
                    report.deferred += 1

            emit(f"  processed {processed}/{len(all_items)} — {report.stored} stored, "
                 f"{report.duplicates} duplicate(s)")

    fetcher.close()
    emit(
        f"Ingestion complete: {report.stored} stored, {report.duplicates} duplicate(s), "
        f"{report.fetch_errors} fetch error(s), {report.skipped_policy} skipped by policy, "
        f"{report.deferred} deferred (host crawl-delay)."
    )
    return report


def _interleave_by_channel(items: list[DiscoveredItem]) -> list[DiscoveredItem]:
    """Round-robin across connectors, newest-first inside each one.

    A plain date sort starves undated first-party content: Podium's marketing
    pages carry no publication date, so every dated RSS item outranks them and
    consumes the entire per-run budget before a single Podium page is reached.
    Interleaving guarantees each channel a proportional share of the cap while
    still preferring the freshest material within a channel.
    """
    buckets: dict[str, list[DiscoveredItem]] = defaultdict(list)
    for item in items:
        buckets[item.source_type].append(item)

    for bucket in buckets.values():
        bucket.sort(
            key=lambda item: naive_utc(item.published_at) or datetime(1970, 1, 1),
            reverse=True,
        )

    # Deterministic channel order; first-party and manual content first so a
    # small cap still yields a representative corpus.
    priority = ["podium_site", "manual", "youtube", "web_search", "rss"]
    ordered_keys = [k for k in priority if k in buckets]
    ordered_keys += [k for k in sorted(buckets) if k not in priority]

    interleaved: list[DiscoveredItem] = []
    position = 0
    while any(len(buckets[k]) > position for k in ordered_keys):
        for key in ordered_keys:
            if len(buckets[key]) > position:
                interleaved.append(buckets[key][position])
        position += 1
    return interleaved


def ingest_manual_item(item: DiscoveredItem) -> dict:
    """Store one human-supplied source. Same dedupe path as everything else."""
    return _store_item(item, fetcher=None, fetch_bodies=False)


def _store_item(item: DiscoveredItem, *, fetcher: PoliteFetcher | None,
                fetch_bodies: bool) -> dict:
    """Fetch (if needed), deduplicate, and persist a single discovered item.

    Kept as the single-item entry point (manual entry, tests). The batch path
    in :func:`run_ingestion` calls the two phases separately so fetches can run
    concurrently while writes stay sequential.
    """
    return _store_prepared(_prepare_item(item, fetcher=fetcher, fetch_bodies=fetch_bodies))


def _prepare_item(item: DiscoveredItem, *, fetcher: PoliteFetcher | None,
                  fetch_bodies: bool, polite_max_wait: float | None = None) -> dict:
    """Network + CPU phase: fetch the body, parse, clean, hash. No database.

    Thread-safe: touches only this item and the (internally-locked) fetcher,
    so a pool can run many of these against different hosts at once.
    ``polite_max_wait`` bounds how long we will sleep for one host's polite
    slot; beyond it the item is deferred rather than stalling the batch.
    """
    canonical = normalize_url(item.source_url)
    domain = domain_of(canonical) or item.metadata.get("source_domain", "")

    raw_text = item.raw_text or ""
    cleaned = item.metadata.get("cleaned_text") or ""
    title = item.title
    author = item.author
    published = item.published_at
    fetch_error: str | None = None
    status = "fetched"
    fetched_at = datetime.now(timezone.utc)
    http_status = item.metadata.get("http_status")

    # ── fetch the body when the connector only gave us a link ───────────
    if item.needs_fetch and fetch_bodies and fetcher is not None:
        fetched = fetcher.fetch(item.source_url, max_wait=polite_max_wait)
        http_status = fetched.status_code
        if fetched.ok:
            article = parse_html(fetched.html, fetched.final_url or item.source_url)
            canonical = article.canonical_url or canonical
            raw_text = fetched.html
            cleaned = article.text
            title = title or article.title
            author = author or article.author
            published = published or article.published_at
            item.metadata.setdefault("extractor", article.extractor)
            item.metadata.setdefault("is_promotional", article.is_promotional)
        else:
            fetch_error = fetched.error
            if fetched.blocked_by_policy:
                status = f"skipped_{fetched.skipped_reason}"
            else:
                status = "error"
            # Fall back to the feed/search summary so the signal is not lost.
            cleaned = clean_text(item.summary) or ""
            raw_text = raw_text or item.summary
            item.metadata["body_unavailable_reason"] = fetched.error
            item.metadata["used_summary_fallback"] = bool(cleaned)

    if not cleaned:
        cleaned = clean_text(raw_text or item.summary)

    words = word_count(cleaned)
    needs_review = False
    if status == "fetched" and words < MIN_BODY_WORDS:
        status = "needs_review"
        needs_review = True

    # The full article body may be unavailable (paywall, bot challenge, 403) while
    # the publisher's own RSS summary is available — syndication is exactly what
    # that feed exists for. Keep it as a first-class but clearly-labelled source
    # rather than discarding lawfully-published content. Nothing was bypassed:
    # the restriction is recorded in `fetch_error` and the row is marked
    # `summary_only`, which caps its evidence weight downstream.
    if status.startswith("skipped_") and words >= MIN_SUMMARY_WORDS:
        item.metadata["body_restricted_status"] = status
        item.metadata["summary_only"] = True
        status = "summary_only"

    # A crawl-delay deferral with no usable summary produces no row at all: we
    # made no request, learned nothing, and the item will be rediscovered on a
    # future run when the host's polite slot is actually available.
    if status == "skipped_crawl_delay_deferred":
        return {"item": item, "deferred": True, "fetch_error": fetch_error,
                "canonical": canonical, "domain": domain}

    return {
        "item": item,
        "canonical": canonical,
        "domain": domain,
        "raw_text": raw_text,
        "cleaned": cleaned,
        "title": title,
        "author": author,
        "published": published,
        "fetch_error": fetch_error,
        "status": status,
        "fetched_at": fetched_at,
        "http_status": http_status,
        "words": words,
        "needs_review": needs_review,
        "text_hash": content_hash(cleaned) if cleaned else None,
    }


def _store_prepared(prepared: dict) -> dict:
    """Database phase: dedupe against existing rows and persist. Sequential."""
    if prepared.get("deferred"):
        return {"result": "deferred", "reason": prepared.get("fetch_error"),
                "url": prepared.get("canonical")}

    item: DiscoveredItem = prepared["item"]
    canonical = prepared["canonical"]
    domain = prepared["domain"]
    raw_text = prepared["raw_text"]
    cleaned = prepared["cleaned"]
    title = prepared["title"]
    author = prepared["author"]
    published = prepared["published"]
    fetch_error = prepared["fetch_error"]
    status = prepared["status"]
    fetched_at = prepared["fetched_at"]
    http_status = prepared["http_status"]
    words = prepared["words"]
    needs_review = prepared["needs_review"]
    text_hash = prepared["text_hash"]

    with session_scope() as session:
        # Compare against a bounded, relevant candidate set rather than the
        # whole table: same domain, plus anything sharing the exact hash.
        candidates = session.execute(
            select(Source.id, Source.canonical_url, Source.content_hash,
                   Source.title, Source.cleaned_text)
            .where((Source.source_domain == domain) | (Source.content_hash == text_hash))
            .limit(400)
        ).all()
        records = [
            CandidateRecord(id=r[0], canonical_url=r[1], content_hash=r[2],
                            title=r[3], cleaned_text=r[4])
            for r in candidates
        ]
        # Always include an exact canonical hit even if the domain differs.
        exact = session.execute(
            select(Source.id, Source.canonical_url, Source.content_hash,
                   Source.title, Source.cleaned_text)
            .where(Source.canonical_url == canonical)
        ).first()
        if exact and not any(r.id == exact[0] for r in records):
            records.append(CandidateRecord(id=exact[0], canonical_url=exact[1],
                                           content_hash=exact[2], title=exact[3],
                                           cleaned_text=exact[4]))

        verdict = find_duplicate(canonical, cleaned, title, records, text_hash=text_hash)

        if verdict.is_duplicate:
            existing = session.get(Source, verdict.matched_id)
            if existing is not None:
                existing.metadata_json = merge_discovery_metadata(
                    existing.metadata_json or {},
                    new_query=item.search_query,
                    new_source_type=item.source_type,
                    new_url=canonical,
                )
                existing.metadata_json["last_rediscovered_at"] = fetched_at.isoformat()
                existing.metadata_json.setdefault("duplicate_detections", []).append({
                    "method": verdict.method,
                    "score": verdict.score,
                    "detail": verdict.detail,
                    "url": canonical,
                    "at": fetched_at.isoformat(),
                })
                session.add(existing)
            return {
                "result": "duplicate",
                "id": verdict.matched_id,
                "method": verdict.method,
                "detail": verdict.detail,
            }

        metadata = dict(item.metadata)
        metadata.pop("cleaned_text", None)   # stored in its own column
        metadata.update({
            "discovered_by_queries": [item.search_query] if item.search_query else [],
            "discovered_by_channels": [item.source_type],
            "word_count": words,
            "http_status": http_status,
            "has_publication_date": published is not None,
            "summary": item.summary[:1000] if item.summary else "",
        })

        source = Source(
            source_type=item.source_type,
            source_url=item.source_url,
            canonical_url=canonical,
            source_domain=domain,
            title=title,
            author=author,
            published_at=naive_utc(published),
            discovered_at=naive_utc(fetched_at),
            fetched_at=naive_utc(fetched_at),
            search_query=item.search_query,
            raw_text=(raw_text or "")[:400_000],
            cleaned_text=cleaned,
            content_hash=text_hash,
            status=status,
            fetch_error=fetch_error,
            metadata_json=metadata,
        )
        session.add(source)
        session.flush()
        source_id = source.id

    if status == "summary_only":
        return {"result": "stored", "id": source_id, "needs_review": False,
                "summary_only": True, "reason": fetch_error}
    if status.startswith("skipped_"):
        return {"result": "policy_skip", "id": source_id, "reason": fetch_error}
    if status == "error":
        return {"result": "fetch_error", "id": source_id, "reason": fetch_error}
    return {"result": "stored", "id": source_id, "needs_review": needs_review}
