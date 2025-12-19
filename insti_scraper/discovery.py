"""
Faculty page discovery using sitemap and deep crawling.

This module provides intelligent URL discovery for faculty pages
from any university URL using a tiered approach:
1. Sitemap discovery (fastest, 0 API calls)
2. Deep crawling with keyword scoring (thorough, 0 API calls)
"""
import asyncio
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

import httpx

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig
from crawl4ai.deep_crawling import BestFirstCrawlingStrategy
from crawl4ai.deep_crawling.filters import FilterChain, URLPatternFilter
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer

from .logger import logger


# Keywords that indicate faculty-related content
FACULTY_KEYWORDS = [
    "faculty", "people", "staff", "professor", "directory",
    "profiles", "team", "members", "academic", "researchers",
    "instructor", "lecturer", "scholar", "expert", "scientist"
]

# URL patterns that likely lead to faculty pages
FACULTY_URL_PATTERNS = [
    "*faculty*", "*people*", "*staff*", "*professor*",
    "*directory*", "*profiles*", "*our-team*", "*researchers*",
    "*academics*", "*about-us*", "*meet-*"
]

# Patterns to exclude (non-faculty pages)
EXCLUDE_PATTERNS = [
    "*login*", "*search*", "*calendar*", "*events*", "*news*",
    "*contact*", "*apply*", "*admission*", "*.pdf", "*.jpg", "*.png"
]


@dataclass
class DiscoveredPage:
    """Represents a discovered faculty-related page."""
    url: str
    score: float = 0.0
    page_type: str = "unknown"  # 'directory', 'profile', 'unknown'
    source: str = "unknown"  # 'sitemap', 'deep_crawl'
    
    def __hash__(self):
        return hash(self.url)
    
    def __eq__(self, other):
        return self.url == other.url


@dataclass
class DiscoveryResult:
    """Result of faculty page discovery."""
    pages: List[DiscoveredPage] = field(default_factory=list)
    discovery_method: str = "none"
    sitemap_found: bool = False
    pages_crawled: int = 0
    
    @property
    def faculty_pages(self) -> List[DiscoveredPage]:
        """Get pages most likely to be faculty directories."""
        return sorted(self.pages, key=lambda p: p.score, reverse=True)


class FacultyPageDiscoverer:
    """
    Discovers faculty-related pages from any university URL.
    
    Uses a tiered approach:
    1. Try sitemap.xml first (fastest)
    2. Fall back to deep crawling with keyword scoring
    """
    
    def __init__(
        self, 
        max_depth: int = 3, 
        max_pages: int = 50,
        timeout: float = 30.0
    ):
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.timeout = timeout
        self._seen_urls: Set[str] = set()
    
    async def discover(
        self, 
        start_url: str, 
        mode: str = "auto"
    ) -> DiscoveryResult:
        """
        Discover faculty pages from any URL.
        
        Args:
            start_url: The starting URL (can be homepage or any page)
            mode: Discovery mode - 'sitemap', 'deep', or 'auto'
        
        Returns:
            DiscoveryResult with discovered pages
        """
        logger.info(f"🔍 Starting faculty page discovery: {start_url}")
        logger.info(f"   Mode: {mode}, Max depth: {self.max_depth}, Max pages: {self.max_pages}")
        
        result = DiscoveryResult()
        self._seen_urls.clear()
        
        # Tier 1: Try sitemap
        if mode in ("sitemap", "auto"):
            sitemap_pages = await self._try_sitemap(start_url)
            if sitemap_pages:
                result.sitemap_found = True
                result.pages.extend(sitemap_pages)
                result.discovery_method = "sitemap"
                logger.info(f"✅ Sitemap: Found {len(sitemap_pages)} faculty-related URLs")
                
                # If we found enough from sitemap, we're done
                if len(sitemap_pages) >= 10 or mode == "sitemap":
                    return result
        
        # Tier 2: Deep crawl
        if mode in ("deep", "auto"):
            logger.info("🕸️ Starting deep crawl for faculty pages...")
            deep_pages = await self._deep_crawl(start_url)
            
            # Add only new pages
            for page in deep_pages:
                if page.url not in self._seen_urls:
                    result.pages.append(page)
                    self._seen_urls.add(page.url)
            
            result.pages_crawled = len(deep_pages)
            if not result.discovery_method:
                result.discovery_method = "deep_crawl"
            else:
                result.discovery_method = "hybrid"
            
            logger.info(f"✅ Deep crawl: Found {len(deep_pages)} pages")
        
        # Deduplicate and sort
        result.pages = list(set(result.pages))
        result.pages.sort(key=lambda p: p.score, reverse=True)
        
        logger.info(f"📊 Total unique pages discovered: {len(result.pages)}")
        return result
    
    async def _try_sitemap(self, url: str) -> List[DiscoveredPage]:
        """Try to discover URLs from sitemap.xml."""
        pages = []
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # Common sitemap locations
        sitemap_urls = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/sitemap/sitemap.xml",
        ]
        
        # Also check robots.txt for sitemap
        robots_sitemaps = await self._get_sitemaps_from_robots(base_url)
        sitemap_urls.extend(robots_sitemaps)
        
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for sitemap_url in sitemap_urls:
                try:
                    response = await client.get(sitemap_url)
                    if response.status_code == 200 and "xml" in response.headers.get("content-type", ""):
                        found_pages = self._parse_sitemap(response.text, base_url)
                        pages.extend(found_pages)
                        logger.debug(f"   Found {len(found_pages)} URLs in {sitemap_url}")
                except Exception as e:
                    logger.debug(f"   Sitemap {sitemap_url}: {e}")
                    continue
        
        return pages
    
    async def _get_sitemaps_from_robots(self, base_url: str) -> List[str]:
        """Extract sitemap URLs from robots.txt."""
        sitemaps = []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/robots.txt")
                if response.status_code == 200:
                    for line in response.text.split("\n"):
                        if line.lower().startswith("sitemap:"):
                            sitemap_url = line.split(":", 1)[1].strip()
                            sitemaps.append(sitemap_url)
        except Exception:
            pass
        return sitemaps
    
    def _parse_sitemap(self, xml_content: str, base_url: str) -> List[DiscoveredPage]:
        """Parse sitemap XML and filter for faculty-related URLs."""
        pages = []
        
        try:
            # Remove namespace for easier parsing
            xml_content = re.sub(r'\sxmlns="[^"]+"', '', xml_content)
            root = ET.fromstring(xml_content)
            
            # Handle sitemap index (contains other sitemaps)
            for sitemap in root.findall(".//sitemap"):
                loc = sitemap.find("loc")
                if loc is not None and loc.text:
                    # TODO: Recursively fetch nested sitemaps
                    pass
            
            # Handle regular sitemap
            for url_elem in root.findall(".//url"):
                loc = url_elem.find("loc")
                if loc is not None and loc.text:
                    url = loc.text.strip()
                    score = self._score_url(url)
                    
                    if score > 0:
                        page_type = self._classify_url(url)
                        pages.append(DiscoveredPage(
                            url=url,
                            score=score,
                            page_type=page_type,
                            source="sitemap"
                        ))
                        self._seen_urls.add(url)
        
        except ET.ParseError as e:
            logger.debug(f"   Sitemap parse error: {e}")
        
        return pages
    
    def _score_url(self, url: str) -> float:
        """Score a URL based on how likely it leads to faculty content."""
        url_lower = url.lower()
        score = 0.0
        
        # Check for faculty keywords
        for keyword in FACULTY_KEYWORDS:
            if keyword in url_lower:
                score += 0.2
        
        # Check for exclude patterns
        for pattern in EXCLUDE_PATTERNS:
            pattern_re = pattern.replace("*", ".*")
            if re.search(pattern_re, url_lower):
                return 0.0  # Exclude completely
        
        # Bonus for specific patterns
        if "/people" in url_lower or "/faculty" in url_lower:
            score += 0.3
        if "/directory" in url_lower or "/profiles" in url_lower:
            score += 0.2
        
        return min(score, 1.0)
    
    def _classify_url(self, url: str) -> str:
        """Classify URL as directory, profile, or unknown."""
        url_lower = url.lower()
        
        # Check for individual profile patterns
        if re.search(r"/people/[^/]+/?$", url_lower):
            return "profile"
        if re.search(r"/faculty/[^/]+/?$", url_lower): 
            return "profile"
        if re.search(r"/profile/[^/]+/?$", url_lower):
            return "profile"
        
        # Check for directory patterns
        if "/people" in url_lower and url_lower.endswith(("/people", "/people/")):
            return "directory"
        if "/faculty" in url_lower and not re.search(r"/faculty/[^/]+", url_lower):
            return "directory"
        if "/directory" in url_lower:
            return "directory"
        
        return "unknown"
    
    async def _deep_crawl(self, start_url: str) -> List[DiscoveredPage]:
        """Use BestFirstCrawlingStrategy for intelligent deep crawling."""
        pages = []
        parsed = urlparse(start_url)
        domain = parsed.netloc
        
        # Create keyword scorer
        scorer = KeywordRelevanceScorer(
            keywords=FACULTY_KEYWORDS,
            weight=0.8
        )
        
        # Create URL filter
        filter_chain = FilterChain([
            URLPatternFilter(patterns=FACULTY_URL_PATTERNS)
        ])
        
        # Create deep crawl strategy
        strategy = BestFirstCrawlingStrategy(
            max_depth=self.max_depth,
            include_external=False,
            url_scorer=scorer,
            filter_chain=filter_chain,
            max_pages=self.max_pages
        )
        
        config = CrawlerRunConfig(
            deep_crawl_strategy=strategy,
            stream=True
        )
        
        browser_config = BrowserConfig(headless=True, verbose=False)
        
        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                async for result in await crawler.arun(start_url, config=config):
                    if result.url not in self._seen_urls:
                        score = result.metadata.get("score", 0)
                        # Re-score based on our criteria
                        our_score = max(score, self._score_url(result.url))
                        
                        if our_score > 0:
                            pages.append(DiscoveredPage(
                                url=result.url,
                                score=our_score,
                                page_type=self._classify_url(result.url),
                                source="deep_crawl"
                            ))
                            self._seen_urls.add(result.url)
                        
                        logger.debug(f"   Crawled: {result.url} (score: {our_score:.2f})")
        
        except Exception as e:
            logger.error(f"Deep crawl error: {e}")
        
        return pages


async def discover_faculty_pages(
    url: str,
    mode: str = "auto",
    max_depth: int = 3,
    max_pages: int = 50
) -> DiscoveryResult:
    """
    Convenience function to discover faculty pages.
    
    Args:
        url: Starting URL
        mode: 'sitemap', 'deep', or 'auto'
        max_depth: Maximum crawl depth
        max_pages: Maximum pages to crawl
    
    Returns:
        DiscoveryResult with discovered pages
    """
    discoverer = FacultyPageDiscoverer(
        max_depth=max_depth,
        max_pages=max_pages
    )
    return await discoverer.discover(url, mode=mode)
