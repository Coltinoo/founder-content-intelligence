#!/usr/bin/env python
"""Verify the configured YouTube channel IDs against the public Atom feed.

The channel-RSS fallback needs a real channel ID (the ``UC...`` form, not the
@handle). This script checks each configured id and, when given ``--resolve``,
looks a handle's canonical channel id out of the public channel page.

Usage:
    python scripts/verify_youtube.py
    python scripts/verify_youtube.py --resolve @podium
"""

from __future__ import annotations

import argparse
import re

import _bootstrap  # noqa: F401  (sets sys.path and console encoding)

import feedparser  # noqa: E402

from fcie.config import load_config  # noqa: E402
from fcie.utils.http import PoliteFetcher  # noqa: E402

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"


def check(channel_id: str, user_agent: str) -> tuple[bool, str]:
    parsed = feedparser.parse(FEED.format(channel_id), agent=user_agent)
    if parsed.entries:
        return True, f"{len(parsed.entries)} video(s); latest: {parsed.entries[0].title[:60]}"
    return False, f"no entries (HTTP {getattr(parsed, 'status', '?')})"


def resolve(handle: str, fetcher: PoliteFetcher) -> str | None:
    """Read the canonical channel id off a public channel page."""
    handle = handle.lstrip("@")
    result = fetcher.fetch(f"https://www.youtube.com/@{handle}")
    if not result.ok:
        print(f"  could not fetch the channel page: {result.error}")
        return None
    match = re.search(r'"(?:channelId|externalId)"\s*:\s*"(UC[\w-]{22})"', result.html)
    if match:
        return match.group(1)
    match = re.search(r'channel/(UC[\w-]{22})', result.html)
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify YouTube channel IDs.")
    parser.add_argument("--resolve", metavar="@handle",
                        help="Resolve a channel handle to its UC... id.")
    args = parser.parse_args()

    cfg = load_config()
    fetcher = PoliteFetcher(delay_seconds=1.0)

    if args.resolve:
        print(f"Resolving {args.resolve} …")
        channel_id = resolve(args.resolve, fetcher)
        if channel_id:
            ok, note = check(channel_id, cfg.crawl.user_agent)
            print(f"  channel_id: {channel_id}")
            print(f"  feed check: {'OK' if ok else 'FAIL'} — {note}")
            print("\nAdd to config/sources.yaml under youtube_channels:")
            print(f'  - name: "{args.resolve.lstrip("@")}"\n    channel_id: "{channel_id}"')
        else:
            print("  could not resolve a channel id from the public page.")
        fetcher.close()
        return 0

    channels = cfg.youtube_channels
    if not channels:
        print("No youtube_channels configured in config/sources.yaml.")
        return 0

    print(f"Checking {len(channels)} channel(s)…\n")
    failures = 0
    for channel in channels:
        channel_id = channel.get("channel_id", "")
        name = channel.get("name", channel_id)
        ok, note = check(channel_id, cfg.crawl.user_agent)
        print(f"[{'OK  ' if ok else 'FAIL'}] {name:<24} {channel_id}  {note}")
        if not ok:
            failures += 1
            print(f"         try: python scripts/verify_youtube.py --resolve @{name.lower()}")

    fetcher.close()
    if failures:
        print(f"\n{failures} channel(s) returned nothing. YouTube discovery will report an "
              "error for those rather than failing silently.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
