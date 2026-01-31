"""
Abstract page handlers for different page types.

Provides specialized extraction logic for:
- Type A/B: Directory pages (full/partial listings)
- Type C: Department gateway pages
- Type D: Paginated lists
- Type F: Individual profiles
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup

from insti_scraper.data.models import Professor
from insti_scraper.config import SelectorConfig, get_university_profile
from insti_scraper.core.logger import logger


@dataclass
class ExtractionResult:
    """Result from a page handler extraction."""
    professors: List[Professor]
    department_name: str = "General"
    next_pages: List[str] = None  # For pagination or gateway links
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.next_pages is None:
            self.next_pages = []
        if self.metadata is None:
            self.metadata = {}


class PageHandler(ABC):
    """Abstract base class for page-specific extraction logic."""
    
    def __init__(self, selectors: Optional[SelectorConfig] = None):
        self.selectors = selectors
    
    @abstractmethod
    async def extract(self, url: str, html: str) -> ExtractionResult:
        """Extract data from the page."""
        pass
    
    def _get_soup(self, html: str) -> BeautifulSoup:
        """Parse HTML into BeautifulSoup."""
        return BeautifulSoup(html, 'html.parser')
    
    def _extract_with_selectors(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract using configured CSS selectors."""
        if not self.selectors or not self.selectors.container:
            return []
        
        results = []
        containers = soup.select(self.selectors.container)
        
        for container in containers:
            item = {}
            
            if self.selectors.name:
                name_el = container.select_one(self.selectors.name)
                item['name'] = name_el.get_text(strip=True) if name_el else None
            
            if self.selectors.title:
                title_el = container.select_one(self.selectors.title)
                item['title'] = title_el.get_text(strip=True) if title_el else None
            
            if self.selectors.email:
                email_el = container.select_one(self.selectors.email)
                if email_el:
                    href = email_el.get('href', '')
                    item['email'] = href.replace('mailto:', '') if href.startswith('mailto:') else email_el.get_text(strip=True)
            
            if self.selectors.profile_link:
                link_el = container.select_one(self.selectors.profile_link)
                item['profile_url'] = link_el.get('href') if link_el else None
            
            if item.get('name'):
                results.append(item)
        
        return results


class DirectoryPageHandler(PageHandler):
    """Handler for Type A/B directory pages."""
    
    async def extract(self, url: str, html: str) -> ExtractionResult:
        """Extract faculty from directory page using selectors if available."""
        soup = self._get_soup(html)
        
        # Try selector-based extraction first
        if self.selectors and self.selectors.has_selectors():
            logger.info(f"   [Selector] Using configured selectors for extraction")
            items = self._extract_with_selectors(soup)
            
            if items:
                professors = [
                    Professor(
                        name=item.get('name', ''),
                        title=item.get('title'),
                        email=item.get('email'),
                        profile_url=item.get('profile_url')
                    )
                    for item in items if item.get('name')
                ]
                return ExtractionResult(professors=professors)
        
        # Fall back to LLM extraction
        return ExtractionResult(professors=[], metadata={'fallback_needed': True})


class GatewayPageHandler(PageHandler):
    """Handler for Type C department gateway pages."""
    
    async def extract(self, url: str, html: str) -> ExtractionResult:
        """Extract department links from gateway page."""
        soup = self._get_soup(html)
        
        # Look for department/faculty links
        department_links = []
        link_patterns = [
            'a[href*="faculty"]',
            'a[href*="people"]',
            'a[href*="staff"]',
            'a[href*="directory"]',
            '.department a',
            '.departments a',
            'nav a'
        ]
        
        seen = set()
        for pattern in link_patterns:
            for link in soup.select(pattern):
                href = link.get('href', '')
                if href and href not in seen and not href.startswith('#'):
                    # Filter out obviously bad links
                    if any(x in href.lower() for x in ['faculty', 'people', 'staff', 'directory']):
                        department_links.append(href)
                        seen.add(href)
        
        logger.info(f"   [Gateway] Found {len(department_links)} department links")
        
        return ExtractionResult(
            professors=[],
            next_pages=department_links,
            metadata={'page_type': 'gateway'}
        )


class PaginatedPageHandler(PageHandler):
    """Handler for Type D paginated pages."""
    
    def __init__(self, selectors: Optional[SelectorConfig] = None, max_pages: int = 50):
        super().__init__(selectors)
        self.max_pages = max_pages
    
    async def extract(self, url: str, html: str) -> ExtractionResult:
        """Extract from paginated page - returns first page and pagination info."""
        from insti_scraper.core.auto_config import AutoConfig
        
        pagination_info = AutoConfig.analyze_page(html)
        
        return ExtractionResult(
            professors=[],
            metadata={
                'page_type': 'paginated',
                'pagination_type': pagination_info.pagination_type,
                'total_pages': pagination_info.total_pages,
                'total_items': pagination_info.total_items
            }
        )


class ProfilePageHandler(PageHandler):
    """Handler for Type F individual profile pages."""
    
    async def extract(self, url: str, html: str) -> ExtractionResult:
        """Extract single professor from profile page."""
        soup = self._get_soup(html)
        
        # Try common profile page patterns
        name = None
        title = None
        email = None
        
        # Name extraction patterns
        name_selectors = ['h1', '.profile-name', '.faculty-name', '.name', '[itemprop="name"]']
        for sel in name_selectors:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                name = el.get_text(strip=True)
                break
        
        # Title extraction
        title_selectors = ['.title', '.position', '.job-title', '[itemprop="jobTitle"]']
        for sel in title_selectors:
            el = soup.select_one(sel)
            if el:
                title = el.get_text(strip=True)
                break
        
        # Email extraction
        email_el = soup.select_one('a[href^="mailto:"]')
        if email_el:
            email = email_el.get('href', '').replace('mailto:', '')
        
        if name:
            professor = Professor(
                name=name,
                title=title,
                email=email,
                profile_url=url
            )
            return ExtractionResult(professors=[professor])
        
        return ExtractionResult(professors=[])


def get_handler_for_page_type(
    page_type: str, 
    url: str
) -> PageHandler:
    """
    Factory function to get the appropriate handler for a page type.
    
    Args:
        page_type: Type from vision analysis (A, B, C, D, F, Z)
        url: Page URL for profile lookup
    
    Returns:
        Appropriate PageHandler instance
    """
    # Get selectors from university profile if available
    profile = get_university_profile(url)
    selectors = profile.selectors if profile else None
    
    handlers = {
        'directory_clickable': DirectoryPageHandler(selectors),
        'directory_partial': DirectoryPageHandler(selectors),
        'department_gateway': GatewayPageHandler(selectors),
        'paginated_list': PaginatedPageHandler(selectors),
        'individual_profile': ProfilePageHandler(selectors),
    }
    
    return handlers.get(page_type, DirectoryPageHandler(selectors))
