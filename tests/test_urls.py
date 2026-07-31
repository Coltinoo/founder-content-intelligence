from fcie.utils.urls import (
    canonicalize,
    domain_of,
    is_allowed,
    is_http_url,
    normalize_url,
    registrable_domain,
    same_site,
    youtube_video_id,
)


class TestNormalizeUrl:
    def test_strips_www_and_upgrades_scheme(self):
        assert normalize_url("http://www.podium.com/about/") == "https://podium.com/about"

    def test_removes_tracking_parameters(self):
        url = "https://example.com/post?utm_source=twitter&utm_campaign=x&id=42&fbclid=abc"
        assert normalize_url(url) == "https://example.com/post?id=42"

    def test_sorts_remaining_parameters(self):
        assert normalize_url("https://e.com/a?b=2&a=1") == "https://e.com/a?a=1&b=2"

    def test_drops_fragment(self):
        assert normalize_url("https://e.com/page#section-3") == "https://e.com/page"

    def test_strips_trailing_slash_but_keeps_root(self):
        assert normalize_url("https://e.com/a/b/") == "https://e.com/a/b"
        assert normalize_url("https://e.com/") == "https://e.com/"

    def test_removes_index_files(self):
        assert normalize_url("https://e.com/docs/index.html") == "https://e.com/docs"

    def test_strips_default_ports(self):
        assert normalize_url("https://e.com:443/a") == "https://e.com/a"
        assert normalize_url("http://e.com:80/a") == "https://e.com/a"

    def test_keeps_non_default_port(self):
        assert normalize_url("https://e.com:8443/a") == "https://e.com:8443/a"

    def test_bare_host_gets_scheme(self):
        assert normalize_url("podium.com/about") == "https://podium.com/about"

    def test_http_and_https_collapse_to_one_identity(self):
        assert normalize_url("http://e.com/a") == normalize_url("https://e.com/a")

    def test_empty_and_none(self):
        assert normalize_url("") == ""
        assert normalize_url(None) == ""
        assert normalize_url("   ") == ""

    def test_same_article_via_different_queries_normalises_identically(self):
        a = "https://www.example.com/story?utm_source=google&utm_medium=cpc"
        b = "http://example.com/story/"
        assert normalize_url(a) == normalize_url(b)


class TestDomain:
    def test_domain_of_strips_www(self):
        assert domain_of("https://www.podium.com/a") == "podium.com"

    def test_domain_of_handles_subdomain(self):
        assert domain_of("https://job-boards.greenhouse.io/podium") == "job-boards.greenhouse.io"

    def test_registrable_domain(self):
        assert registrable_domain("https://job-boards.greenhouse.io/x") == "greenhouse.io"
        assert registrable_domain("https://news.bbc.co.uk/x") == "bbc.co.uk"

    def test_same_site(self):
        assert same_site("https://a.example.com/1", "https://b.example.com/2")
        assert not same_site("https://example.com", "https://other.com")

    def test_domain_of_invalid(self):
        assert domain_of("") == ""
        assert domain_of(None) == ""


class TestAllowlist:
    allowed = {"podium.com", "job-boards.greenhouse.io"}
    blocked = {"linkedin.com", "x.com"}

    def test_allows_exact_and_subdomain(self):
        assert is_allowed("https://podium.com/about", self.allowed, self.blocked)
        assert is_allowed("https://www.podium.com/about", self.allowed, self.blocked)
        assert is_allowed("https://blog.podium.com/x", self.allowed, self.blocked)

    def test_rejects_unlisted_domain(self):
        assert not is_allowed("https://example.com/x", self.allowed, self.blocked)

    def test_blocklist_overrides_allowlist(self):
        assert not is_allowed(
            "https://linkedin.com/in/someone", self.allowed | {"linkedin.com"}, self.blocked
        )

    def test_blocklist_covers_subdomains(self):
        assert not is_allowed("https://www.linkedin.com/feed", self.allowed, self.blocked)


class TestCanonicalize:
    def test_prefers_same_host_declared_canonical(self):
        result = canonicalize("https://e.com/a?utm_source=x", "https://e.com/canonical-a")
        assert result == "https://e.com/canonical-a"

    def test_ignores_cross_host_canonical(self):
        result = canonicalize("https://e.com/a", "https://evil.com/steal")
        assert result == "https://e.com/a"

    def test_no_declared_canonical(self):
        assert canonicalize("https://e.com/a/") == "https://e.com/a"


class TestMisc:
    def test_is_http_url(self):
        assert is_http_url("https://e.com")
        assert is_http_url("e.com")
        assert not is_http_url("mailto:a@b.com")
        assert not is_http_url(None)

    def test_youtube_ids(self):
        assert youtube_video_id("https://www.youtube.com/watch?v=abc123XYZ_-") == "abc123XYZ_-"
        assert youtube_video_id("https://youtu.be/abc123XYZ_-") == "abc123XYZ_-"
        assert youtube_video_id("https://www.youtube.com/shorts/abc123XYZ_-") == "abc123XYZ_-"
        assert youtube_video_id("https://www.youtube.com/embed/abc123XYZ_-") == "abc123XYZ_-"
        assert youtube_video_id("https://example.com/watch?v=x") is None
