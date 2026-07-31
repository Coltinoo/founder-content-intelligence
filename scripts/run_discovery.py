#!/usr/bin/env python
"""Run the full pipeline from the command line.

Usage:
    python scripts/run_discovery.py
    python scripts/run_discovery.py --max-sources 40 --no-search
    python scripts/run_discovery.py --stage ingest --stage extract
    python scripts/run_discovery.py --force-heuristic --json
"""

from __future__ import annotations

import argparse
import json
import logging

import _bootstrap  # noqa: F401  (sets sys.path and console encoding)

from fcie.config import load_config  # noqa: E402
from fcie.db import describe_backend, init_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FCIE discovery pipeline.")
    parser.add_argument("--max-sources", type=int, default=None)
    parser.add_argument("--no-podium", action="store_true")
    parser.add_argument("--no-rss", action="store_true")
    parser.add_argument("--no-search", action="store_true")
    parser.add_argument("--no-youtube", action="store_true")
    parser.add_argument("--no-engagement", action="store_true")
    parser.add_argument("--force-heuristic", action="store_true",
                        help="Use the deterministic analyser even if OPENAI_API_KEY is set.")
    parser.add_argument("--regenerate-briefs", action="store_true")
    parser.add_argument(
        "--stage", action="append",
        choices=["ingest", "extract", "trends", "opportunities", "engagement"],
        help="Run only these stages (repeatable). Default: all.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a JSON summary.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config()
    init_db()

    if not args.quiet:
        print(f"Database: {describe_backend()}")
        for row in cfg.integration_status():
            icon = {"yes": "OK ", "fallback": "~  ", "no": "-- "}.get(row["ready"], "?  ")
            print(f"  [{icon}] {row['integration']}: {row['status']}")
        print()

    def progress(message: str) -> None:
        if not args.quiet:
            print(f"  {message}")

    stages = set(args.stage) if args.stage else None
    payload: dict = {}

    if stages is None:
        from fcie.pipeline.run import run_full_pipeline

        result = run_full_pipeline(
            trigger="cli",
            include_podium=not args.no_podium,
            include_rss=not args.no_rss,
            include_search=not args.no_search,
            include_youtube=not args.no_youtube,
            max_sources=args.max_sources,
            force_heuristic=args.force_heuristic,
            build_engagement=not args.no_engagement,
            regenerate_opportunities=args.regenerate_briefs,
            progress=progress,
        )
        payload = {
            "run_id": result.run_id, "duration_seconds": result.duration_seconds,
            "stages": result.stages, "errors": result.errors,
            "setup_messages": result.setup_messages, "summary": result.summary_line(),
        }
        if not args.quiet:
            print(f"\n✔ {result.summary_line()}  ({result.duration_seconds}s)")
            for message in result.setup_messages:
                print(f"  ⚙ {message}")
    else:
        if "ingest" in stages:
            from fcie.pipeline.ingest import run_ingestion

            report = run_ingestion(
                include_podium=not args.no_podium, include_rss=not args.no_rss,
                include_search=not args.no_search, include_youtube=not args.no_youtube,
                max_sources=args.max_sources, progress=progress,
            )
            payload["ingest"] = report.as_dict()
        if "extract" in stages:
            from fcie.pipeline.extract import run_extraction

            payload["extract"] = run_extraction(
                force_heuristic=args.force_heuristic, progress=progress
            ).as_dict()
        if "trends" in stages:
            from fcie.pipeline.trends import run_trend_analysis

            payload["trends"] = run_trend_analysis(progress=progress).as_dict()
        if "opportunities" in stages:
            from fcie.pipeline.opportunities import generate_opportunities

            payload["opportunities"] = generate_opportunities(
                force_heuristic=args.force_heuristic,
                force_regenerate=args.regenerate_briefs, progress=progress,
            ).as_dict()
        if "engagement" in stages:
            from fcie.pipeline.engagement import build_watchlist

            payload["engagement"] = build_watchlist(
                force_heuristic=args.force_heuristic
            ).as_dict()

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
