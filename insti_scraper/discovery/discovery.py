"""
Faculty page discovery using DuckDuckGo search, sitemap and deep crawling.

This module provides intelligent URL discovery for faculty pages
from any university URL using a hybrid approach:
1. DuckDuckGo web search (PRIMARY - most reliable)
2. Sitemap-based discovery (fallback)
3. Deep crawling with semantic matching (last resort)
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
from crawl4ai.deep_crawling.filters import (
    FilterChain, 
    URLPatternFilter, 
    DomainFilter,
    ContentRelevanceFilter
)
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer

from insti_scraper.core.logger import logger


# Semantic query for content-based filtering (BM25 matching)
# This query describes what faculty directory pages typically contain
FACULTY_CONTENT_QUERY = (
    "faculty professor staff people directory listing "
    "email research interests office department "
    "academic personnel team members profiles"
)


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
# Note: Be careful not to exclude too aggressively - pages like /topic/faculty are valid
EXCLUDE_PATTERNS = [
    r"/login", r"/search\?", r"/calendar", r"/events/",
    r"/contact$", r"/apply$", r"/admission",
    r"\.pdf$", r"\.jpg$", r"\.png$", r"\.xml$",
    r"/rss", r"/feed"  # RSS feeds
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
        mode: str = "auto",
        university_name: str = None,
        model: str = None
    ) -> DiscoveryResult:
        """
        Discover faculty pages from any URL.
        
        Args:
            start_url: The starting URL (can be homepage or any page)
            mode: Discovery mode - 'search' (DDG), 'sitemap', 'deep', or 'auto'
            university_name: Name of university (for DDG search)
            model: LLM model for URL selection
        
        Returns:
            DiscoveryResult with discovered pages
        """
        logger.info(f"🔍 Starting faculty page discovery: {start_url}")
        logger.info(f"   Mode: {mode}, Max depth: {self.max_depth}, Max pages: {self.max_pages}")
        
        result = DiscoveryResult()
        self._seen_urls.clear()
        
        # Tier 1: DuckDuckGo search (PRIMARY for 'search' and 'auto' modes)
        if mode in ("search", "auto"):
            try:
                from .duckduckgo_discovery import discover_faculty_url, is_ddgs_available
                
                if is_ddgs_available():
                    name = university_name or self._extract_university_name(start_url)
                    logger.info(f"🔎 DuckDuckGo search for: {name}")
                    
                    faculty_url = await discover_faculty_url(
                        university_name=name,
                        homepage_url=start_url,
                        model=model
                    )
                    
                    if faculty_url:
                        result.pages.append(DiscoveredPage(
                            url=faculty_url,
                            score=1.0,  # High confidence - LLM selected
                            page_type="directory",
                            source="duckduckgo"
                        ))
                        result.discovery_method = "duckduckgo"
                        self._seen_urls.add(faculty_url)
                        logger.info(f"✅ DuckDuckGo: Found {faculty_url}")
                        
                        if mode == "search":
                            return result
                else:
                    logger.warning("DuckDuckGo search not available. Install: uv add duckduckgo-search")
            except ImportError:
                logger.warning("DuckDuckGo module not found")
            except Exception as e:
                logger.error(f"DuckDuckGo search failed: {e}")
        
        # Tier 2: Try sitemap
        if mode in ("sitemap", "auto"):
            sitemap_pages = await self._try_sitemap(start_url)
            if sitemap_pages:
                result.sitemap_found = True
                result.pages.extend(sitemap_pages)
                if not result.discovery_method:
                    result.discovery_method = "sitemap"
                logger.info(f"✅ Sitemap: Found {len(sitemap_pages)} faculty-related URLs")
                
                # If we found enough from sitemap, we're done
                if len(sitemap_pages) >= 10 or mode == "sitemap":
                    return result
        
        # Tier 3: Deep crawl (last resort)
        if mode in ("deep", "auto") and len(result.pages) < 5:
            logger.info("🕸️ Starting deep crawl for faculty pages...")
            deep_pages = await self._deep_crawl(start_url)
            
            result.pages.extend(deep_pages)
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
    
    def _extract_university_name(self, url: str) -> str:
        """Extract university name from URL for search."""
        parsed = urlparse(url)
        domain = parsed.netloc
        
        # Remove common prefixes/suffixes
        name = domain.replace("www.", "").replace(".edu", "").replace(".ac.in", "")
        name = name.replace(".ac.uk", "").replace(".org", "")
        
        # Convert domain parts to title case
        parts = name.split(".")
        return " ".join(part.title() for part in parts)
    
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
        
        # Check for exclude patterns (these are already regex)
        for pattern in EXCLUDE_PATTERNS:
            if re.search(pattern, url_lower):
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
        
        # Query params that indicate directory
        if "people_type" in url_lower or "?type=" in url_lower:
            return "directory"
        
        return "unknown"
    
    def _has_profile_content(self, html: str) -> bool:
        """
        Check if HTML content looks like a faculty profile listing.
        Returns True if page has indicators of actual profile listings.
        """
        if not html:
            return False
        
        html_lower = html.lower()
        
        # Count indicators
        score = 0
        
        # Check for multiple .edu emails (strong indicator)
        email_count = len(re.findall(r'[\w.-]+@[\w.-]+\.edu', html))
        if email_count >= 3:
            score += 3
        elif email_count >= 1:
            score += 1
        
        # Check for profile-style links (e.g., /people/name, /faculty/name)
        profile_links = len(re.findall(r'href=["\']/(?:people|faculty|staff|profile)/[^"\']+["\']', html_lower))
        if profile_links >= 3:
            score += 3
        elif profile_links >= 1:
            score += 1
        
        # Check for title indicators (Professor, PhD, etc.)
        title_count = len(re.findall(r'\b(?:professor|assistant professor|associate professor|phd|ph\.d|lecturer|researcher)\b', html_lower))
        if title_count >= 3:
            score += 2
        
        # Check for department mentions
        if any(dept in html_lower for dept in ['department of', 'school of', 'faculty ']):
            score += 1
        
        # Threshold: need at least 3 points to be considered a profile page
        return score >= 3
    
    async def _deep_crawl(self, start_url: str) -> List[DiscoveredPage]:
        """
        Use BestFirstCrawlingStrategy with multi-layer filtering.
        
        Layer 1: DomainFilter - Stay within university domain
        Layer 2: URLPatternFilter - Pre-filter by URL patterns  
        Layer 3: ContentRelevanceFilter - BM25 semantic matching on content
        """
        pages = []
        parsed = urlparse(start_url)
        domain = parsed.netloc
        
        # Extract base domain (e.g., "mit.edu" from "nse.mit.edu")
        domain_parts = domain.split('.')
        if len(domain_parts) >= 2:
            base_domain = '.'.join(domain_parts[-2:])
        else:
            base_domain = domain
        
        logger.info(f"   Domain: {base_domain}")
        
        # LAYER 1: Domain filter - stay within university
        # This is the ONLY filter during exploration
        # We DON'T use URLPatternFilter here as it blocks exploration of non-matching paths
        domain_filter = DomainFilter(
            allowed_domains=[base_domain],
            blocked_domains=["news." + base_domain]  # Block news subdomain
        )
        
        # Note: ContentRelevanceFilter is too restrictive for exploration
        # We'll filter results using our _score_url() method instead
        
        # Combine filters - just domain filter for exploration
        filter_chain = FilterChain([
            domain_filter
        ])
        
        # Create keyword scorer for URL-based prioritization
        scorer = KeywordRelevanceScorer(
            keywords=FACULTY_KEYWORDS,
            weight=0.7
        )
        
        # Create deep crawl strategy
        strategy = BestFirstCrawlingStrategy(
            max_depth=self.max_depth,
            include_external=True,  # ALLOW external links to find subdomains (e.g. nse.mit.edu)
            # The DomainFilter above will strictly keep us within the base_domain
            url_scorer=scorer,
            filter_chain=filter_chain,
            max_pages=self.max_pages
        )
        
        config = CrawlerRunConfig(
            deep_crawl_strategy=strategy,
            stream=True  # Back to streaming as it's more reliable
        )
        
        browser_config = BrowserConfig(headless=True, verbose=False)
        
        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                try:
                    async for result in await crawler.arun(start_url, config=config):
                        if result.url not in self._seen_urls:
                            # Get score from crawler (includes content relevance)
                            crawl_score = result.metadata.get("score", 0) if result.metadata else 0
                            url_score = self._score_url(result.url)
                            page_type = self._classify_url(result.url)
                            
                            # CONTENT-BASED VALIDATION: Check if page has actual profile listings
                            has_profiles = self._has_profile_content(result.html or "")
                            
                            # Boost pages that have actual profile content
                            if has_profiles:
                                url_score += 0.5  # Big boost for pages with real profiles
                                if page_type == "unknown":
                                    page_type = "directory"  # Upgrade to directory
                            elif page_type == "directory" and not has_profiles:
                                # URL looks like directory but no profiles found - demote
                                url_score *= 0.3
                            
                            # Combined score: crawl4ai score + our URL score
                            combined_score = (crawl_score * 0.6) + (url_score * 0.4)
                            
                            if combined_score > 0:
                                pages.append(DiscoveredPage(
                                    url=result.url,
                                    score=combined_score,
                                    page_type=page_type,
                                    source="deep_crawl"
                                ))
                                self._seen_urls.add(result.url)
                                content_marker = "📄" if has_profiles else "⚪"
                                logger.debug(f"   {content_marker} {result.url} (score: {combined_score:.2f}, type: {page_type})")

                except Exception as e:
                    # Ignore the ContextVar error which happens on cleanup
                    if "ContextVar" in str(e) or "GeneratorExit" in str(e):
                        logger.debug(f"Ignored cleanup error: {e}")
                    else:
                        logger.error(f"Stream error: {e}")
        
        except Exception as e:
            logger.error(f"Deep crawl error: {e}")
        
        # Sort by score and prioritize directories over profiles
        pages.sort(key=lambda p: (p.page_type == "directory", p.score), reverse=True)
        
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
