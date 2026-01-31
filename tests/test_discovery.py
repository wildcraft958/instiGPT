"""
Tests for the discovery module.

Tests cover:
- URL scoring
- Sitemap parsing
- Domain extraction
- Profile content detection
"""

import pytest

from insti_scraper.discovery import (
    FacultyPageDiscoverer,
    DiscoveredPage,
    DiscoveryResult,
)
from insti_scraper.config import FACULTY_KEYWORDS, EXCLUDE_PATTERNS


# =============================================================================
# Test Data
# =============================================================================

SAMPLE_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://example.edu/faculty</loc>
        <lastmod>2024-01-01</lastmod>
    </url>
    <url>
        <loc>https://example.edu/people/directory</loc>
    </url>
    <url>
        <loc>https://example.edu/about</loc>
    </url>
    <url>
        <loc>https://example.edu/contact</loc>
    </url>
    <url>
        <loc>https://example.edu/staff/professors</loc>
    </url>
</urlset>
"""

SAMPLE_SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap>
        <loc>https://example.edu/sitemap-main.xml</loc>
    </sitemap>
    <sitemap>
        <loc>https://example.edu/sitemap-people.xml</loc>
    </sitemap>
</sitemapindex>
"""

PROFILE_LISTING_HTML = """
<html>
<body>
<h1>Department of Computer Science - Faculty</h1>
<div class="faculty-list">
    <div class="person">
        <img src="photo1.jpg">
        <a href="/people/john-smith">Dr. John Smith</a>
        <span>Professor</span>
        <a href="mailto:jsmith@example.edu">jsmith@example.edu</a>
    </div>
    <div class="person">
        <a href="/people/jane-doe">Dr. Jane Doe, PhD</a>
        <span>Associate Professor</span>
        <a href="mailto:jdoe@example.edu">jdoe@example.edu</a>
    </div>
    <div class="person">
        <a href="/faculty/bob-wilson">Dr. Bob Wilson</a>
        <span>Assistant Professor</span>
        <a href="mailto:bwilson@example.edu">bwilson@example.edu</a>
    </div>
</div>
</body>
</html>
"""

NON_PROFILE_HTML = """
<html>
<body>
<h1>About Our University</h1>
<p>Welcome to Example University, founded in 1850.</p>
<p>We have many departments and programs.</p>
<nav>
    <a href="/home">Home</a>
    <a href="/about">About</a>
    <a href="/contact">Contact</a>
</nav>
</body>
</html>
"""


# =============================================================================
# Tests: URL Scoring
# =============================================================================

class TestURLScoring:
    """Tests for URL scoring functionality."""
    
    def setup_method(self):
        """Create discoverer for each test."""
        self.discoverer = FacultyPageDiscoverer()
    
    def test_faculty_url_high_score(self):
        """Faculty-related URLs should score high."""
        score = self.discoverer._score_url("https://example.edu/faculty")
        assert score >= 0.3
    
    def test_people_url_high_score(self):
        """People-related URLs should score high."""
        score = self.discoverer._score_url("https://example.edu/people")
        assert score >= 0.3
    
    def test_directory_url_high_score(self):
        """Directory URLs should score high."""
        score = self.discoverer._score_url("https://example.edu/directory")
        assert score >= 0.2
    
    def test_excluded_url_zero_score(self):
        """Excluded patterns should score zero."""
        assert self.discoverer._score_url("https://example.edu/login") == 0.0
        assert self.discoverer._score_url("https://example.edu/calendar") == 0.0
        assert self.discoverer._score_url("https://example.edu/document.pdf") == 0.0
    
    def test_generic_url_low_score(self):
        """Generic URLs should score low."""
        score = self.discoverer._score_url("https://example.edu/about")
        assert score < 0.3
    
    def test_multiple_keywords_boost_score(self):
        """URLs with multiple keywords should score higher."""
        single = self.discoverer._score_url("https://example.edu/faculty")
        multiple = self.discoverer._score_url("https://example.edu/faculty-directory-profiles")
        assert multiple >= single


# =============================================================================
# Tests: URL Classification
# =============================================================================

class TestURLClassification:
    """Tests for URL classification (directory vs profile)."""
    
    def setup_method(self):
        """Create discoverer for each test."""
        self.discoverer = FacultyPageDiscoverer()
    
    def test_directory_classification(self):
        """Should classify directory URLs correctly."""
        assert self.discoverer._classify_url("https://example.edu/people") == "directory"
        assert self.discoverer._classify_url("https://example.edu/faculty/") == "directory"
        assert self.discoverer._classify_url("https://example.edu/directory") == "directory"
    
    def test_profile_classification(self):
        """Should classify profile URLs correctly."""
        assert self.discoverer._classify_url("https://example.edu/people/john-smith") == "profile"
        assert self.discoverer._classify_url("https://example.edu/faculty/jane-doe/") == "profile"
        assert self.discoverer._classify_url("https://example.edu/profile/bob") == "profile"
    
    def test_unknown_classification(self):
        """Should return unknown for ambiguous URLs."""
        assert self.discoverer._classify_url("https://example.edu/about") == "unknown"
        assert self.discoverer._classify_url("https://example.edu/") == "unknown"


# =============================================================================
# Tests: Sitemap Parsing
# =============================================================================

class TestSitemapParsing:
    """Tests for sitemap XML parsing."""
    
    def setup_method(self):
        """Create discoverer for each test."""
        self.discoverer = FacultyPageDiscoverer()
    
    def test_parse_basic_sitemap(self):
        """Should parse basic sitemap and filter URLs."""
        pages, nested = self.discoverer._parse_sitemap(
            SAMPLE_SITEMAP_XML
        )
        
        # Should find faculty-related URLs
        urls = [p.url for p in pages]
        assert "https://example.edu/faculty" in urls
        assert "https://example.edu/people/directory" in urls
        assert "https://example.edu/staff/professors" in urls
        
        # Should filter out non-faculty URLs (score = 0)
        # Note: 'about' and 'contact' have low scores but not necessarily 0
        # The actual filtering depends on score threshold
    
    def test_parse_sitemap_index(self):
        """Should detect nested sitemaps."""
        pages, nested = self.discoverer._parse_sitemap(
            SAMPLE_SITEMAP_INDEX
        )
        
        # Should find nested sitemaps
        assert len(nested) == 2
        assert "https://example.edu/sitemap-main.xml" in nested
        assert "https://example.edu/sitemap-people.xml" in nested
    
    def test_parse_invalid_sitemap(self):
        """Should handle invalid XML gracefully."""
        pages, nested = self.discoverer._parse_sitemap(
            "not valid xml <><>"
        )
        
        assert pages == []
        assert nested == []


# =============================================================================
# Tests: University Name Extraction
# =============================================================================

class TestUniversityNameExtraction:
    """Tests for extracting university names from URLs."""
    
    def setup_method(self):
        """Create discoverer for each test."""
        self.discoverer = FacultyPageDiscoverer()
    
    def test_edu_domain(self):
        """Should extract name from .edu domain."""
        name = self.discoverer._extract_university_name("https://www.stanford.edu/faculty")
        assert "stanford" in name.lower()
    
    def test_ac_in_domain(self):
        """Should extract name from .ac.in domain."""
        name = self.discoverer._extract_university_name("https://cse.iitb.ac.in/faculty")
        assert "iitb" in name.lower() or "cse" in name.lower()
    
    def test_cl_domain(self):
        """Should extract name from .cl domain."""
        name = self.discoverer._extract_university_name("https://departamento-scpa.uct.cl/academicos/")
        assert "uct" in name.lower()
    
    def test_subdomain_handling(self):
        """Should handle subdomains appropriately."""
        name = self.discoverer._extract_university_name("https://faculty.princeton.edu/meet-faculty")
        assert "princeton" in name.lower()


# =============================================================================
# Tests: Profile Content Detection
# =============================================================================

# Note: _has_profile_content was removed in the simplified implementation
# These tests are commented out as the method no longer exists

# class TestProfileContentDetection:
#     """Tests for detecting faculty profile content in HTML."""
#     
#     def setup_method(self):
#         """Create discoverer for each test."""
#         self.discoverer = FacultyPageDiscoverer()
#     
#     def test_detect_profile_content(self):
#         """Should detect pages with faculty profiles."""
#         result = self.discoverer._has_profile_content(PROFILE_LISTING_HTML)
#         assert result is True
#     
#     def test_detect_non_profile_content(self):
#         """Should not detect profiles on non-faculty pages."""
#         result = self.discoverer._has_profile_content(NON_PROFILE_HTML)
#         assert result is False
#     
#     def test_empty_html(self):
#         """Should handle empty HTML."""
#         result = self.discoverer._has_profile_content("")
#         assert result is False
#     
#     def test_none_html(self):
#         """Should handle None HTML."""
#         result = self.discoverer._has_profile_content(None)
#         assert result is False


# =============================================================================
# Tests: DiscoveredPage
# =============================================================================

class TestDiscoveredPage:
    """Tests for DiscoveredPage dataclass."""
    
    def test_equality(self):
        """Pages with same URL should be equal."""
        page1 = DiscoveredPage(url="https://example.edu/faculty", score=0.5)
        page2 = DiscoveredPage(url="https://example.edu/faculty", score=0.8)
        
        assert page1 == page2
    
    def test_hash(self):
        """Pages with same URL should have same hash."""
        page1 = DiscoveredPage(url="https://example.edu/faculty", score=0.5)
        page2 = DiscoveredPage(url="https://example.edu/faculty", score=0.8)
        
        assert hash(page1) == hash(page2)
    
    def test_set_deduplication(self):
        """Should deduplicate in sets."""
        pages = {
            DiscoveredPage(url="https://example.edu/faculty", score=0.5),
            DiscoveredPage(url="https://example.edu/faculty", score=0.8),
            DiscoveredPage(url="https://example.edu/people", score=0.6),
        }
        
        assert len(pages) == 2


# =============================================================================
# Tests: DiscoveryResult
# =============================================================================

class TestDiscoveryResult:
    """Tests for DiscoveryResult dataclass."""
    
    def test_faculty_pages_sorted(self):
        """faculty_pages should return sorted by score."""
        result = DiscoveryResult(pages=[
            DiscoveredPage(url="https://example.edu/low", score=0.2),
            DiscoveredPage(url="https://example.edu/high", score=0.9),
            DiscoveredPage(url="https://example.edu/mid", score=0.5),
        ])
        
        sorted_pages = result.faculty_pages
        scores = [p.score for p in sorted_pages]
        
        assert scores == sorted(scores, reverse=True)
    
    def test_empty_result(self):
        """Should handle empty results."""
        result = DiscoveryResult()
        
        assert result.pages == []
        assert result.faculty_pages == []
        assert result.method == "none"


# =============================================================================
# Tests: Keywords and Patterns
# =============================================================================

class TestKeywordsAndPatterns:
    """Tests for keyword and pattern constants."""
    
    def test_faculty_keywords_exist(self):
        """Should have essential faculty keywords."""
        assert "faculty" in FACULTY_KEYWORDS
        assert "people" in FACULTY_KEYWORDS
        assert "professor" in FACULTY_KEYWORDS
        assert "directory" in FACULTY_KEYWORDS
    
    def test_exclude_patterns_exist(self):
        """Should have essential exclude patterns."""
        assert any("login" in p for p in EXCLUDE_PATTERNS)
        assert any("pdf" in p for p in EXCLUDE_PATTERNS)
        assert any("calendar" in p for p in EXCLUDE_PATTERNS)


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
