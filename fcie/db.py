"""Database abstraction.

Local development uses SQLite at ``data/fcie.db``. Setting ``FCIE_DATABASE_URL``
to a Supabase / Postgres connection string switches the whole application over
with no code changes — the ORM models are dialect-neutral.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import DATA_DIR, load_config
from .models import Base

_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def database_url() -> str:
    cfg = load_config()
    if cfg.credentials.database_url:
        return cfg.credentials.database_url
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(DATA_DIR / 'fcie.db').as_posix()}"


def describe_backend() -> str:
    """ASCII-only so it is safe to print on a cp1252 Windows console."""
    url = database_url()
    if url.startswith("sqlite"):
        return f"SQLite -> {url.replace('sqlite:///', '')}"
    host = url.split("@")[-1].split("/")[0] if "@" in url else "postgres"
    return f"Postgres -> {host}"


def get_engine(url: str | None = None, echo: bool = False) -> Engine:
    global _engine, _SessionFactory
    if url is not None:
        # Explicit URL (tests) — build a throwaway engine, don't cache.
        return _build_engine(url, echo)
    if _engine is None:
        _engine = _build_engine(database_url(), echo)
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _build_engine(url: str, echo: bool) -> Engine:
    kwargs: dict = {"echo": echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs["pool_pre_ping"] = True
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def get_session_factory() -> sessionmaker:
    global _SessionFactory
    if _SessionFactory is None:
        get_engine()
    assert _SessionFactory is not None
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session. Commits on success, rolls back on exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> list[str]:
    """Create all tables if absent. Idempotent. Returns the table names present."""
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    return sorted(inspect(engine).get_table_names())


def reset_db(engine: Engine | None = None) -> None:
    """Drop and recreate every table. Destructive — used by tests and `--reset`."""
    engine = engine or get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def dispose() -> None:
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
