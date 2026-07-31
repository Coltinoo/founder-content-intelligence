"""Database creation, model round-trips, dedupe-on-write, and brief↔source linkage."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from fcie.models import (
    ContentDraft,
    ContentOpportunity,
    EngagementWatchlistItem,
    ExtractedSignal,
    RunLog,
    Source,
    Theme,
    VoiceExample,
)

EXPECTED_TABLES = {
    "sources", "extracted_signals", "themes", "content_opportunities",
    "content_drafts", "voice_examples", "engagement_watchlist", "run_log",
}


class TestSchema:
    def test_all_tables_created(self, temp_db):
        tables = set(temp_db.init_db())
        assert EXPECTED_TABLES <= tables

    def test_init_is_idempotent(self, temp_db):
        first = temp_db.init_db()
        second = temp_db.init_db()
        assert first == second

    def test_reset_clears_data(self, temp_db):
        with temp_db.session_scope() as session:
            session.add(Source(source_type="manual_text", source_url="u",
                               canonical_url="https://e.com/1", source_domain="e.com"))
        temp_db.reset_db()
        with temp_db.session_scope() as session:
            assert session.scalar(select(Source).limit(1)) is None


class TestJSONColumns:
    def test_lists_round_trip(self, temp_db):
        with temp_db.session_scope() as session:
            session.add(Source(source_type="rss", source_url="u",
                               canonical_url="https://e.com/1", source_domain="e.com"))
            session.flush()
            session.add(ExtractedSignal(
                source_id=1,
                industries=["Automotive", "Home services"],
                supporting_evidence=[{"passage": "verbatim text", "verified_verbatim": True}],
                score_breakdown={"total": 72.5, "components": []},
            ))
        with temp_db.session_scope() as session:
            signal = session.scalar(select(ExtractedSignal))
            assert signal.industries == ["Automotive", "Home services"]
            assert signal.supporting_evidence[0]["verified_verbatim"] is True
            assert signal.score_breakdown["total"] == 72.5

    def test_null_json_defaults_to_empty(self, temp_db):
        with temp_db.session_scope() as session:
            session.add(Source(source_type="rss", source_url="u",
                               canonical_url="https://e.com/2", source_domain="e.com"))
            session.flush()
            session.add(ExtractedSignal(source_id=1))
        with temp_db.session_scope() as session:
            signal = session.scalar(select(ExtractedSignal))
            assert signal.industries == []
            assert signal.score_breakdown == {}


class TestCanonicalUniqueness:
    def test_duplicate_canonical_url_is_rejected(self, temp_db):
        from sqlalchemy.exc import IntegrityError

        with temp_db.session_scope() as session:
            session.add(Source(source_type="rss", source_url="a",
                               canonical_url="https://e.com/same", source_domain="e.com"))
        with pytest.raises(IntegrityError):
            with temp_db.session_scope() as session:
                session.add(Source(source_type="web_search", source_url="b",
                                   canonical_url="https://e.com/same", source_domain="e.com"))


class TestIngestDeduplication:
    def test_same_article_from_two_queries_stores_once(self, temp_db):
        from fcie.connectors.base import DiscoveredItem
        from fcie.pipeline.ingest import _store_item

        text = " ".join(
            f"Missed after-hours calls cost local businesses real revenue, point {i}."
            for i in range(40)
        )
        first = DiscoveredItem(
            source_url="https://example.com/story?utm_source=a",
            source_type="web_search", title="Missed calls are costing local businesses",
            search_query="small business missed calls AI", raw_text=text,
            needs_fetch=False, metadata={"cleaned_text": text},
        )
        second = DiscoveredItem(
            source_url="https://www.example.com/story/",
            source_type="web_search", title="Missed calls are costing local businesses",
            search_query="AI customer follow-up local business", raw_text=text,
            needs_fetch=False, metadata={"cleaned_text": text},
        )

        assert _store_item(first, fetcher=None, fetch_bodies=False)["result"] == "stored"
        outcome = _store_item(second, fetcher=None, fetch_bodies=False)
        assert outcome["result"] == "duplicate"

        with temp_db.session_scope() as session:
            rows = session.execute(select(Source)).scalars().all()
            assert len(rows) == 1
            queries = rows[0].metadata_json["discovered_by_queries"]
            assert "AI customer follow-up local business" in queries

    def test_distinct_articles_are_both_stored(self, temp_db):
        from fcie.connectors.base import DiscoveredItem
        from fcie.pipeline.ingest import _store_item

        for index, (url, title, body) in enumerate([
            ("https://a.com/1", "HVAC dispatch software pricing in 2026",
             "Contractors compare dispatch tools on scheduling and routing features. " * 20),
            ("https://b.com/2", "Medspa injectables demand shifts to weekday evenings",
             "Aesthetic clinics report booking pattern changes across their locations. " * 20),
        ]):
            item = DiscoveredItem(source_url=url, source_type="rss", title=title,
                                  raw_text=body, needs_fetch=False,
                                  metadata={"cleaned_text": body})
            assert _store_item(item, fetcher=None, fetch_bodies=False)["result"] == "stored"

        with temp_db.session_scope() as session:
            assert len(session.execute(select(Source)).scalars().all()) == 2


class TestChannelInterleaving:
    """Undated first-party content must not be starved by dated RSS items."""

    def _items(self):
        from fcie.connectors.base import DiscoveredItem

        items = []
        # 60 dated RSS items — these would otherwise monopolise the whole budget.
        for index in range(60):
            items.append(DiscoveredItem(
                source_url=f"https://feed{index}.com/a", source_type="rss",
                title=f"Feed article {index}",
                published_at=datetime.now(timezone.utc) - timedelta(hours=index),
            ))
        # 10 undated Podium pages.
        for index in range(10):
            items.append(DiscoveredItem(
                source_url=f"https://podium.com/page{index}", source_type="podium_site",
                title=f"Podium page {index}", published_at=None,
            ))
        return items

    def test_first_party_sources_reach_the_front_of_the_queue(self):
        from fcie.pipeline.ingest import _interleave_by_channel

        ordered = _interleave_by_channel(self._items())
        first_ten = ordered[:10]
        assert any(i.source_type == "podium_site" for i in first_ten), (
            "undated first-party pages were starved by dated RSS items"
        )
        # Podium is highest priority, so it leads.
        assert ordered[0].source_type == "podium_site"

    def test_a_small_cap_still_yields_a_mixed_corpus(self):
        from fcie.pipeline.ingest import _interleave_by_channel

        ordered = _interleave_by_channel(self._items())[:20]
        types = {i.source_type for i in ordered}
        assert types == {"rss", "podium_site"}

    def test_nothing_is_lost_or_duplicated(self):
        from fcie.pipeline.ingest import _interleave_by_channel

        items = self._items()
        ordered = _interleave_by_channel(items)
        assert len(ordered) == len(items)
        assert {i.source_url for i in ordered} == {i.source_url for i in items}

    def test_newest_first_within_a_channel(self):
        from fcie.pipeline.ingest import _interleave_by_channel

        ordered = _interleave_by_channel(self._items())
        rss = [i for i in ordered if i.source_type == "rss"]
        dates = [i.published_at for i in rss]
        assert dates == sorted(dates, reverse=True)

    def test_empty_input(self):
        from fcie.pipeline.ingest import _interleave_by_channel

        assert _interleave_by_channel([]) == []


class TestRestrictedBodyHandling:
    """A blocked article body must never be bypassed, but the publisher's own
    syndicated summary is legitimate content and should not be thrown away."""

    class _BlockingFetcher:
        """Stands in for a site that 403s article bodies."""

        def __init__(self):
            from fcie.utils.http import RateLimiter

            self.limiter = RateLimiter(0.0)

        def fetch(self, url):
            from fcie.utils.http import FetchResult

            return FetchResult(
                url=url, status_code=403, ok=False,
                skipped_reason="restricted",
                error="HTTP 403 - access restricted. Not bypassed.",
            )

    def test_summary_is_kept_and_made_analysable(self, temp_db):
        from fcie.connectors.base import DiscoveredItem
        from fcie.pipeline.ingest import _store_item

        summary = ("Local service businesses are losing after-hours demand to voicemail, "
                   "and operators say response speed now decides who wins the job. " * 3)
        item = DiscoveredItem(
            source_url="https://paywalled.example.com/story", source_type="rss",
            title="Response speed decides who wins the job", summary=summary,
            needs_fetch=True, published_at=datetime.now(timezone.utc),
        )
        outcome = _store_item(item, fetcher=self._BlockingFetcher(), fetch_bodies=True)
        assert outcome["result"] == "stored"
        assert outcome["summary_only"] is True

        with temp_db.session_scope() as session:
            source = session.get(Source, outcome["id"])
            assert source.status == "summary_only"
            assert source.cleaned_text
            # The restriction is recorded, not hidden.
            assert "403" in (source.fetch_error or "")
            assert "Not bypassed" in (source.fetch_error or "")
            assert source.metadata_json["summary_only"] is True

    def test_short_summary_is_still_a_policy_skip(self, temp_db):
        from fcie.connectors.base import DiscoveredItem
        from fcie.pipeline.ingest import _store_item

        item = DiscoveredItem(
            source_url="https://paywalled.example.com/tiny", source_type="rss",
            title="Tiny", summary="Too short.", needs_fetch=True,
        )
        outcome = _store_item(item, fetcher=self._BlockingFetcher(), fetch_bodies=True)
        assert outcome["result"] == "policy_skip"

    def test_summary_only_sources_are_extracted(self, temp_db):
        from fcie.connectors.base import DiscoveredItem
        from fcie.pipeline.extract import run_extraction
        from fcie.pipeline.ingest import _store_item

        summary = ("Local service businesses are losing after-hours demand to voicemail. "
                   "Operators say response speed now decides who wins the job, and missed "
                   "calls are the largest single source of lost revenue. " * 3)
        item = DiscoveredItem(
            source_url="https://paywalled.example.com/story2", source_type="rss",
            title="Missed calls and lost revenue", summary=summary, needs_fetch=True,
            published_at=datetime.now(timezone.utc),
        )
        outcome = _store_item(item, fetcher=self._BlockingFetcher(), fetch_bodies=True)
        report = run_extraction(source_ids=[outcome["id"]], force_heuristic=True)
        assert report.succeeded == 1

        with temp_db.session_scope() as session:
            signal = session.scalar(
                select(ExtractedSignal).where(ExtractedSignal.source_id == outcome["id"])
            )
            assert signal is not None
            assert signal.is_summary_only is True
            assert any("not bypassed" in n.lower() for n in signal.verification_notes)


class TestManualEntry:
    def test_manual_source_requires_text(self):
        from fcie.connectors.manual import build_manual_item

        with pytest.raises(ValueError):
            build_manual_item(text="", url="https://e.com/1")

    def test_manual_source_without_url_gets_stable_identifier(self):
        from fcie.connectors.manual import build_manual_item

        a = build_manual_item(text="Some pasted public content here for the library.")
        b = build_manual_item(text="Some pasted public content here for the library.")
        assert a.source_url.startswith("manual://")
        assert a.source_url == b.source_url

    def test_manual_source_stores_and_dedupes(self, temp_db):
        from fcie.connectors.manual import build_manual_item
        from fcie.pipeline.ingest import ingest_manual_item

        item = build_manual_item(
            text="A public post about missed calls in home services. " * 12,
            source_type="manual_social", url="https://example.com/post/1",
            title="Public post", author="An Author",
        )
        assert ingest_manual_item(item)["result"] == "stored"
        assert ingest_manual_item(item)["result"] == "duplicate"


class TestBriefSourceLinkage:
    """A brief must never reference a source that does not exist."""

    def _seed(self, temp_db):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        text = (
            "After-hours calls to local service businesses regularly go unanswered. "
            "One operator reported losing several jobs a week to voicemail. "
            "Speed to lead determines who wins the customer."
        )
        source_ids = []
        with temp_db.session_scope() as session:
            for index, domain in enumerate(["cbtnews.com", "achrnews.com", "smallbiztrends.com"]):
                source = Source(
                    source_type="rss", source_url=f"https://{domain}/a{index}",
                    canonical_url=f"https://{domain}/a{index}", source_domain=domain,
                    title=f"After-hours demand goes unanswered in the trades, part {index}",
                    published_at=now - timedelta(days=index + 1),
                    discovered_at=now, cleaned_text=text, status="extracted",
                )
                session.add(source)
                session.flush()
                source_ids.append(source.id)
                session.add(ExtractedSignal(
                    source_id=source.id,
                    primary_theme="Missed after-hours leads",
                    secondary_themes=["Speed to lead"],
                    industries=["Home services"],
                    customer_problem="After-hours calls go unanswered.",
                    primary_claim="Local businesses lose jobs to voicemail.",
                    supporting_evidence=[{
                        "passage": "After-hours calls to local service businesses regularly go unanswered.",
                        "verified_verbatim": True,
                    }],
                    notable_quotes=[], numerical_claims=[],
                    podium_relevance=8.0, founder_relevance=7.5, evidence_strength=7.0,
                    business_impact=7.0, novelty_score=6.0, freshness_score=9.0,
                    opportunity_score=76.0, extraction_method="heuristic",
                    extraction_model="heuristic-v1", extracted_at=now,
                ))
        return source_ids

    def test_generated_brief_links_only_to_real_sources(self, temp_db):
        from fcie.pipeline.opportunities import generate_opportunities
        from fcie.pipeline.trends import run_trend_analysis

        seeded = set(self._seed(temp_db))
        run_trend_analysis(write_rationale=False)
        report = generate_opportunities(force_heuristic=True)
        assert report.created >= 1

        with temp_db.session_scope() as session:
            opportunity = session.scalar(select(ContentOpportunity))
            assert opportunity is not None
            assert set(opportunity.supporting_source_ids) <= seeded
            assert opportunity.supporting_points, "brief must have evidenced points"
            for point in opportunity.supporting_points:
                assert point["evidence_source_ids"]
                assert set(point["evidence_source_ids"]) <= seeded
                assert point["evidence_passage"]
            for passage in opportunity.evidence_passages:
                assert passage["source_id"] in seeded

    def test_every_brief_evidence_passage_exists_in_its_source(self, temp_db):
        from fcie.pipeline.opportunities import generate_opportunities
        from fcie.pipeline.trends import run_trend_analysis
        from fcie.utils.text import is_verbatim

        self._seed(temp_db)
        run_trend_analysis(write_rationale=False)
        generate_opportunities(force_heuristic=True)

        with temp_db.session_scope() as session:
            opportunity = session.scalar(select(ContentOpportunity))
            for passage in opportunity.evidence_passages:
                source = session.get(Source, passage["source_id"])
                assert source is not None
                assert is_verbatim(passage["passage"], source.cleaned_text)

    def test_draft_stays_linked_to_opportunity_and_sources(self, temp_db):
        from fcie.pipeline.drafts import draft_source_links, generate_draft
        from fcie.pipeline.opportunities import generate_opportunities
        from fcie.pipeline.trends import run_trend_analysis

        seeded = set(self._seed(temp_db))
        run_trend_analysis(write_rationale=False)
        generate_opportunities(force_heuristic=True)

        with temp_db.session_scope() as session:
            opportunity_id = session.scalar(select(ContentOpportunity.id))

        result = generate_draft(opportunity_id, "linkedin_post", force_heuristic=True)
        assert result["ok"]
        assert result["draft_text"]
        assert set(result["cited_source_ids"]) <= seeded

        links = draft_source_links(result["draft_id"])
        assert links
        for link in links:
            assert link["url"].startswith("http")

        with temp_db.session_scope() as session:
            draft = session.get(ContentDraft, result["draft_id"])
            assert draft.content_opportunity_id == opportunity_id
            assert draft.approval_status == "pending_review"

    def test_approval_requires_an_explicit_human_action(self, temp_db):
        from fcie.pipeline.drafts import generate_draft, set_approval
        from fcie.pipeline.opportunities import generate_opportunities
        from fcie.pipeline.trends import run_trend_analysis

        self._seed(temp_db)
        run_trend_analysis(write_rationale=False)
        generate_opportunities(force_heuristic=True)
        with temp_db.session_scope() as session:
            opportunity_id = session.scalar(select(ContentOpportunity.id))

        result = generate_draft(opportunity_id, "linkedin_post", force_heuristic=True)
        with temp_db.session_scope() as session:
            assert session.get(ContentDraft, result["draft_id"]).approval_status == "pending_review"

        assert set_approval(result["draft_id"], "approved", "checked the sources")
        with temp_db.session_scope() as session:
            assert session.get(ContentDraft, result["draft_id"]).approval_status == "approved"
            assert session.get(ContentOpportunity, opportunity_id).status == "approved"

    def test_invalid_approval_status_rejected(self, temp_db):
        from fcie.pipeline.drafts import set_approval

        assert set_approval(999, "published_live") is False


class TestEvidenceRanking:
    """Independent reporting must outrank vendor copy in every brief."""

    def _evidence(self):
        from fcie.pipeline.opportunities import ThemeEvidence

        ev = ThemeEvidence(theme={"name": "Missed after-hours leads"})
        ev.sources = [
            {"id": 1, "is_promotional": True, "domain": "podium.com", "industries": []},
            {"id": 2, "is_promotional": False, "domain": "achrnews.com", "industries": []},
        ]
        ev.passages = [
            {"source_id": 1, "url": "u1", "domain": "podium.com",
             "passage": "Watch a demo and turn missed calls into revenue with our platform."},
            {"source_id": 2, "url": "u2", "domain": "achrnews.com",
             "passage": "Contractors reported that 38% of after-hours calls went unanswered last year."},
        ]
        ev.quotes = [
            {"source_id": 1, "url": "u1", "quote": "reply to get 10% off your next order!",
             "speaker": None},
            {"source_id": 2, "url": "u2",
             "quote": "We were missing calls every single evening and had no idea it was happening.",
             "speaker": "Dana Whitfield"},
        ]
        return ev

    def test_independent_passage_ranks_first(self):
        from fcie.pipeline.opportunities import _rank_evidence

        ev = self._evidence()
        _rank_evidence(ev)
        assert ev.passages[0]["source_id"] == 2

    def test_attributed_quote_ranks_above_marketing_sms(self):
        from fcie.pipeline.opportunities import _rank_evidence

        ev = self._evidence()
        _rank_evidence(ev)
        assert ev.quotes[0]["speaker"] == "Dana Whitfield"

    def test_hook_never_opens_with_a_promotional_fragment(self):
        from fcie.pipeline.opportunities import HeuristicBriefBuilder, _rank_evidence

        ev = self._evidence()
        _rank_evidence(ev)
        hook = HeuristicBriefBuilder._hook(ev, "Missed after-hours leads")
        assert "10% off" not in hook

    def test_weak_only_quote_is_not_used_as_a_hook(self):
        from fcie.pipeline.opportunities import HeuristicBriefBuilder, _rank_evidence

        ev = self._evidence()
        ev.quotes = [ev.quotes[0]]          # only the marketing SMS remains
        ev.problems = [{"source_id": 2, "text": "After-hours calls go unanswered.", "url": "u2"}]
        _rank_evidence(ev)
        hook = HeuristicBriefBuilder._hook(ev, "Missed after-hours leads")
        assert "10% off" not in hook
        assert "unanswered" in hook

    def test_off_theme_passage_is_dropped_even_though_independent(self):
        from fcie.pipeline.opportunities import ThemeEvidence, _rank_evidence

        ev = ThemeEvidence(theme={"name": "Missed after-hours leads"})
        ev.sources = [
            {"id": 1, "is_promotional": False, "domain": "techcrunch.com", "industries": []},
            {"id": 2, "is_promotional": True, "domain": "podium.com", "industries": []},
        ]
        ev.passages = [
            {"source_id": 1, "url": "u1", "domain": "techcrunch.com",
             "passage": "AWS revenue rose 37% year over year, clocking $42 billion for the quarter."},
            {"source_id": 2, "url": "u2", "domain": "podium.com",
             "passage": "Shops said a missed call after hours is how most jobs are lost."},
        ]
        _rank_evidence(ev)
        assert all("AWS revenue" not in p["passage"] for p in ev.passages), (
            "an off-theme passage must not survive just because its source is independent"
        )
        assert ev.passages[0]["source_id"] == 2

    def test_off_theme_quote_never_becomes_the_hook(self):
        from fcie.pipeline.opportunities import (
            HeuristicBriefBuilder, ThemeEvidence, _rank_evidence,
        )

        ev = ThemeEvidence(theme={"name": "AI skepticism and trust"})
        ev.sources = [{"id": 1, "is_promotional": False, "domain": "reuters.com",
                       "industries": []}]
        ev.quotes = [{
            "source_id": 1, "url": "u1", "speaker": None,
            "quote": "The fund's largest holdings at the end of the first quarter "
                     "included Nebius Group, Sandisk, Micron and CoreWeave.",
        }]
        ev.problems = [{"source_id": 1, "text": "Buyers say AI vendors overpromise.",
                        "url": "u1"}]
        _rank_evidence(ev)
        hook = HeuristicBriefBuilder._hook(ev, "AI skepticism and trust")
        assert "Nebius" not in hook, "an off-theme quote must not become the hook"

    def test_off_theme_figure_never_becomes_the_hook(self):
        from fcie.pipeline.opportunities import (
            HeuristicBriefBuilder, ThemeEvidence, _rank_evidence,
        )

        ev = ThemeEvidence(theme={"name": "Missed after-hours leads"})
        ev.sources = [{"id": 1, "is_promotional": False, "domain": "forrester.com",
                       "industries": []}]
        ev.numbers = [{
            "source_id": 1, "url": "u1", "value": "$4 billion",
            "context": "OpenAI followed with the Deployment Company, with $4 billion of "
                       "initial investment.",
        }]
        ev.problems = [{"source_id": 1, "url": "u1",
                        "text": "Shops lose jobs when an after-hours call goes unanswered."}]
        _rank_evidence(ev)
        hook = HeuristicBriefBuilder._hook(ev, "Missed after-hours leads")
        assert "$4 billion" not in hook
        assert "unanswered" in hook

    def test_off_theme_problem_statement_never_becomes_the_hook(self):
        from fcie.pipeline.opportunities import (
            HeuristicBriefBuilder, ThemeEvidence, _rank_evidence,
        )

        ev = ThemeEvidence(theme={"name": "Missed after-hours leads"})
        ev.sources = [{"id": 1, "is_promotional": False, "domain": "forrester.com",
                       "industries": []}]
        ev.problems = [{
            "source_id": 1, "url": "u1",
            "text": "Microsoft closed the run two days later with Frontier Company "
                    "($2.5 billion and 6,000 people).",
        }]
        _rank_evidence(ev)
        hook = HeuristicBriefBuilder._hook(ev, "Missed after-hours leads")
        assert "Microsoft" not in hook, (
            "the last fallback in the hook chain must be theme-filtered too"
        )

    def test_on_theme_figure_is_still_usable(self):
        from fcie.pipeline.opportunities import ThemeEvidence, _rank_evidence

        ev = ThemeEvidence(theme={"name": "Missed after-hours leads"})
        ev.sources = [{"id": 1, "is_promotional": False, "domain": "achrnews.com",
                       "industries": []}]
        ev.numbers = [{
            "source_id": 1, "url": "u1", "value": "38%",
            "context": "38% of after-hours calls went unanswered across the surveyed shops.",
        }]
        _rank_evidence(ev)
        assert ev.numbers, "an on-theme figure must survive ranking"
        assert ev.numbers[0]["value"] == "38%"

    def test_wrong_sense_of_a_keyword_is_rejected(self):
        """"After-hours trading" is the stock market, not a missed customer call."""
        from fcie.pipeline.opportunities import ThemeEvidence, _rank_evidence

        ev = ThemeEvidence(theme={"name": "Missed after-hours leads"})
        ev.sources = [
            {"id": 1, "is_promotional": False, "domain": "techcrunch.com", "industries": []},
            {"id": 2, "is_promotional": True, "domain": "podium.com", "industries": []},
        ]
        ev.passages = [
            {"source_id": 1, "url": "u1", "domain": "techcrunch.com",
             "passage": "This was enough to send Amazon's stock up nearly 10% in "
                        "after-hours trading on Thursday."},
            {"source_id": 2, "url": "u2", "domain": "podium.com",
             "passage": "Automatically text missed or after-hours calls, keeping the "
                        "customer from going somewhere else."},
        ]
        _rank_evidence(ev)
        assert all("trading" not in p["passage"] for p in ev.passages)

    def test_repeated_boilerplate_yields_one_point_not_three(self):
        from fcie.pipeline.opportunities import HeuristicBriefBuilder, ThemeEvidence

        boilerplate = ("During this time, we have deployed 10,000 AI employees to empower "
                       "real business outcomes for our customers.")
        ev = ThemeEvidence(theme={"name": "AI employee accountability"})
        ev.sources = [{"id": i, "is_promotional": False, "domain": "job-boards.greenhouse.io",
                       "industries": []} for i in (1, 2, 3)]
        ev.passages = [
            {"source_id": i, "url": f"u{i}", "domain": "job-boards.greenhouse.io",
             "passage": boilerplate}
            for i in (1, 2, 3)
        ]
        points = HeuristicBriefBuilder._supporting_points(ev)
        assert len(points) == 1, "identical boilerplate must not become three points"

    def test_first_party_content_off_domain_is_flagged_promotional(self):
        from datetime import datetime, timezone

        from fcie.ai.extraction import HeuristicExtractor

        result = HeuristicExtractor().extract(
            text="We are hiring. " * 40, title="Job",
            url="https://job-boards.greenhouse.io/podium81/jobs/1",
            published_at=datetime.now(timezone.utc), source_type="podium_site",
            domain="job-boards.greenhouse.io", metadata={"first_party": True},
        )
        assert result.is_promotional_source, (
            "a company's own job board is first-party content, not independent corroboration"
        )

    def test_supporting_points_lead_with_independent_evidence(self):
        from fcie.pipeline.opportunities import HeuristicBriefBuilder, _rank_evidence

        ev = self._evidence()
        _rank_evidence(ev)
        points = HeuristicBriefBuilder._supporting_points(ev)
        assert points[0]["evidence_source_ids"] == [2]


class TestDraftAttribution:
    """A verbatim source sentence must never be rendered as the author's own words."""

    POINT = {
        "point": "After-hours calls to local service businesses regularly go unanswered",
        "evidence_passage": "After-hours calls to local service businesses regularly go unanswered.",
        "evidence_source_ids": [3],
        "evidence_domain": "achrnews.com",
        "evidence_url": "https://achrnews.com/a",
    }
    SUMMARY_POINT = {
        "point": "Response speed, not lead volume, is the binding constraint",
        "evidence_passage": "After-hours calls to local service businesses regularly go unanswered.",
        "evidence_source_ids": [3],
        "evidence_domain": "achrnews.com",
        "evidence_url": "https://achrnews.com/a",
    }

    def test_detects_a_verbatim_point(self):
        from fcie.pipeline.drafts import HeuristicDraftWriter

        assert HeuristicDraftWriter._is_verbatim_point(self.POINT)
        assert not HeuristicDraftWriter._is_verbatim_point(self.SUMMARY_POINT)

    def test_verbatim_point_is_quoted_and_attributed(self):
        from fcie.pipeline.drafts import HeuristicDraftWriter

        rendered = HeuristicDraftWriter._render_point(self.POINT)
        assert '"' in rendered, "a verbatim source sentence must be quoted"
        assert "achrnews.com" in rendered, "a verbatim quote must be attributed"

    def test_summary_point_is_not_falsely_quoted(self):
        from fcie.pipeline.drafts import HeuristicDraftWriter

        rendered = HeuristicDraftWriter._render_point(self.SUMMARY_POINT)
        assert '"' not in rendered
        assert "#3" in rendered

    def test_linkedin_draft_quotes_its_verbatim_points(self):
        from fcie.pipeline.drafts import HeuristicDraftWriter

        opportunity = {
            "title": "T", "hook": "A hook.", "core_insight": "An insight.",
            "founder_point_of_view": "[Inference] An argument.",
            "supporting_points": [self.POINT],
            "suggested_call_to_action": "Ask the reader to audit their operation.",
        }
        result = HeuristicDraftWriter().write(opportunity, "linkedin_post", [])
        assert "achrnews.com" in result.draft_text
        assert '"After-hours calls' in result.draft_text
        assert result.cited_source_ids == [3]


class TestStaleBriefRetirement:
    """A brief whose evidence has weakened must not keep ranking on stale numbers."""

    def _seed_opportunity(self, temp_db, status="ready_for_brief"):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with temp_db.session_scope() as session:
            theme = Theme(slug="ai-skepticism", name="AI skepticism and trust",
                          source_count=2, trend_status="stable")
            session.add(theme)
            session.flush()
            session.add(ContentOpportunity(
                theme_id=theme.id, title="Stale brief", status=status,
                opportunity_score=70.0, created_at=now,
            ))

    def test_below_threshold_theme_archives_its_brief(self, temp_db):
        from fcie.pipeline.opportunities import _retire_stale_opportunity

        self._seed_opportunity(temp_db)
        assert _retire_stale_opportunity("AI skepticism and trust", "score 52 below 55")

        with temp_db.session_scope() as session:
            opportunity = session.scalar(select(ContentOpportunity))
            assert opportunity.status == "archived"
            assert "Evidence base weakened" in (opportunity.reviewer_notes or "")

    def test_human_approved_brief_is_annotated_not_overruled(self, temp_db):
        from fcie.pipeline.opportunities import _retire_stale_opportunity

        self._seed_opportunity(temp_db, status="approved")
        _retire_stale_opportunity("AI skepticism and trust", "score 52 below 55")

        with temp_db.session_scope() as session:
            opportunity = session.scalar(select(ContentOpportunity))
            assert opportunity.status == "approved", "a human sign-off must not be overruled"
            assert "Evidence base weakened" in (opportunity.reviewer_notes or "")

    def test_unknown_theme_is_a_no_op(self, temp_db):
        from fcie.pipeline.opportunities import _retire_stale_opportunity

        assert _retire_stale_opportunity("No Such Theme", "reason") is False


class TestTrendGuards:
    def test_single_source_is_never_a_trend(self, temp_db):
        from fcie.pipeline.trends import run_trend_analysis

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with temp_db.session_scope() as session:
            source = Source(source_type="rss", source_url="https://only.com/1",
                            canonical_url="https://only.com/1", source_domain="only.com",
                            title="A lone article", published_at=now,
                            discovered_at=now, cleaned_text="text", status="extracted")
            session.add(source)
            session.flush()
            session.add(ExtractedSignal(source_id=source.id, primary_theme="AI skepticism and trust",
                                        podium_relevance=6, evidence_strength=5,
                                        extracted_at=now))

        run_trend_analysis(write_rationale=False)
        with temp_db.session_scope() as session:
            theme = session.scalar(select(Theme))
            assert theme.trend_status == "low_confidence"
            assert "1 source" in theme.trend_rationale

    def test_single_domain_repeats_are_low_confidence(self, temp_db):
        from fcie.pipeline.trends import run_trend_analysis

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with temp_db.session_scope() as session:
            for index in range(4):
                source = Source(source_type="rss", source_url=f"https://one.com/{index}",
                                canonical_url=f"https://one.com/{index}", source_domain="one.com",
                                title=f"Article {index}", published_at=now,
                                discovered_at=now, cleaned_text="t", status="extracted")
                session.add(source)
                session.flush()
                session.add(ExtractedSignal(source_id=source.id,
                                            primary_theme="AI skepticism and trust",
                                            podium_relevance=6, evidence_strength=5,
                                            extracted_at=now))

        run_trend_analysis(write_rationale=False)
        with temp_db.session_scope() as session:
            theme = session.scalar(select(Theme))
            assert theme.trend_status == "low_confidence"
            assert "domain" in theme.trend_rationale.lower()


class TestVoiceLibrary:
    def test_empty_library_makes_no_voice_claim(self, temp_db):
        from fcie.pipeline.voice import build_voice_guide

        guide = build_voice_guide()
        assert guide["status"] == "empty"
        assert guide["approved_example_count"] == 0
        assert guide["unsupported_assumptions"]

    def test_example_is_analysed_on_add(self, temp_db):
        from fcie.pipeline.voice import add_voice_example

        example_id = add_voice_example(
            title="Test post",
            text="Most local businesses don't have a lead problem.\n\n"
                 "They have a response problem. We saw 40% of calls go unanswered.\n\n"
                 "What are you seeing?",
            content_type="linkedin_post", approved=True,
        )
        with temp_db.session_scope() as session:
            example = session.get(VoiceExample, example_id)
            assert example.analysis_json
            assert example.hook_style
            assert example.analysis_json["number_count"] >= 1

    def test_guide_warns_below_five_examples(self, temp_db):
        from fcie.pipeline.voice import add_voice_example, build_voice_guide

        add_voice_example(title="One", text="A short public example about local business revenue.",
                          approved=True)
        guide = build_voice_guide()
        assert guide["approved_example_count"] == 1
        assert guide["coverage_warning"]
        assert "1 approved example" in guide["coverage_warning"]

    def test_voice_score_is_zero_without_examples(self, temp_db):
        from fcie.pipeline.drafts import score_voice_alignment
        from fcie.pipeline.voice import build_voice_guide

        score, notes = score_voice_alignment("Any draft text here.", build_voice_guide())
        assert score == 0.0
        assert any("No approved voice examples" in n for n in notes)


class TestFeedFetchIsBounded:
    """A hanging publisher must not be able to stall a scheduled run."""

    def test_socket_default_timeout_is_set(self):
        import socket

        import fcie.config  # noqa: F401  (import applies the backstop)

        assert socket.getdefaulttimeout() is not None, (
            "an unbounded socket timeout lets urllib-based fetchers hang forever"
        )

    def test_fetch_feed_reports_errors_instead_of_raising(self):
        from fcie.utils.http import PoliteFetcher

        fetcher = PoliteFetcher(timeout=2)
        body, error = fetcher.fetch_feed("https://127.0.0.1:9/nonexistent.xml")
        assert body is None
        assert error
        fetcher.close()

    def test_rss_connector_survives_a_failing_feed(self, temp_db):
        from fcie.connectors.rss import RSSConnector
        from fcie.utils.http import PoliteFetcher

        class _FailingFetcher(PoliteFetcher):
            def fetch_feed(self, url):
                return None, "timeout after 2s"

        fetcher = _FailingFetcher(timeout=2)
        connector = RSSConnector(
            feeds=[{"name": "Dead feed", "url": "https://example.invalid/feed"}],
            fetcher=fetcher,
        )
        result = connector.discover()
        assert result.items == []
        assert any("timeout" in e for e in result.errors)
        fetcher.close()


class TestUnsupportedSources:
    def test_blocked_domain_is_refused(self, temp_db):
        from fcie.utils.http import PoliteFetcher

        fetcher = PoliteFetcher(blocked_domains={"linkedin.com"})
        result = fetcher.fetch("https://www.linkedin.com/in/someone")
        assert not result.ok
        assert result.skipped_reason == "blocked_domain"
        fetcher.close()

    def test_non_http_scheme_is_refused(self, temp_db):
        from fcie.utils.http import PoliteFetcher

        fetcher = PoliteFetcher()
        result = fetcher.fetch("mailto:someone@example.com")
        assert not result.ok
        assert result.error
        fetcher.close()

    def test_unknown_prompt_name_raises(self):
        from fcie.ai.prompts import load_prompt

        with pytest.raises(KeyError):
            load_prompt("no_such_prompt")


class TestRunLog:
    def test_run_log_round_trip(self, temp_db):
        with temp_db.session_scope() as session:
            session.add(RunLog(trigger="cli", stages={"ingest": {"stored": 5}},
                               sources_fetched=5, errors=["one problem"]))
        with temp_db.session_scope() as session:
            run = session.scalar(select(RunLog))
            assert run.stages["ingest"]["stored"] == 5
            assert run.errors == ["one problem"]


class TestWatchlist:
    def test_watchlist_item_round_trip(self, temp_db):
        with temp_db.session_scope() as session:
            session.add(EngagementWatchlistItem(
                person_or_company="Trade Publication",
                profile_or_source_url="https://cbtnews.com/story",
                topic="Speed to lead", priority="high",
                risk_notes="Review only. Do not automate.",
            ))
        with temp_db.session_scope() as session:
            item = session.scalar(select(EngagementWatchlistItem))
            assert item.review_status == "unreviewed"
            assert "Do not automate" in item.risk_notes
