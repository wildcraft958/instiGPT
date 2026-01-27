from typing import List
from insti_scraper.discovery.discovery import FacultyPageDiscoverer, DiscoveredPage
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)

class DiscoveryService:
    def __init__(self):
        self.discoverer = FacultyPageDiscoverer()

    async def discover_faculty_pages(self, start_url: str, max_depth: int = 3, max_pages: int = 30) -> List[DiscoveredPage]:
        """
        Uses the robust insti_scraper.discovery implementation.
        """
        # Update discoverer config if needed
        self.discoverer.max_depth = max_depth
        self.discoverer.max_pages = max_pages
        
        result = await self.discoverer.discover(start_url, mode="auto")
        
        # Return list of DiscoveredPage objects
        # We prioritize directories but main.py processes all returned pages
        return result.faculty_pages

    def _extract_university_name(self, url: str) -> str:
        """Extract university name from URL."""
        # Delegating to the implementation in FacultyPageDiscoverer (need to instantiate or static)
        # It's an instance method in FacultyPageDiscoverer, so we can use self.discoverer
        return self.discoverer._extract_university_name(url)
