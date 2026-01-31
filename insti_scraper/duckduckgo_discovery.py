"""
Specialized DuckDuckGo-based discovery service.

Enhanced search strategies for finding faculty pages with
better filtering and ranking.
"""

import logging
import re
from typing import List, Optional, Set
from urllib.parse import urlparse

from ddgs import DDGS

from .models import DiscoveredPage
from .config import FACULTY_KEYWORDS

logger = logging.getLogger(__name__)


class DuckDuckGoDiscovery:
    """
    Advanced DuckDuckGo search for faculty page discovery.
    
    Features:
    - Multi-query strategy for comprehensive results
    - Domain-aware filtering
    - Result ranking and deduplication
    - Fallback queries for difficult sites
    """
    
    def __init__(self, max_results_per_query: int = 10):
        """
        Initialize DuckDuckGo discovery.
        
        Args:
            max_results_per_query: Max results to fetch per search query
        """
        self.max_results_per_query = max_results_per_query
    
    async def discover(
        self,
        university_name: str,
        homepage_url: str = None,
        include_departments: bool = True
    ) -> List[DiscoveredPage]:
        """
        Discover faculty pages using DuckDuckGo search.
        
        Args:
            university_name: University name (e.g., "MIT", "Stanford University")
            homepage_url: Homepage URL for domain filtering (optional)
            include_departments: Also search for department pages
        
        Returns:
            List of discovered pages sorted by relevance
        """
        logger.info(f"🔍 DuckDuckGo search: {university_name}")
        
        # Extract domain for filtering
        domain = self._extract_domain(homepage_url) if homepage_url else None
        
        # Generate search queries
        queries = self._generate_queries(university_name, include_departments)
        
        # Execute searches
        all_pages = []
        seen_urls = set()
        
        for query in queries:
            pages = await self._search_query(query, domain, seen_urls)
            all_pages.extend(pages)
            logger.debug(f"   Query '{query}': {len(pages)} results")
        
        # Rank and deduplicate
        ranked = self._rank_results(all_pages, university_name)
        
        logger.info(f"   ✅ Found {len(ranked)} unique faculty pages")
        return ranked
    
    def _generate_queries(
        self,
        university_name: str,
        include_departments: bool
    ) -> List[str]:
        """
        Generate search queries for comprehensive coverage.
        
        Returns:
            List of search query strings
        """
        queries = [
            f"{university_name} faculty directory",
            f"{university_name} people directory",
            f"{university_name} academic staff list",
            f"{university_name} faculty profiles",
        ]
        
        if include_departments:
            queries.extend([
                f"{university_name} departments list",
                f"{university_name} schools faculties",
                f"{university_name} department faculty",
            ])
        
        # Add variations for different naming patterns
        queries.extend([
            f"{university_name} professors list",
            f"{university_name} researchers directory",
            f"site:{self._extract_domain(university_name)} faculty",
        ])
        
        return queries
    
    async def _search_query(
        self,
        query: str,
        target_domain: Optional[str],
        seen_urls: Set[str]
    ) -> List[DiscoveredPage]:
        """
        Execute a single search query.
        
        Args:
            query: Search query string
            target_domain: Target domain for filtering (optional)
            seen_urls: Set of already seen URLs for deduplication
        
        Returns:
            List of discovered pages
        """
        pages = []
        
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(
                    query,
                    max_results=self.max_results_per_query
                ))
            
            for result in results:
                url = result.get('href', '').strip()
                
                # Skip if already seen
                if url in seen_urls:
                    continue
                
                # Skip PDFs and other non-HTML files
                if url.endswith(('.pdf', '.doc', '.docx', '.ppt', '.xls')):
                    continue
                
                # Domain filtering
                if target_domain:
                    result_domain = self._extract_domain(url)
                    if target_domain not in result_domain:
                        continue
                
                # Score the result
                score = self._score_result(url, result.get('title', ''), result.get('body', ''))
                
                if score > 0:
                    pages.append(DiscoveredPage(
                        url=url,
                        score=score,
                        page_type=self._classify_url(url),
                        source="duckduckgo"
                    ))
                    seen_urls.add(url)
        
        except Exception as e:
            logger.warning(f"Search failed for query '{query}': {e}")
        
        return pages
    
    def _score_result(self, url: str, title: str, snippet: str) -> float:
        """
        Score a search result for relevance.
        
        Args:
            url: Result URL
            title: Page title
            snippet: Text snippet from search result
        
        Returns:
            Relevance score (0.0 to 1.0)
        """
        score = 0.0
        
        url_lower = url.lower()
        title_lower = title.lower()
        snippet_lower = snippet.lower()
        
        # URL path scoring
        path_keywords = {
            '/faculty': 0.4,
            '/people': 0.4,
            '/directory': 0.3,
            '/staff': 0.3,
            '/profiles': 0.3,
            '/departments': 0.25,
            '/academic': 0.2,
        }
        
        for keyword, points in path_keywords.items():
            if keyword in url_lower:
                score += points
        
        # Title scoring
        title_keywords = [
            'faculty', 'directory', 'people', 'staff',
            'professors', 'academic', 'researchers'
        ]
        
        for keyword in title_keywords:
            if keyword in title_lower:
                score += 0.1
        
        # Snippet scoring
        for keyword in FACULTY_KEYWORDS:
            if keyword in snippet_lower:
                score += 0.05
        
        # Penalties
        negative_terms = [
            'login', 'news', 'events', 'about us', 'contact',
            'alumni', 'admissions', 'apply', 'careers'
        ]
        
        for term in negative_terms:
            if term in url_lower or term in title_lower:
                score -= 0.2
        
        # Normalize
        return max(0.0, min(1.0, score))
    
    def _classify_url(self, url: str) -> str:
        """
        Classify URL type.
        
        Returns:
            'directory', 'profile', 'department', or 'unknown'
        """
        url_lower = url.lower()
        path = urlparse(url).path.lower()
        
        # Individual profile
        if re.search(r'/(people|faculty|staff|profile)/[^/]+/?$', path):
            return 'profile'
        
        # Directory listing
        if any(term in path for term in ['/directory', '/people', '/faculty', '/staff']):
            if path.endswith(('/directory', '/directory/', '/people', '/people/', '/faculty', '/faculty/')):
                return 'directory'
        
        # Department page
        if any(term in path for term in ['/department', '/school', '/college']):
            return 'department'
        
        return 'unknown'
    
    def _rank_results(
        self,
        pages: List[DiscoveredPage],
        university_name: str
    ) -> List[DiscoveredPage]:
        """
        Rank and deduplicate results.
        
        Args:
            pages: List of discovered pages
            university_name: University name for context
        
        Returns:
            Ranked and deduplicated pages
        """
        # Deduplicate by URL
        unique_pages = {page.url: page for page in pages}
        pages = list(unique_pages.values())
        
        # Boost directory pages over profiles
        for page in pages:
            if page.page_type == 'directory':
                page.score += 0.2
            elif page.page_type == 'profile':
                page.score -= 0.1
        
        # Sort by score (descending)
        pages.sort(key=lambda p: p.score, reverse=True)
        
        return pages
    
    def _extract_domain(self, url_or_name: str) -> str:
        """
        Extract domain from URL or university name.
        
        Args:
            url_or_name: URL or university name
        
        Returns:
            Domain string (e.g., "mit.edu")
        """
        if not url_or_name:
            return ""
        
        # If it's a URL
        if url_or_name.startswith('http'):
            parsed = urlparse(url_or_name)
            domain = parsed.netloc.replace('www.', '')
            return domain
        
        # If it's a name, try to guess the domain
        name_lower = url_or_name.lower().replace(' ', '').replace('university', '')
        
        # Common patterns
        patterns = [
            f"{name_lower}.edu",
            f"{name_lower}.ac.uk",
            f"{name_lower}.ac.in",
        ]
        
        return patterns[0] if patterns else name_lower


async def discover_with_duckduckgo(
    university_name: str,
    homepage_url: str = None,
    include_departments: bool = True
) -> List[DiscoveredPage]:
    """
    Convenience function for DuckDuckGo discovery.
    
    Args:
        university_name: University name
        homepage_url: Homepage URL (optional)
        include_departments: Include department searches
    
    Returns:
        List of discovered pages
    """
    discoverer = DuckDuckGoDiscovery()
    return await discoverer.discover(university_name, homepage_url, include_departments)
