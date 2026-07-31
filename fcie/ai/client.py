"""OpenAI client wrapper with structured JSON output.

Never raises on a missing key: callers ask ``client.available`` and fall back to
the heuristic backend, surfacing ``client.setup_message`` in the UI.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import load_config

log = logging.getLogger(__name__)

SETUP_MESSAGE = (
    "OPENAI_API_KEY is not set. LLM extraction, brief writing and draft "
    "generation are running on the deterministic heuristic analyser instead. "
    "Quotes and evidence passages are still sliced verbatim from the source "
    "text, but the interpretation layer is rule-based rather than model-based. "
    "Add OPENAI_API_KEY to your .env to enable the LLM path."
)


class LLMUnavailable(RuntimeError):
    """Raised only when an LLM call is explicitly required and cannot be made."""


# Failures that will not resolve by trying again: a bad key stays bad, and an
# account with no credit stays empty. Retrying these wastes the caller's time
# (~4.5s of backoff per call) for a guaranteed second failure.
PERMANENT_ERROR_MARKERS = (
    "api key", "authentication", "invalid_api_key", "incorrect api key",
    "insufficient_quota", "exceeded your current quota", "billing",
    "account is not active", "permission",
)

# Exhausted *allowance* — distinct from a bad key or an empty account. A daily
# request cap resets on its own, so calling this "rejected the key" would send
# the operator to fix something that is not broken. Retrying inside one run is
# still pointless (the window is minutes to hours away), so it stops the run —
# but the message has to say what actually happened.
RATE_LIMIT_MARKERS = (
    "requests per day", "rpd", "requests per min", "rpm",
    "tokens per min", "tpm", "rate limit reached", "rate_limit_exceeded",
)

# After this many consecutive permanent failures the client disables itself for
# the rest of the process. Without it, a 70-source run makes 70 doomed API calls
# before finishing on the heuristic backend anyway.
PERMANENT_FAILURE_LIMIT = 3


@dataclass
class LLMResponse:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    error: str | None = None
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class AIClient:
    """Thin, dependency-light wrapper around OpenAI chat completions."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        cfg = load_config()
        self.cfg = cfg
        self.api_key = api_key if api_key is not None else cfg.credentials.openai_api_key
        self.model = model or cfg.ai.model
        self.temperature = cfg.ai.temperature
        self.enabled_in_config = cfg.ai.enable_llm
        self._client = None
        self._import_error: str | None = None
        self.call_count = 0
        self.total_tokens = 0
        self._permanent_failures = 0
        self._disabled_reason: str | None = None

        if self.api_key and self.enabled_in_config:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.api_key)
            except ImportError as exc:
                self._import_error = f"openai package not installed: {exc}"
            except Exception as exc:  # noqa: BLE001
                self._import_error = f"OpenAI client init failed: {exc}"

    # ── availability ────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._client is not None and self._disabled_reason is None

    @property
    def setup_message(self) -> str:
        if self._disabled_reason:
            return self._disabled_reason
        if self._import_error:
            return self._import_error
        if not self.enabled_in_config:
            return "LLM disabled in config/settings.yaml (ai.enable_llm: false). Using the heuristic analyser."
        if not self.api_key:
            return SETUP_MESSAGE
        return "OpenAI configured."

    def _note_failure(self, error: str) -> None:
        """Track unrecoverable failures and trip the breaker once they repeat."""
        if not _is_unrecoverable(error):
            self._permanent_failures = 0
            return
        self._permanent_failures += 1
        if self._permanent_failures >= PERMANENT_FAILURE_LIMIT:
            self._disabled_reason = (
                f"{_diagnose(error)} The LLM backend was disabled after "
                f"{self._permanent_failures} consecutive failures and the run continued on "
                f"the deterministic heuristic analyser — rows already extracted keep their "
                f"LLM output. Original error: {error[:200]}"
            )
            log.warning(self._disabled_reason)

    @property
    def backend_label(self) -> str:
        return self.model if self.available else "heuristic-v1"

    # ── main call ───────────────────────────────────────────────────────

    def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 3000,
        retries: int = 2,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Ask for a JSON object. Returns ``ok=False`` rather than raising."""
        if not self.available:
            return LLMResponse(ok=False, error=self.setup_message)

        system = system or (
            "You are a rigorous research analyst. You return only valid JSON. "
            "You never invent quotations, statistics, customers, or attributions. "
            "You would rather return an empty field than an unsupported one."
        )
        last_error = "unknown error"

        for attempt in range(retries + 1):
            started = time.perf_counter()
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=self.temperature if temperature is None else temperature,
                    max_tokens=max_tokens,
                )
                latency = int((time.perf_counter() - started) * 1000)
                text = (response.choices[0].message.content or "").strip()
                usage = getattr(response, "usage", None)

                self.call_count += 1
                if usage:
                    self.total_tokens += getattr(usage, "total_tokens", 0) or 0

                data = _parse_json(text)
                if data is None:
                    last_error = "model returned non-JSON output"
                    continue

                return LLMResponse(
                    ok=True,
                    data=data,
                    raw_text=text,
                    model=self.model,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
                    latency_ms=latency,
                )

            except Exception as exc:  # noqa: BLE001
                last_error = f"{exc.__class__.__name__}: {exc}"
                if _is_unrecoverable(last_error):
                    # A bad key, an empty account, or an exhausted daily
                    # allowance: none of these resolve inside a retry window.
                    break
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))

        self._note_failure(last_error)
        return LLMResponse(ok=False, error=last_error, model=self.model)

    def usage_summary(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "model": self.model if self.available else "heuristic-v1",
            "calls": self.call_count,
            "tokens": self.total_tokens,
        }


def _is_permanent(error: str | None) -> bool:
    """True for failures that repeating the call cannot resolve at all."""
    if not error:
        return False
    low = error.lower()
    return any(marker in low for marker in PERMANENT_ERROR_MARKERS)


def _is_rate_limited(error: str | None) -> bool:
    """True when the account's request allowance is exhausted (self-resolving)."""
    if not error:
        return False
    low = error.lower()
    return any(marker in low for marker in RATE_LIMIT_MARKERS)


def _is_unrecoverable(error: str | None) -> bool:
    """True when retrying *within this run* cannot succeed."""
    return _is_permanent(error) or _is_rate_limited(error)


def _diagnose(error: str) -> str:
    """A first line that names what actually happened, and the real remedy.

    Getting this wrong is worse than saying nothing: telling someone their key
    was rejected when they have simply used today's allowance sends them to
    regenerate a key that works fine.
    """
    low = error.lower()
    if _is_rate_limited(low) and not _is_permanent(low):
        window = "per-day" if ("requests per day" in low or "rpd" in low) else "per-minute"
        # Quote the account's real limit rather than guessing at a tier. Telling
        # someone on tier 1 to "add credit" when they already have it is the same
        # class of unhelpful as blaming their key for a rate limit.
        limit = re.search(r"limit\s+(\d[\d,]*)", low)
        ceiling = f" The account's current {window} ceiling is {limit.group(1)}." if limit else ""
        return (
            f"OpenAI {window} rate limit reached — an allowance cap, not a problem with "
            f"the key.{ceiling} It resets on its own; raise the ceiling by moving up a "
            f"usage tier at platform.openai.com/settings/organization/limits."
        )
    if "insufficient_quota" in low or "exceeded your current quota" in low:
        return (
            "OpenAI quota exhausted — the key is valid but the account has no credit. "
            "Add credit at platform.openai.com/settings/organization/billing."
        )
    return (
        "OpenAI rejected the credentials — check OPENAI_API_KEY is current and has "
        "access to the configured model."
    )


def _parse_json(text: str) -> dict | None:
    """Tolerant JSON parse — strips fences and trailing prose."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1] if "```" in cleaned[3:] else cleaned[3:]
        cleaned = cleaned.removeprefix("json").strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            return parsed if isinstance(parsed, dict) else {"result": parsed}
        except json.JSONDecodeError:
            return None
    return None
