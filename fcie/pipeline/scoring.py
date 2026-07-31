"""Transparent scoring.

Two independent numbers:

* **opportunity_score** (0-100) — weighted sum of six 0-10 components, weights
  from ``config/scoring.yaml``. Every breakdown is stored so the dashboard can
  show exactly how the number was produced.
* **risk_score** (0-100) — additive penalties for detected publication risks.
  Deliberately *not* subtracted from the opportunity score: a high-value, high-
  risk item should surface loudly, with its risk visible, not be hidden by
  arithmetic.

Nothing here calls an LLM. The scores are reproducible from the stored inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from ..config import load_config
from ..utils.text import naive_utc

DEFAULT_WEIGHTS = {
    "podium_relevance": 0.25,
    "founder_relevance": 0.20,
    "evidence_strength": 0.20,
    "freshness": 0.15,
    "novelty": 0.10,
    "business_impact": 0.10,
}

COMPONENT_LABELS = {
    "podium_relevance": "Podium relevance",
    "founder_relevance": "Founder (Eric) relevance",
    "evidence_strength": "Customer / market evidence",
    "freshness": "Freshness",
    "novelty": "Novelty",
    "business_impact": "Business impact",
}


@dataclass
class ScoreBreakdown:
    total: float
    components: list[dict[str, Any]] = field(default_factory=list)
    weights_used: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 1),
            "components": self.components,
            "weights_used": self.weights_used,
            "notes": self.notes,
            "formula": "score = Σ(component_0_to_10 × weight) × 10",
        }


@dataclass
class RiskBreakdown:
    total: float
    band: str
    factors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 1),
            "band": self.band,
            "factors": self.factors,
            "note": "Risk is scored independently of opportunity so high-value, "
                    "high-risk items stay visible rather than being averaged away.",
        }


# ── freshness ───────────────────────────────────────────────────────────────

def freshness_score(published_at: datetime | None, *, now: datetime | None = None,
                    config: dict | None = None) -> tuple[float, str]:
    """0-10 recency score, with the reason it was assigned."""
    cfg = config or load_config().scoring.get("freshness", {})
    full_days = cfg.get("full_score_days", 7)
    zero_days = cfg.get("zero_score_days", 120)
    unknown = float(cfg.get("unknown_date_score", 4))

    if published_at is None:
        return unknown, "No publication date in the source — default score applied and flagged."

    now = now or datetime.now(timezone.utc)
    published = naive_utc(published_at)
    reference = naive_utc(now)
    age_days = (reference - published).total_seconds() / 86400.0

    if age_days < 0:
        return 10.0, "Publication date is in the future — treated as brand new and flagged."
    if age_days <= full_days:
        return 10.0, f"Published {age_days:.0f} day(s) ago."
    if age_days >= zero_days:
        return 0.0, f"Published {age_days:.0f} days ago — outside the {zero_days}-day freshness window."

    span = max(zero_days - full_days, 1)
    score = 10.0 * (1.0 - (age_days - full_days) / span)
    return round(max(score, 0.0), 2), f"Published {age_days:.0f} days ago — linear decay."


# ── opportunity score ───────────────────────────────────────────────────────

def _clamp10(value: Any) -> float:
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def compute_opportunity_score(
    components: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
    notes: Iterable[str] = (),
) -> ScoreBreakdown:
    """Weighted 0-100 score from six 0-10 components.

    Weights are normalised so a partially-configured weight map still produces a
    score on the same 0-100 scale.
    """
    cfg_weights = weights if weights is not None else (
        load_config().scoring_weights or DEFAULT_WEIGHTS
    )
    used = {k: float(v) for k, v in cfg_weights.items() if k in DEFAULT_WEIGHTS}
    if not used:
        used = dict(DEFAULT_WEIGHTS)
    weight_sum = sum(used.values()) or 1.0

    rows: list[dict[str, Any]] = []
    total = 0.0
    for key in DEFAULT_WEIGHTS:
        weight = used.get(key, 0.0)
        raw = _clamp10(components.get(key, 0))
        contribution = raw * (weight / weight_sum) * 10.0
        total += contribution
        rows.append({
            "component": key,
            "label": COMPONENT_LABELS[key],
            "raw_0_10": round(raw, 2),
            "weight": round(weight / weight_sum, 4),
            "weight_pct": f"{weight / weight_sum:.0%}",
            "points": round(contribution, 2),
            "max_points": round((weight / weight_sum) * 100, 2),
        })

    return ScoreBreakdown(
        total=round(min(total, 100.0), 1),
        components=rows,
        weights_used={k: round(v / weight_sum, 4) for k, v in used.items()},
        notes=list(notes),
    )


# ── risk score ──────────────────────────────────────────────────────────────

RISK_LABELS = {
    "weak_sourcing": "Weak sourcing (few distinct domains, or vendor-only)",
    "unverified_numbers": "Unverified numbers",
    "sensitive_claims": "Sensitive claims (employment, legal, health, financial)",
    "competitor_claims": "Claims about named competitors",
    "overused_narrative": "Overused / saturated narrative",
    "no_original_insight": "No original insight beyond the source",
    "generic_tone": "Generic or hype-toned",
    "promotional_source": "Source is vendor marketing",
    "missing_publication_date": "Source has no publication date",
}


def compute_risk_score(detected: dict[str, str | bool],
                       *, config: dict | None = None) -> RiskBreakdown:
    """Additive risk model. ``detected`` maps factor → reason (or a truthy flag)."""
    scoring = config or load_config().scoring
    points = scoring.get("risk_factors", {})
    bands = scoring.get("risk_bands", {"low": 24, "moderate": 49, "elevated": 74})

    rows: list[dict[str, Any]] = []
    total = 0.0
    for factor, reason in detected.items():
        if not reason:
            continue
        value = float(points.get(factor, 8))
        total += value
        rows.append({
            "factor": factor,
            "label": RISK_LABELS.get(factor, factor.replace("_", " ").title()),
            "points": value,
            "reason": reason if isinstance(reason, str) else "detected",
        })

    total = min(total, 100.0)
    if total <= bands.get("low", 24):
        band = "Low"
    elif total <= bands.get("moderate", 49):
        band = "Moderate"
    elif total <= bands.get("elevated", 74):
        band = "Elevated"
    else:
        band = "High"

    rows.sort(key=lambda r: r["points"], reverse=True)
    return RiskBreakdown(total=round(total, 1), band=band, factors=rows)


# ── confidence ──────────────────────────────────────────────────────────────

def compute_confidence(
    *,
    distinct_domains: int,
    evidence_passage_count: int,
    avg_evidence_strength: float,
    source_count: int,
    has_dated_sources: bool = True,
    config: dict | None = None,
) -> tuple[float, list[str]]:
    """0-100 confidence in a brief, with the reasons behind it.

    Confidence is about *how well-supported* the brief is, deliberately separate
    from how attractive the opportunity is.
    """
    cfg = (config or load_config().scoring).get("confidence", {})
    domain_target = cfg.get("min_distinct_domains_for_high", 3)
    passage_target = cfg.get("min_evidence_passages_for_high", 4)

    reasons: list[str] = []

    domain_part = min(distinct_domains / max(domain_target, 1), 1.0) * 30
    reasons.append(f"{distinct_domains} distinct domain(s) → {domain_part:.0f}/30")

    passage_part = min(evidence_passage_count / max(passage_target, 1), 1.0) * 25
    reasons.append(f"{evidence_passage_count} verbatim evidence passage(s) → {passage_part:.0f}/25")

    strength_part = (_clamp10(avg_evidence_strength) / 10.0) * 30
    reasons.append(f"avg evidence strength {avg_evidence_strength:.1f}/10 → {strength_part:.0f}/30")

    volume_part = min(source_count / 5.0, 1.0) * 15
    reasons.append(f"{source_count} supporting source(s) → {volume_part:.0f}/15")

    total = domain_part + passage_part + strength_part + volume_part

    if distinct_domains <= 1:
        total *= 0.65
        reasons.append("Single-domain evidence base → 35% penalty applied.")
    if not has_dated_sources:
        total *= 0.9
        reasons.append("No dated sources → 10% penalty applied.")

    return round(min(total, 100.0), 1), reasons


def score_band(score: float) -> str:
    if score >= 80:
        return "Strong"
    if score >= 65:
        return "Promising"
    if score >= 50:
        return "Moderate"
    return "Weak"
