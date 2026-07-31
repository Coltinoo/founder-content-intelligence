from fcie.utils.hashing import (
    content_hash,
    jaccard,
    normalize_for_hash,
    shingles,
    short_hash,
    slugify,
    text_similarity,
)


class TestNormalizeForHash:
    def test_collapses_whitespace_and_case(self):
        assert normalize_for_hash("Hello   World\n\n") == normalize_for_hash("hello world")

    def test_normalises_smart_quotes(self):
        assert normalize_for_hash("It's a “test”") == normalize_for_hash('It’s a "test"')

    def test_strips_punctuation(self):
        assert normalize_for_hash("A, B. C!") == "a b c"

    def test_removes_boilerplate(self):
        text = "Accept all cookies. Real content here about AI agents."
        assert "cookies" not in normalize_for_hash(text)
        assert "real content here" in normalize_for_hash(text)

    def test_handles_none_and_empty(self):
        assert normalize_for_hash(None) == ""
        assert normalize_for_hash("") == ""


class TestContentHash:
    def test_is_deterministic(self):
        assert content_hash("some text") == content_hash("some text")

    def test_is_stable_across_formatting(self):
        assert content_hash("Hello  World.") == content_hash("hello world")

    def test_differs_for_different_content(self):
        assert content_hash("a real article") != content_hash("a different article")

    def test_length_is_sha256(self):
        assert len(content_hash("x")) == 64

    def test_short_hash_length(self):
        assert len(short_hash("x", 12)) == 12

    def test_empty_text_hashes_consistently(self):
        assert content_hash("") == content_hash(None)


class TestSimilarity:
    def test_identical_text_is_one(self):
        text = " ".join(f"word{i}" for i in range(50))
        assert text_similarity(text, text) == 1.0

    def test_unrelated_text_is_low(self):
        a = "local businesses miss inbound calls after hours every single evening"
        b = "quantum computing hardware roadmaps for superconducting qubit arrays"
        assert text_similarity(a, b) < 0.1

    def test_near_duplicate_is_high(self):
        base = " ".join(f"sentence part {i}" for i in range(60))
        modified = base + " with a short additional clause appended at the end"
        assert text_similarity(base, modified) > 0.8

    def test_jaccard_empty_sets(self):
        assert jaccard(set(), set()) == 0.0
        assert jaccard({"a"}, set()) == 0.0

    def test_shingles_short_text(self):
        assert shingles("two words", 5) == {"two words"}
        assert shingles("", 5) == set()


class TestSlugify:
    def test_basic(self):
        assert slugify("Missed After-Hours Leads!") == "missed-after-hours-leads"

    def test_empty_becomes_untitled(self):
        assert slugify("") == "untitled"
        assert slugify("!!!") == "untitled"

    def test_truncates(self):
        assert len(slugify("word " * 60, max_length=20)) <= 20
