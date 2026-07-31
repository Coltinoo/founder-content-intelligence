#!/usr/bin/env python
"""Check every configured RSS feed and report which ones actually work.

Usage:
    python scripts/verify_feeds.py
    python scripts/verify_feeds.py --disable-broken   # rewrite config/feeds.yaml
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401  (sets sys.path and console encoding)

import feedparser  # noqa: E402

from fcie.config import load_config, write_yaml  # noqa: E402
from fcie.utils.http import PoliteFetcher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify configured RSS feeds.")
    parser.add_argument("--disable-broken", action="store_true",
                        help="Set enabled: false on feeds that return no entries.")
    args = parser.parse_args()

    cfg = load_config()
    feeds = cfg.feeds.get("feeds", [])
    if not feeds:
        print("No feeds configured.")
        return 0

    print(f"Checking {len(feeds)} feed(s) with UA: {cfg.crawl.user_agent}")
    print(f"Timeout: {cfg.crawl.request_timeout}s per feed\n")
    fetcher = PoliteFetcher(delay_seconds=0.5)
    results = []
    for feed in feeds:
        name, url = feed.get("name", "?"), feed.get("url", "")
        body, error = fetcher.fetch_feed(url)
        if error:
            count, ok, note = 0, False, error
        else:
            try:
                parsed = feedparser.parse(body)
                count = len(parsed.entries)
                ok = count > 0
                note = "" if ok else (str(getattr(parsed, "bozo_exception", "")) or "no entries")
            except Exception as exc:  # noqa: BLE001
                count, ok, note = 0, False, f"{exc.__class__.__name__}: {exc}"

        icon = "OK " if ok else "FAIL"
        print(f"[{icon}] {name:<38} {count:>3} entries  {note[:70]}")
        results.append({"feed": feed, "ok": ok, "count": count})
    fetcher.close()

    working = sum(1 for r in results if r["ok"])
    print(f"\n{working}/{len(results)} feed(s) returned entries.")

    if args.disable_broken:
        payload = {"feeds": []}
        for result in results:
            feed = dict(result["feed"])
            feed["enabled"] = bool(result["ok"]) and feed.get("enabled", True)
            feed["verified"] = bool(result["ok"])
            payload["feeds"].append(feed)
        write_yaml("feeds.yaml", payload)
        print(f"config/feeds.yaml updated — {working} feed(s) left enabled.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
