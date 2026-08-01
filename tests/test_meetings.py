"""The meeting agent's evidence contract.

Same guarantee as the web pipeline: a quote that is not in the source does not
get shown. Here the source is the transcript, and nothing is persisted, so the
gate is the only thing standing between a model's paraphrase and the screen.
"""

from unittest.mock import patch

from fcie.pipeline.meetings import (
    MIN_TRANSCRIPT_WORDS,
    analyse_transcript,
    notes_to_markdown,
)

TRANSCRIPT = """
Dana: Volume is flat month over month, but our close rate on inbound dropped.
Marcus: Anything that comes in after four in the afternoon waits until morning.
Priya: We'll pilot evening coverage for two weeks and measure the close rate.
Dana: I'll pull the after-hours cohort separately so we have a clean baseline.
Marcus: We don't know it for every one. We know it for the ones who tell us.
Priya: One thing we should not talk about publicly yet is the pricing change.
""" + "Filler discussion line to clear the minimum word count. " * 20


class _FakeResponse:
    ok = True
    error = None

    def __init__(self, data):
        self.data = data


def _run_with_model(payload):
    """Drive the LLM path with a canned payload."""
    with patch("fcie.pipeline.meetings.AIClient") as client_cls:
        client = client_cls.return_value
        client.available = True
        client.model = "test-model"
        client.complete_json.return_value = _FakeResponse(payload)
        return analyse_transcript(TRANSCRIPT, title="Test meeting")


class TestVerbatimGate:
    def test_a_fabricated_quote_is_discarded(self):
        notes = _run_with_model({
            "summary": "s",
            "quotes": [
                {"quote": "Anything that comes in after four in the afternoon waits until morning.",
                 "speaker": "Marcus", "why_notable": "real"},
                {"quote": "We lost sixty percent of our pipeline last quarter.",
                 "speaker": "Dana", "why_notable": "invented"},
            ],
        })
        kept = [q["quote"] for q in notes.quotes]
        assert len(kept) == 1
        assert "sixty percent" not in " ".join(kept)
        assert notes.dropped_unverifiable == 1

    def test_a_paraphrased_quote_is_discarded(self):
        """Close is not good enough — the gate is exact, not fuzzy."""
        notes = _run_with_model({
            "summary": "s",
            "quotes": [{"quote": "Anything arriving after 4pm waits until the morning.",
                        "speaker": "Marcus", "why_notable": "tidied up"}],
        })
        assert notes.quotes == []
        assert notes.dropped_unverifiable == 1

    def test_unverifiable_evidence_does_not_silently_back_an_idea(self):
        notes = _run_with_model({
            "summary": "s",
            "content_ideas": [{
                "idea": "Speed to lead matters",
                "evidence_quote": "Our close rate fell by half, which we measured precisely.",
                "suggested_post": "Businesses lose leads overnight.",
            }],
        })
        assert notes.content_ideas[0]["evidence_quote"] == ""
        assert notes.dropped_unverifiable == 1

    def test_decision_keeps_its_quote_when_it_is_real(self):
        notes = _run_with_model({
            "summary": "s",
            "decisions": [{
                "decision": "Pilot evening coverage",
                "owner": "Priya",
                "quote": "We'll pilot evening coverage for two weeks and measure the close rate.",
            }],
        })
        assert notes.decisions[0]["quote"]
        assert notes.dropped_unverifiable == 0


class TestGuards:
    def test_short_transcript_is_refused_rather_than_guessed_at(self):
        notes = analyse_transcript("Too short.", title="x")
        assert not notes.ok
        assert str(MIN_TRANSCRIPT_WORDS) in " ".join(notes.warnings)

    def test_nothing_is_written_to_the_database(self, temp_db):
        """The page is exposed in the read-only demo, so this must hold."""
        from sqlalchemy import select

        from fcie.models import ContentDraft, ExtractedSignal, Source

        _run_with_model({"summary": "s", "content_ideas": []})
        with temp_db.session_scope() as session:
            assert session.scalar(select(Source).limit(1)) is None
            assert session.scalar(select(ExtractedSignal).limit(1)) is None
            assert session.scalar(select(ContentDraft).limit(1)) is None


class TestHeuristicFallback:
    def test_works_with_no_model_configured(self):
        with patch("fcie.pipeline.meetings.AIClient") as client_cls:
            client_cls.return_value.available = False
            notes = analyse_transcript(TRANSCRIPT, title="No key")
        assert notes.backend == "heuristic-v1"
        assert notes.ok
        assert any("deterministic" in w for w in notes.warnings)

    def test_markdown_export_runs_on_every_backend(self):
        with patch("fcie.pipeline.meetings.AIClient") as client_cls:
            client_cls.return_value.available = False
            notes = analyse_transcript(TRANSCRIPT, title="Export")
        text = notes_to_markdown(notes)
        assert "# Export" in text
        assert "Not affiliated" in text
