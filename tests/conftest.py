from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Isolated SQLite database for a single test."""
    import fcie.db as db_module
    from fcie.config import load_config

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("FCIE_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    load_config.cache_clear()
    db_module.dispose()

    db_module.init_db()
    yield db_module

    db_module.dispose()
    load_config.cache_clear()


@pytest.fixture
def sample_text() -> str:
    return (
        "Local dealerships are losing revenue to a problem they rarely measure. "
        "A recent survey of 240 service departments found that 38% of inbound calls "
        "outside business hours went unanswered. "
        "\"We were missing calls every single evening and had no idea,\" said Dana Whitfield, "
        "who runs a five-rooftop group in Ohio. "
        "The average response time to a web lead was 47 minutes, well past the window in which "
        "most customers have already contacted a competitor. "
        "Speed to lead is not a marketing problem for these businesses; it is a staffing problem. "
        "Front desk turnover ran above 60% annually across the sample. "
        "AI agents that book appointments rather than merely answering questions are being "
        "piloted at 18 of the surveyed locations."
    )
