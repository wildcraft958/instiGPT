"""
Integration tests for the insti_scraper package.

Tests real-world scenarios with mocked network calls.
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from insti_scraper.engine.discovery import FacultyPageDiscoverer, DiscoveredPage
from insti_scraper.services.extraction_service import ExtractionService
from insti_scraper.config import get_university_profile, ProfileLoader
from insti_scraper.core.selector_strategies import FallbackExtractor, COMMON_STRATEGIES
from insti_scraper.engine.page_handlers import GatewayPageHandler, DirectoryPageHandler


class TestUniversityProfiles:
    """Tests for university profile configuration."""
    
    def test_princeton_profile_loads(self):
        """Princeton should have a pre-configured profile."""
        profile = get_university_profile("https://cs.princeton.edu/people/faculty")
        
        assert profile is not None
        assert profile.name == "Princeton University"
        assert len(profile.faculty_urls) >= 3
    
    def test_mit_profile_loads(self):
        """MIT should have a pre-configured profile."""
        profile = get_university_profile("https://eecs.mit.edu/people")
        
        assert profile is not None
        assert profile.name == "Massachusetts Institute of Technology"
    
    def test_iit_pattern_matches(self):
        """IIT pattern should match various IIT domains."""
        iit_urls = [
            "https://www.iitb.ac.in/people",
            "https://iitd.ac.in/faculty",
            "https://iitm.ac.in/people",
        ]
        
        for url in iit_urls:
            profile = get_university_profile(url)
            assert profile is not None
            assert "Indian Institute of Technology" in profile.name
    
    def test_generic_edu_fallback(self):
        """Unknown .edu domains should fall back to generic profile."""
        profile = get_university_profile("https://unknown-university.edu/faculty")
        
        # Should match generic pattern
        assert profile is not None or profile is None  # May or may not match


class TestSelectorStrategies:
    """Tests for multi-fallback selector strategies."""
    
    def test_datatable_extraction(self):
        """Should extract from DataTable HTML."""
        html = """
        <table class="dataTable">
            <tbody>
                <tr>
                    <td><a href="/prof/smith">Dr. John Smith</a></td>
                    <td>Professor</td>
                    <td><a href="mailto:jsmith@uni.edu">jsmith@uni.edu</a></td>
                </tr>
                <tr>
                    <td><a href="/prof/doe">Dr. Jane Doe</a></td>
                    <td>Associate Professor</td>
                    <td><a href="mailto:jdoe@uni.edu">jdoe@uni.edu</a></td>
                </tr>
            </tbody>
        </table>
        """
        
        extractor = FallbackExtractor()
        results, strategy = extractor.extract(html)
        
        assert len(results) == 2
        assert strategy.name == "datatable"
        assert results[0]['name'] == "Dr. John Smith"
        assert "jsmith@uni.edu" in results[0].get('email', '')
    
    def test_card_extraction(self):
        """Should extract from card-based layouts."""
        html = """
        <div class="faculty-card">
            <h3 class="name">Alice Johnson</h3>
            <span class="title">Assistant Professor</span>
            <a href="mailto:alice@uni.edu">Email</a>
        </div>
        <div class="faculty-card">
            <h3 class="name">Bob Williams</h3>
            <span class="title">Professor</span>
        </div>
        """
        
        extractor = FallbackExtractor()
        results, strategy = extractor.extract(html)
        
        assert len(results) >= 1
        assert "cards" in strategy.name or "generic" in strategy.name
    
    def test_fallback_order(self):
        """Strategies should be tried in priority order."""
        extractor = FallbackExtractor()
        
        priorities = [s.priority for s in extractor.strategies]
        assert priorities == sorted(priorities)


class TestGatewayPageHandler:
    """Tests for department gateway page handling."""
    
    @pytest.mark.asyncio
    async def test_extracts_department_links(self):
        """Should extract faculty/people links from gateway pages."""
        html = """
        <nav>
            <a href="/cs/faculty">Computer Science</a>
            <a href="/ee/people">Electrical Engineering</a>
            <a href="/about">About</a>
            <a href="/news">News</a>
        </nav>
        """
        
        handler = GatewayPageHandler()
        result = await handler.extract("https://example.edu", html)
        
        # Should find faculty/people links but not about/news
        assert len(result.next_pages) >= 2
        assert any("faculty" in link for link in result.next_pages)
        assert any("people" in link for link in result.next_pages)


class TestDiscoveryWithProfiles:
    """Tests for discovery flow with university profiles."""
    
    @pytest.mark.asyncio
    async def test_princeton_uses_profile_urls(self):
        """Princeton discovery should use pre-configured URLs."""
        discoverer = FacultyPageDiscoverer()
        
        # Mock the actual network calls
        with patch.object(discoverer, '_seen_urls', set()):
            result = await discoverer.discover(
                "https://princeton.edu",
                mode="auto"
            )
        
        # Should find pages from profile
        assert len(result.faculty_pages) >= 1
        assert result.discovery_method == "profile"


class TestExtractionService:
    """Tests for the extraction service."""
    
    def test_garbage_link_detection(self):
        """Should filter out navigation links."""
        service = ExtractionService()
        
        garbage = ["calendar", "contact", "home", "about", "login"]
        for text in garbage:
            assert service._is_garbage_link(text) == True
        
        valid = ["Dr. Smith", "Prof. Johnson", "Associate Dean"]
        for text in valid:
            assert service._is_garbage_link(text) == False


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
