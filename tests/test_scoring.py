from datetime import datetime, timedelta, timezone

import pytest

from fcie.pipeline.scoring import (
    DEFAULT_WEIGHTS,
    compute_confidence,
    compute_opportunity_score,
    compute_risk_score,
    freshness_score,
    score_band,
)


class TestFreshness:
    def test_brand_new_scores_ten(self):
        score, reason = freshness_score(datetime.now(timezone.utc))
        assert score == 10.0
        assert "day" in reason

    def test_very_old_scores_zero(self):
        score, _ = freshness_score(datetime.now(timezone.utc) - timedelta(days=400))
        assert score == 0.0

    def test_missing_date_uses_default_and_flags_it(self):
        score, reason = freshness_score(None)
        assert score == 4.0
        assert "No publication date" in reason

    def test_decays_monotonically(self):
        now = datetime.now(timezone.utc)
        recent, _ = freshness_score(now - timedelta(days=20))
        older, _ = freshness_score(now - timedelta(days=60))
        assert recent > older

    def test_future_date_is_flagged(self):
        score, reason = freshness_score(datetime.now(timezone.utc) + timedelta(days=5))
        assert score == 10.0
        assert "future" in reason


class TestOpportunityScore:
    def test_all_tens_is_one_hundred(self):
        breakdown = compute_opportunity_score(
            {k: 10 for k in DEFAULT_WEIGHTS}, weights=DEFAULT_WEIGHTS
        )
        assert breakdown.total == pytest.approx(100.0, abs=0.2)

    def test_all_zeros_is_zero(self):
        breakdown = compute_opportunity_score(
            {k: 0 for k in DEFAULT_WEIGHTS}, weights=DEFAULT_WEIGHTS
        )
        assert breakdown.total == 0.0

    def test_weights_are_applied(self):
        podium_only = compute_opportunity_score(
            {"podium_relevance": 10}, weights=DEFAULT_WEIGHTS
        )
        novelty_only = compute_opportunity_score(
            {"novelty": 10}, weights=DEFAULT_WEIGHTS
        )
        # Podium relevance is weighted 25% vs novelty 10%.
        assert podium_only.total > novelty_only.total
        assert podium_only.total == pytest.approx(25.0, abs=0.3)

    def test_breakdown_has_every_component(self):
        breakdown = compute_opportunity_score({k: 5 for k in DEFAULT_WEIGHTS})
        assert len(breakdown.components) == 6
        for row in breakdown.components:
            assert {"component", "label", "raw_0_10", "weight", "points", "max_points"} <= set(row)

    def test_weights_are_normalised(self):
        doubled = {k: v * 2 for k, v in DEFAULT_WEIGHTS.items()}
        a = compute_opportunity_score({k: 7 for k in DEFAULT_WEIGHTS}, weights=DEFAULT_WEIGHTS)
        b = compute_opportunity_score({k: 7 for k in DEFAULT_WEIGHTS}, weights=doubled)
        assert a.total == pytest.approx(b.total, abs=0.1)

    def test_out_of_range_inputs_are_clamped(self):
        breakdown = compute_opportunity_score({k: 99 for k in DEFAULT_WEIGHTS})
        assert breakdown.total <= 100.0

    def test_non_numeric_inputs_do_not_crash(self):
        breakdown = compute_opportunity_score({"podium_relevance": "not a number"})
        assert breakdown.total >= 0.0

    def test_missing_components_default_to_zero(self):
        breakdown = compute_opportunity_score({})
        assert breakdown.total == 0.0

    def test_serialises_to_dict(self):
        payload = compute_opportunity_score({k: 6 for k in DEFAULT_WEIGHTS}).to_dict()
        assert "total" in payload and "components" in payload and "formula" in payload


class TestRiskScore:
    def test_no_factors_is_zero_and_low(self):
        risk = compute_risk_score({})
        assert risk.total == 0.0
        assert risk.band == "Low"

    def test_factors_accumulate(self):
        risk = compute_risk_score({
            "weak_sourcing": "only one domain",
            "unverified_numbers": "3 figures",
            "competitor_claims": "names a competitor",
        })
        assert risk.total > 40
        assert len(risk.factors) == 3

    def test_falsey_reasons_are_ignored(self):
        risk = compute_risk_score({"weak_sourcing": "", "unverified_numbers": None})
        assert risk.total == 0.0

    def test_caps_at_one_hundred(self):
        risk = compute_risk_score({k: "detected" for k in [
            "weak_sourcing", "unverified_numbers", "sensitive_claims", "competitor_claims",
            "overused_narrative", "no_original_insight", "generic_tone",
            "promotional_source", "missing_publication_date",
        ]})
        assert risk.total <= 100.0
        assert risk.band == "High"

    def test_factors_carry_their_reason(self):
        risk = compute_risk_score({"weak_sourcing": "single domain only"})
        assert risk.factors[0]["reason"] == "single domain only"


class TestConfidence:
    def test_strong_evidence_scores_high(self):
        score, reasons = compute_confidence(
            distinct_domains=5, evidence_passage_count=10,
            avg_evidence_strength=8.5, source_count=8,
        )
        assert score > 80
        assert reasons

    def test_single_domain_is_penalised(self):
        multi, _ = compute_confidence(distinct_domains=3, evidence_passage_count=6,
                                      avg_evidence_strength=7, source_count=5)
        single, reasons = compute_confidence(distinct_domains=1, evidence_passage_count=6,
                                             avg_evidence_strength=7, source_count=5)
        assert single < multi
        assert any("Single-domain" in r for r in reasons)

    def test_no_evidence_scores_zero(self):
        score, _ = compute_confidence(distinct_domains=0, evidence_passage_count=0,
                                      avg_evidence_strength=0, source_count=0)
        assert score == 0.0

    def test_undated_sources_penalised(self):
        dated, _ = compute_confidence(distinct_domains=3, evidence_passage_count=5,
                                      avg_evidence_strength=7, source_count=5,
                                      has_dated_sources=True)
        undated, _ = compute_confidence(distinct_domains=3, evidence_passage_count=5,
                                        avg_evidence_strength=7, source_count=5,
                                        has_dated_sources=False)
        assert undated < dated


def test_score_bands():
    assert score_band(90) == "Strong"
    assert score_band(70) == "Promising"
    assert score_band(55) == "Moderate"
    assert score_band(20) == "Weak"
