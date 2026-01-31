"""
Faculty page discovery using sitemap, search, and deep crawling.

Discovers faculty directory pages from university websites.
"""

import re
import xml.etree.ElementTree as ET
import logging
from typing import List, Set
from urllib.parse import urlparse

import httpx

from .config import FACULTY_KEYWORDS, EXCLUDE_PATTERNS
from .models import DiscoveredPage, DiscoveryResult

logger = logging.getLogger(__name__)


class FacultyPageDiscoverer:
    """
    Discovers faculty pages from university websites.
    
    Uses tiered approach:
    1. DuckDuckGo search (fast, accurate)
    2. Sitemap parsing (comprehensive)
    3. Deep crawling (thorough but slow)
    """
    
    def __init__(self, max_depth: int = 3, max_pages: int = 50, timeout: float = 30.0):
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.timeout = timeout
        self._seen_urls: Set[str] = set()
    
    async def discover(self, start_url: str, mode: str = "auto") -> DiscoveryResult:
        """
        Discover faculty pages.
        
        Args:
            start_url: Starting URL (homepage or any page)
            mode: 'search', 'sitemap', 'deep', or 'auto'
        
        Returns:
            DiscoveryResult with discovered pages
        """
        logger.info(f"🔍 Discovering faculty pages: {start_url}")
        
        result = DiscoveryResult()
        self._seen_urls.clear()
        
        # Tier 1: DuckDuckGo search
        if mode in ("search", "auto"):
            search_pages = await self._try_search(start_url)
            if search_pages:
                result.pages.extend(search_pages)
                result.method = "search"
                if mode == "search":
                    return result
        
        # Tier 2: Sitemap
        if mode in ("sitemap", "auto"):
            sitemap_pages = await self._try_sitemap(start_url)
            if sitemap_pages:
                result.pages.extend(sitemap_pages)
                result.method = result.method or "sitemap"
                if len(sitemap_pages) >= 10 or mode == "sitemap":
                    return result
        
        # Tier 3: Deep crawl
        if mode in ("deep", "auto") and len(result.pages) < 5:
            deep_pages = await self._try_deep_crawl(start_url)
            result.pages.extend(deep_pages)
            result.method = result.method or "deep_crawl"
        
        # Deduplicate and sort
        result.pages = list(set(result.pages))
        result.pages.sort(key=lambda p: p.score, reverse=True)
        
        logger.info(f"📊 Found {len(result.pages)} faculty pages")
        return result
    
    async def _try_search(self, url: str) -> List[DiscoveredPage]:
        """Search using DuckDuckGo (Enhanced version)."""
        try:
            # Use the enhanced DuckDuckGo discovery service
            from .duckduckgo_discovery import DuckDuckGoDiscovery
            
            name = self._extract_university_name(url)
            
            logger.info(f"🔎 Enhanced DuckDuckGo search: {name}")
            
            ddg = DuckDuckGoDiscovery(max_results_per_query=8)
            pages = await ddg.discover(name, url, include_departments=True)
            
            # Boost scores for search results
            for page in pages:
                page.score += 0.3
            
            return pages
            
        except ImportError:
            # Fallback to basic ddgs if enhanced version fails
            return await self._try_search_basic(url)
        except Exception as e:
            logger.debug(f"Enhanced search failed, trying basic: {e}")
            return await self._try_search_basic(url)
    
    async def _try_search_basic(self, url: str) -> List[DiscoveredPage]:
        """Basic DuckDuckGo search (fallback)."""
        try:
            from ddgs import DDGS
            
            name = self._extract_university_name(url)
            query = f"{name} faculty directory people"
            
            logger.info(f"🔎 Searching: {query}")
            
            pages = []
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=10))
                
                parsed = urlparse(url)
                domain = parsed.netloc.replace("www.", "")
                
                for r in results:
                    result_url = r.get("href", "")
                    if domain in result_url:
                        score = self._score_url(result_url)
                        if score > 0:
                            pages.append(DiscoveredPage(
                                url=result_url,
                                score=score + 0.3,  # Boost for search results
                                page_type=self._classify_url(result_url),
                                source="search"
                            ))
            
            return pages
            
        except ImportError:
            logger.debug("ddgs not available")
            return []
        except Exception as e:
            logger.debug(f"Search failed: {e}")
            return []
    
    async def _try_sitemap(self, url: str) -> List[DiscoveredPage]:
        """Parse sitemap.xml for faculty URLs."""
        pages = []
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        sitemap_urls = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
        ]
        
        # Check robots.txt for sitemaps
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/robots.txt")
                if response.status_code == 200:
                    for line in response.text.split("\n"):
                        if line.lower().startswith("sitemap:"):
                            sitemap_urls.append(line.split(":", 1)[1].strip())
        except Exception:
            pass
        
        processed = set()
        
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for sitemap_url in sitemap_urls[:10]:  # Limit sitemap depth
                if sitemap_url in processed:
                    continue
                processed.add(sitemap_url)
                
                try:
                    response = await client.get(sitemap_url)
                    if response.status_code == 200 and "xml" in response.headers.get("content-type", ""):
                        found, nested = self._parse_sitemap(response.text)
                        pages.extend(found)
                        sitemap_urls.extend(nested)
                except Exception:
                    continue
        
        return pages
    
    def _parse_sitemap(self, xml_content: str) -> tuple:
        """Parse sitemap XML. Returns (pages, nested_sitemaps)."""
        pages = []
        nested = []
        
        try:
            xml_content = re.sub(r'\sxmlns="[^"]+"', '', xml_content)
            root = ET.fromstring(xml_content)
            
            # Nested sitemaps
            for sitemap in root.findall(".//sitemap"):
                loc = sitemap.find("loc")
                if loc is not None and loc.text:
                    nested.append(loc.text.strip())
            
            # URLs
            for url_elem in root.findall(".//url"):
                loc = url_elem.find("loc")
                if loc is not None and loc.text:
                    url = loc.text.strip()
                    score = self._score_url(url)
                    if score > 0:
                        pages.append(DiscoveredPage(
                            url=url,
                            score=score,
                            page_type=self._classify_url(url),
                            source="sitemap"
                        ))
        except ET.ParseError:
            pass
        
        return pages, nested
    
    async def _try_deep_crawl(self, start_url: str) -> List[DiscoveredPage]:
        """Deep crawl using Crawl4AI."""
        pages = []
        
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
            from crawl4ai.deep_crawling import BestFirstCrawlingStrategy
            from crawl4ai.deep_crawling.filters import FilterChain, DomainFilter
            from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer
            
            parsed = urlparse(start_url)
            domain_parts = parsed.netloc.split('.')
            base_domain = '.'.join(domain_parts[-2:]) if len(domain_parts) >= 2 else parsed.netloc
            
            strategy = BestFirstCrawlingStrategy(
                max_depth=self.max_depth,
                include_external=True,
                url_scorer=KeywordRelevanceScorer(keywords=FACULTY_KEYWORDS, weight=0.7),
                filter_chain=FilterChain([DomainFilter(allowed_domains=[base_domain])]),
                max_pages=self.max_pages
            )
            
            config = CrawlerRunConfig(deep_crawl_strategy=strategy, stream=True)
            browser_config = BrowserConfig(headless=True, verbose=False)
            
            async with AsyncWebCrawler(config=browser_config) as crawler:
                try:
                    async for result in await crawler.arun(start_url, config=config):
                        if result.url not in self._seen_urls:
                            score = self._score_url(result.url)
                            if score > 0:
                                pages.append(DiscoveredPage(
                                    url=result.url,
                                    score=score,
                                    page_type=self._classify_url(result.url),
                                    source="deep_crawl"
                                ))
                                self._seen_urls.add(result.url)
                except Exception as e:
                    if "ContextVar" not in str(e):
                        logger.debug(f"Crawl stream error: {e}")
                        
        except ImportError:
            logger.warning("Deep crawl requires crawl4ai")
        except Exception as e:
            logger.error(f"Deep crawl error: {e}")
        
        return pages
    
    def _score_url(self, url: str) -> float:
        """Score URL for faculty relevance."""
        url_lower = url.lower()
        score = 0.0
        
        # Check exclude patterns
        for pattern in EXCLUDE_PATTERNS:
            if re.search(pattern, url_lower):
                return 0.0
        
        # Faculty keywords
        for keyword in FACULTY_KEYWORDS:
            if keyword in url_lower:
                score += 0.2
        
        # Strong patterns
        if "/people" in url_lower or "/faculty" in url_lower:
            score += 0.3
        if "/directory" in url_lower:
            score += 0.2
        
        return min(score, 1.0)
    
    def _classify_url(self, url: str) -> str:
        """Classify URL type."""
        url_lower = url.lower()
        
        # Individual profile
        if re.search(r"/(?:people|faculty|profile)/[^/]+/?$", url_lower):
            return "profile"
        
        # Directory listing
        if any(url_lower.endswith(p) for p in ["/people", "/people/", "/faculty", "/faculty/", "/directory"]):
            return "directory"
        
        return "unknown"
    
    def _extract_university_name(self, url: str) -> str:
        """Extract university name from URL."""
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        
        # Remove TLDs
        for tld in [".edu", ".ac.in", ".ac.uk", ".org", ".com"]:
            domain = domain.replace(tld, "")
        
        return " ".join(p.title() for p in domain.split("."))


async def discover_faculty_pages(url: str, mode: str = "auto") -> DiscoveryResult:
    """Convenience function for discovery."""
    discoverer = FacultyPageDiscoverer()
    return await discoverer.discover(url, mode=mode)
