"""Shared CLI bootstrap: import path + console encoding.

Windows consoles default to cp1252, which cannot encode the box-drawing and
symbol characters the pipeline logs. Without this, a run dies with
``UnicodeEncodeError`` on a *log line* — the work succeeded but the process
crashed printing about it. Force UTF-8 where possible and degrade to a
replacement character rather than failing.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def configure_console() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Older/redirected streams: at least stop encoding errors being fatal.
            try:
                reconfigure(errors="replace")
            except Exception:  # noqa: BLE001
                pass


configure_console()
