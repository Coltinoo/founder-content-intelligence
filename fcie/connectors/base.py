"""Shared connector contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..utils.urls import domain_of, normalize_url


@dataclass
class DiscoveredItem:
    """One candidate document, before fetching and extraction."""

    source_url: str
    source_type: str
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    search_query: str | None = None
    summary: str = ""
    raw_text: str = ""          # populated when the connector already has the body
    needs_fetch: bool = True    # False when raw_text is already complete
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_url = normalize_url(self.source_url) or self.source_url
        self.metadata.setdefault("source_domain", domain_of(self.source_url))


@dataclass
class ConnectorResult:
    """Outcome of running one connector, including why it did nothing."""

    connector: str
    items: list[DiscoveredItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    configured: bool = True
    setup_message: str = ""
    requests_made: int = 0

    @property
    def count(self) -> int:
        return len(self.items)

    def summary(self) -> str:
        if not self.configured:
            return f"{self.connector}: not configured — {self.setup_message}"
        parts = [f"{self.count} item(s)"]
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        return f"{self.connector}: " + ", ".join(parts)


class BaseConnector:
    name = "base"

    def discover(self) -> ConnectorResult:  # pragma: no cover - interface
        raise NotImplementedError

    def not_configured(self, message: str) -> ConnectorResult:
        return ConnectorResult(
            connector=self.name, configured=False, setup_message=message
        )
