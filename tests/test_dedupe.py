from fcie.utils.dedupe import (
    CandidateRecord,
    dedupe_batch,
    find_duplicate,
    merge_discovery_metadata,
    title_similarity,
)

LONG_A = " ".join(
    f"Local businesses lose inbound demand when nobody answers the phone segment {i}."
    for i in range(40)
)
LONG_B = LONG_A + " One extra closing sentence that does not change the document."


class TestTitleSimilarity:
    def test_identical_titles(self):
        assert title_similarity("AI agents for dealerships", "AI agents for dealerships") == 100.0

    def test_ignores_site_suffix(self):
        score = title_similarity(
            "Speed to lead is a staffing problem | CBT News",
            "Speed to lead is a staffing problem",
        )
        assert score >= 92

    def test_short_titles_never_match(self):
        assert title_similarity("About", "About") == 0.0
        assert title_similarity("Pricing", "Pricing") == 0.0

    def test_different_titles(self):
        score = title_similarity(
            "AI agents for automotive dealerships",
            "Quantum computing breakthroughs in 2026",
        )
        assert score < 92

    def test_handles_none(self):
        assert title_similarity(None, "x") == 0.0


class TestFindDuplicate:
    def test_detects_canonical_url_match(self):
        candidates = [CandidateRecord(id=1, canonical_url="https://e.com/article")]
        verdict = find_duplicate("https://www.e.com/article/?utm_source=x", "text", "Title", candidates)
        assert verdict.is_duplicate
        assert verdict.method == "canonical_url"
        assert verdict.matched_id == 1

    def test_detects_content_hash_match(self):
        from fcie.utils.hashing import content_hash

        text = "The same body text discovered at two different addresses entirely."
        candidates = [CandidateRecord(id=7, canonical_url="https://a.com/x",
                                      content_hash=content_hash(text))]
        verdict = find_duplicate("https://b.com/y", text, "Different title here", candidates)
        assert verdict.is_duplicate
        assert verdict.method == "content_hash"

    def test_detects_title_match(self):
        candidates = [CandidateRecord(
            id=3, canonical_url="https://a.com/1",
            title="Why local businesses miss after-hours leads",
        )]
        verdict = find_duplicate(
            "https://b.com/2", "different body text entirely here",
            "Why local businesses miss after-hours leads | Trade Weekly", candidates,
        )
        assert verdict.is_duplicate
        assert verdict.method == "title"

    def test_detects_body_near_duplicate(self):
        candidates = [CandidateRecord(id=9, canonical_url="https://a.com/1",
                                      title="Original headline about answering calls",
                                      cleaned_text=LONG_A)]
        verdict = find_duplicate("https://syndicated.com/1", LONG_B,
                                 "A completely unrelated headline string", candidates)
        assert verdict.is_duplicate
        assert verdict.method == "body"

    def test_unique_document_is_not_duplicate(self):
        candidates = [CandidateRecord(id=1, canonical_url="https://a.com/1",
                                      title="Something about HVAC scheduling software",
                                      cleaned_text="HVAC dispatch scheduling content here.")]
        verdict = find_duplicate(
            "https://b.com/2",
            "An entirely different article about medspa injectables pricing trends.",
            "Medspa injectables pricing in 2026", candidates,
        )
        assert not verdict.is_duplicate

    def test_no_candidates(self):
        assert not find_duplicate("https://a.com/1", "text", "Title", [])

    def test_short_documents_skip_body_comparison(self):
        candidates = [CandidateRecord(id=1, canonical_url="https://a.com/1",
                                      title="Short one", cleaned_text="tiny body")]
        assert not find_duplicate("https://b.com/2", "tiny body", "Short two", candidates)


class TestMergeMetadata:
    def test_records_new_query_without_losing_old(self):
        meta = {"discovered_by_queries": ["Eric Rea"]}
        merged = merge_discovery_metadata(meta, "Podium CEO", "web_search", "https://e.com/a")
        assert merged["discovered_by_queries"] == ["Eric Rea", "Podium CEO"]
        assert merged["rediscovery_count"] == 1

    def test_does_not_duplicate_the_same_query(self):
        meta = {"discovered_by_queries": ["Eric Rea"]}
        merged = merge_discovery_metadata(meta, "Eric Rea")
        assert merged["discovered_by_queries"] == ["Eric Rea"]

    def test_tracks_channels_and_alternate_urls(self):
        merged = merge_discovery_metadata({}, "q", "rss", "https://www.e.com/a/")
        assert merged["discovered_by_channels"] == ["rss"]
        assert merged["alternate_urls"] == ["https://e.com/a"]

    def test_increments_across_calls(self):
        meta = merge_discovery_metadata({}, "a")
        meta = merge_discovery_metadata(meta, "b")
        assert meta["rediscovery_count"] == 2


class TestDedupeBatch:
    def test_collapses_same_url_from_multiple_queries(self):
        records = [
            {"canonical_url": "https://e.com/a", "title": "Article about missed calls", "cleaned_text": "x"},
            {"canonical_url": "https://www.e.com/a/?utm_source=q", "title": "Article about missed calls", "cleaned_text": "x"},
            {"canonical_url": "https://e.com/b", "title": "A completely separate piece", "cleaned_text": "y"},
        ]
        unique, duplicates = dedupe_batch(records)
        assert len(unique) == 2
        assert len(duplicates) == 1
        assert duplicates[0]["_duplicate_method"] == "canonical_url"

    def test_empty_batch(self):
        unique, duplicates = dedupe_batch([])
        assert unique == [] and duplicates == []
