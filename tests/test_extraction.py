"""Extraction correctness — especially the anti-hallucination guarantees."""

from datetime import datetime, timezone

from fcie.ai.extraction import (
    ExtractionResult,
    Extractor,
    HeuristicExtractor,
    LLMExtractor,
    enforce_verbatim,
)
from fcie.ai.taxonomy import match_entities, match_industries, match_themes
from fcie.utils.text import extract_numerical_claims, extract_quotes, is_verbatim


class TestVerbatimGate:
    """The backstop that a hallucinating model cannot get past."""

    def test_drops_fabricated_quote(self, sample_text):
        result = ExtractionResult(notable_quotes=[
            {"quote": "We were missing calls every single evening and had no idea", "speaker": "Dana Whitfield"},
            {"quote": "This quotation was never in the source document at all", "speaker": "Nobody"},
        ])
        cleaned = enforce_verbatim(result, sample_text)
        assert len(cleaned.notable_quotes) == 1
        assert cleaned.notable_quotes[0]["verified_verbatim"] is True
        assert any("discarded" in note for note in cleaned.verification_notes)

    def test_drops_fabricated_evidence_passage(self, sample_text):
        result = ExtractionResult(supporting_evidence=[
            {"passage": "The average response time to a web lead was 47 minutes"},
            {"passage": "Ninety percent of businesses solved this problem last year."},
        ])
        cleaned = enforce_verbatim(result, sample_text)
        assert len(cleaned.supporting_evidence) == 1

    def test_drops_number_with_invented_context(self, sample_text):
        result = ExtractionResult(numerical_claims=[
            {"value": "38%", "context": "A recent survey of 240 service departments found that 38% "
                                        "of inbound calls outside business hours went unanswered."},
            {"value": "500%", "context": "Revenue increased 500% after deployment."},
        ])
        cleaned = enforce_verbatim(result, sample_text)
        assert len(cleaned.numerical_claims) == 1
        assert cleaned.numerical_claims[0]["needs_verification"] is True

    def test_keeps_everything_when_all_verbatim(self, sample_text):
        result = ExtractionResult(
            supporting_evidence=[{"passage": "Front desk turnover ran above 60% annually across the sample."}],
        )
        cleaned = enforce_verbatim(result, sample_text)
        assert len(cleaned.supporting_evidence) == 1
        assert not any("discarded" in n for n in cleaned.verification_notes)

    def test_empty_source_text_drops_everything(self):
        result = ExtractionResult(notable_quotes=[{"quote": "anything at all here"}])
        cleaned = enforce_verbatim(result, "")
        assert cleaned.notable_quotes == []


class TestIsVerbatim:
    def test_whitespace_insensitive(self):
        assert is_verbatim("hello   world friend", "Hello world friend, and more text.")

    def test_curly_quote_insensitive(self):
        assert is_verbatim("it's a test of quoting", "It’s a test of quoting here.")

    def test_rejects_absent_text(self):
        assert not is_verbatim("never appeared anywhere", "Some other content entirely.")

    def test_rejects_too_short(self):
        assert not is_verbatim("ai", "ai is everywhere")


class TestHeuristicExtractor:
    def _run(self, text, **kwargs):
        return HeuristicExtractor().extract(
            text=text, title=kwargs.get("title", "Dealerships are losing after-hours leads"),
            url=kwargs.get("url", "https://cbtnews.com/story"),
            published_at=kwargs.get("published_at", datetime.now(timezone.utc)),
            source_type=kwargs.get("source_type", "rss"),
            domain=kwargs.get("domain", "cbtnews.com"),
            metadata=kwargs.get("metadata", {}),
        )

    def test_produces_all_required_fields(self, sample_text):
        result = self._run(sample_text)
        for field in ("primary_entity", "industries", "primary_theme", "customer_problem",
                      "primary_claim", "supporting_evidence", "notable_quotes",
                      "numerical_claims", "podium_relevance", "founder_relevance",
                      "novelty_score", "freshness_score", "evidence_strength",
                      "business_impact", "risk_score", "opportunity_score",
                      "score_breakdown", "risk_breakdown", "content_opportunity",
                      "potential_angle", "recommended_format", "verification_notes",
                      "extraction_model", "extraction_method"):
            assert hasattr(result, field), field

    def test_all_evidence_is_verbatim(self, sample_text):
        result = self._run(sample_text)
        for passage in result.supporting_evidence:
            assert is_verbatim(passage["passage"], sample_text)
            assert passage["verified_verbatim"] is True

    def test_all_quotes_are_verbatim(self, sample_text):
        result = self._run(sample_text)
        assert result.notable_quotes, "the sample text contains a quotation"
        for quote in result.notable_quotes:
            assert is_verbatim(quote["quote"], sample_text)

    def test_scores_are_in_range(self, sample_text):
        result = self._run(sample_text)
        for value in (result.podium_relevance, result.founder_relevance, result.novelty_score,
                      result.freshness_score, result.evidence_strength, result.business_impact):
            assert 0.0 <= value <= 10.0
        assert 0.0 <= result.opportunity_score <= 100.0
        assert 0.0 <= result.risk_score <= 100.0

    def test_detects_automotive_industry(self, sample_text):
        assert "Automotive" in self._run(sample_text).industries

    def test_assigns_a_relevant_theme(self, sample_text):
        theme = self._run(sample_text).primary_theme
        assert theme in ("Missed after-hours leads", "Speed to lead",
                         "Local-business staffing limits", "Revenue ownership by AI")

    def test_flags_missing_publication_date(self, sample_text):
        result = self._run(sample_text, published_at=None)
        assert any("publication date" in note.lower() for note in result.verification_notes)
        assert "missing_publication_date" in {
            f["factor"] for f in result.risk_breakdown["factors"]
        }

    def test_marks_promotional_source(self, sample_text):
        result = self._run(
            sample_text + " Request a demo today. Book a demo with our team.",
            domain="podium.com", url="https://podium.com/ai-employee",
            metadata={"is_promotional": True},
        )
        assert result.is_promotional_source
        assert "promotional_source" in {f["factor"] for f in result.risk_breakdown["factors"]}

    def test_summary_only_is_flagged_and_discounted(self, sample_text):
        full = self._run(sample_text)
        summary = self._run(sample_text, metadata={"summary_only": True})
        assert summary.is_summary_only
        assert not full.is_summary_only
        assert summary.evidence_strength < full.evidence_strength
        assert any("not accessible" in n for n in summary.verification_notes)
        assert any("not bypassed" in n.lower() for n in summary.verification_notes)

    def test_empty_text_does_not_crash(self):
        result = self._run("")
        assert result.supporting_evidence == []
        assert result.opportunity_score >= 0

    def test_deterministic(self, sample_text):
        a, b = self._run(sample_text), self._run(sample_text)
        assert a.opportunity_score == b.opportunity_score
        assert a.primary_theme == b.primary_theme

    def test_extraction_method_is_labelled(self, sample_text):
        result = self._run(sample_text)
        assert result.extraction_method == "heuristic"
        assert result.extraction_model == "heuristic-v1"

    def test_inference_fields_are_labelled_as_inference(self, sample_text):
        result = self._run(sample_text)
        assert result.content_opportunity.startswith("[Inference]")
        assert result.potential_angle.startswith("[Inference]")


class TestNoApiKeyBehaviour:
    def test_extractor_falls_back_without_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from fcie.config import load_config

        load_config.cache_clear()
        extractor = Extractor()
        assert extractor.backend == "heuristic"
        assert "OPENAI_API_KEY" in extractor.backend_note or "heuristic" in extractor.backend_note.lower()
        load_config.cache_clear()

    def test_llm_extractor_reports_unavailable(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from fcie.config import load_config

        load_config.cache_clear()
        assert LLMExtractor().available is False
        load_config.cache_clear()

    def test_llm_extractor_falls_back_and_records_the_error(self, monkeypatch, sample_text):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from fcie.config import load_config

        load_config.cache_clear()
        result = LLMExtractor().extract(
            text=sample_text, title="T", url="https://e.com/a",
            published_at=datetime.now(timezone.utc), source_type="rss", domain="e.com",
        )
        assert result.extraction_method == "heuristic"
        assert result.extraction_error
        load_config.cache_clear()

    def test_ai_client_setup_message_is_actionable(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from fcie.ai.client import AIClient
        from fcie.config import load_config

        load_config.cache_clear()
        client = AIClient()
        assert not client.available
        assert "OPENAI_API_KEY" in client.setup_message
        response = client.complete_json("anything")
        assert response.ok is False and response.error
        load_config.cache_clear()


class TestLLMCoercion:
    def test_rejects_theme_outside_the_taxonomy(self):
        result = LLMExtractor._coerce(
            {"primary_theme": "A Theme That Does Not Exist", "podium_relevance": 8},
            None, "e.com",
        )
        assert result.primary_theme is None

    def test_clamps_out_of_range_scores(self):
        result = LLMExtractor._coerce({"podium_relevance": 99, "novelty_score": -5}, None, "e.com")
        assert result.podium_relevance == 10.0
        assert result.novelty_score == 0.0

    def test_placeholder_strings_become_none(self):
        result = LLMExtractor._coerce({"customer_problem": "N/A", "primary_claim": "TBD"},
                                      None, "e.com")
        assert result.customer_problem is None
        assert result.primary_claim is None

    def test_rejects_invalid_format(self):
        result = LLMExtractor._coerce({"recommended_format": "tiktok_dance"}, None, "e.com")
        assert result.recommended_format == "executive_talking_point"

    def test_quotes_start_unverified(self):
        result = LLMExtractor._coerce(
            {"notable_quotes": [{"quote": "something", "speaker": "X"}]}, None, "e.com"
        )
        assert result.notable_quotes[0]["verified_verbatim"] is False

    def test_missing_date_adds_verification_note(self):
        result = LLMExtractor._coerce({}, None, "e.com")
        assert any("publication date" in n.lower() for n in result.verification_notes)


class TestWordBoundaryMatching:
    """Substring matching mis-attributes whole industries. Guard against it."""

    def test_spa_does_not_match_space_or_spark(self):
        from fcie.ai.taxonomy import count_phrase

        text = "The company is exploring space exploration and spark plugs, disparate topics."
        assert count_phrase(text, "spa") == 0

    def test_lead_does_not_match_leader_or_misleading(self):
        from fcie.ai.taxonomy import count_phrase

        text = "The industry leader gave a misleading and leading statement while leadership watched."
        assert count_phrase(text, "lead") == 0

    def test_matches_the_real_word_and_its_plural(self):
        from fcie.ai.taxonomy import count_phrase

        assert count_phrase("We lost a lead today.", "lead") == 1
        assert count_phrase("We lost three leads today.", "lead") == 1
        assert count_phrase("A medspa and two medspas opened.", "medspa") == 2

    def test_multiword_phrases_tolerate_extra_whitespace(self):
        from fcie.ai.taxonomy import count_phrase

        assert count_phrase("a missed  call problem", "missed call") == 1

    def test_aesthetics_not_attributed_from_incidental_words(self):
        from fcie.ai.taxonomy import match_industries

        text = (
            "The startup raised funding to build space infrastructure. Sparks flew at the "
            "conference as disparate teams debated the design and its visual polish."
        )
        assert "Aesthetics & medspa" not in match_industries(text)

    def test_industry_needs_more_than_one_passing_mention(self):
        from fcie.ai.taxonomy import match_industries

        single = "The article briefly mentions one dealership in passing."
        assert "Automotive" not in match_industries(single)

        real = ("The dealership group said its service department and used car sales both "
                "improved after the dealer changed how it handled vehicle enquiries.")
        assert "Automotive" in match_industries(real)

    def test_entity_matching_respects_boundaries(self):
        from fcie.ai.taxonomy import match_entities

        assert "Podium" not in match_entities("They stood on a podiums platform")["podium"]
        assert "Podium" in match_entities("Podium announced a product.")["podium"]


class TestTaxonomy:
    def test_matches_podium_entity(self):
        found = match_entities("Podium announced a new AI Employee for dealerships.")
        assert "Podium" in found["podium"]

    def test_matches_competitors(self):
        found = match_entities("Birdeye and Weave both compete in this space.")
        assert "Birdeye" in found["competitors"]
        assert "Weave" in found["competitors"]

    def test_industries_default_to_cross_industry(self):
        assert match_industries("A general note about software.") == ["Cross-industry"]

    def test_theme_matching_returns_evidence_keywords(self):
        matches = match_themes("Missed calls after hours are killing lead response times.")
        assert matches
        theme, score, keywords = matches[0]
        assert score > 0
        assert keywords


class TestEvidenceQuality:
    """Page chrome is not evidence. Quoting a CTA button is worse than nothing."""

    def test_rejects_call_to_action_chrome(self):
        from fcie.utils.text import looks_like_prose

        assert not looks_like_prose("Watch a demo Turn missed calls into revenue today.")
        assert not looks_like_prose(
            "Works with your systems Podium integrates with the tools your office uses."
        )

    def test_rejects_shouty_banners(self):
        from fcie.utils.text import looks_like_prose

        assert not looks_like_prose("#1 AI OPERATING SYSTEM FOR HOME SERVICES BUSINESSES.")

    def test_rejects_title_case_navigation(self):
        from fcie.utils.text import looks_like_prose

        assert not looks_like_prose("Reviews Payments Phones Marketing Contacts Inbox Reporting.")

    def test_rejects_fragments_without_terminal_punctuation(self):
        from fcie.utils.text import looks_like_prose

        assert not looks_like_prose("Turn missed calls into booked revenue")

    def test_accepts_a_real_claim(self):
        from fcie.utils.text import looks_like_prose

        assert looks_like_prose(
            "A recent survey found that 38% of inbound calls outside business hours "
            "went unanswered."
        )

    def test_theme_keywords_outrank_generic_ones(self):
        from fcie.utils.text import select_evidence_passages

        text = (
            "Amazon said the revenue outlook for its cloud hosting unit remains uncertain "
            "this year. "
            "Shops report that a missed call after hours is the most common way a job is "
            "lost to a competitor."
        )
        passages = select_evidence_passages(
            text, ["revenue", "business"], limit=1,
            priority_keywords=["missed call", "after hours"],
        )
        assert passages
        assert "missed call" in passages[0]["passage"].lower()

    def test_rejects_obfuscated_paywall_text(self):
        from fcie.utils.text import looks_like_gibberish, looks_like_prose

        scrambled = ("Gfh ifkgzgg hcfapv rmr rukbtc ahb phehadg vioi tatz 16% om hkp "
                     "xlwcv b ackpip wlac s qjrwalpr dm 94er.")
        assert looks_like_gibberish(scrambled)
        assert not looks_like_prose(scrambled)

    def test_real_prose_is_not_flagged_as_gibberish(self):
        from fcie.utils.text import looks_like_gibberish

        assert not looks_like_gibberish(
            "Contractors reported that 38% of after-hours calls went unanswered last year."
        )
        assert not looks_like_gibberish(
            "The average response time to a web lead was 47 minutes across the sample."
        )

    def test_chrome_never_becomes_evidence(self):
        from fcie.utils.text import select_evidence_passages

        text = (
            "Watch a demo Turn missed calls into revenue and let our AI Employee follow up. "
            "Get started free today with our missed call platform."
        )
        assert select_evidence_passages(
            text, ["revenue"], priority_keywords=["missed call"]
        ) == []


class TestTextUtilities:
    def test_quotes_are_extracted_verbatim(self, sample_text):
        quotes = extract_quotes(sample_text)
        assert quotes
        for quote in quotes:
            assert quote["verified_verbatim"]
            assert is_verbatim(quote["quote"], sample_text)

    def test_numbers_keep_their_original_sentence(self, sample_text):
        numbers = extract_numerical_claims(sample_text)
        assert numbers
        for number in numbers:
            assert number["context"]
            assert is_verbatim(number["context"], sample_text)
            assert number["needs_verification"] is True

    def test_list_punctuation_is_not_a_statistic(self):
        """"Reviews 22, Payments 30," is a nav row, not three figures."""
        claims = extract_numerical_claims(
            "Reviews 22, Payments 30, Phones 21, Marketing 14, Contacts 9."
        )
        assert claims == []

    def test_properly_grouped_thousands_survive(self):
        claims = extract_numerical_claims(
            "The shop lost an estimated $24,000 of revenue every week to unanswered calls."
        )
        assert any("24,000" in c["value"] for c in claims)

    def test_trailing_punctuation_is_trimmed(self):
        claims = extract_numerical_claims(
            "Across the surveyed group, 38% of inbound calls went unanswered after hours."
        )
        assert any(c["value"] == "38%" for c in claims)
        assert all(not c["value"].endswith((",", ".")) for c in claims)

    def test_robotics_vocabulary_does_not_match_the_agent_theme(self):
        from fcie.ai.taxonomy import match_themes

        matches = match_themes(
            "Today's robot vacuums are autonomous mobile computers with lidar and cameras."
        )
        names = [t.name for t, _s, _k in matches]
        assert "Agents that act vs chatbots that answer" not in names

    def test_real_agent_language_still_matches(self):
        from fcie.ai.taxonomy import match_themes

        matches = match_themes(
            "An agentic AI agent books the appointment end to end, unlike a chatbot that "
            "only answers questions."
        )
        assert matches[0][0].name == "Agents that act vs chatbots that answer"

    def test_bare_years_are_not_treated_as_statistics(self):
        numbers = extract_numerical_claims(
            "The company was founded in 2014 and moved offices in 2019 to a new site."
        )
        assert all(n["value"] not in ("2014", "2019") for n in numbers)
