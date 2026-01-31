"""
Multi-fallback selector strategies for robust extraction.

Provides cascading selector strategies that try multiple approaches
until successful extraction is achieved.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from bs4 import BeautifulSoup
import re

from insti_scraper.core.logger import logger


@dataclass
class SelectorStrategy:
    """A single extraction strategy with priority."""
    name: str
    container: str
    name_selector: str
    title_selector: Optional[str] = None
    email_selector: Optional[str] = None
    link_selector: Optional[str] = None
    priority: int = 10  # Lower = higher priority
    min_results: int = 1  # Minimum results to consider strategy successful
    
    def extract(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract using this strategy."""
        results = []
        containers = soup.select(self.container)
        
        for container in containers:
            item = {}
            
            # Name (required)
            name_el = container.select_one(self.name_selector)
            if not name_el:
                continue
            item['name'] = name_el.get_text(strip=True)
            if not item['name'] or len(item['name']) < 2:
                continue
            
            # Title
            if self.title_selector:
                title_el = container.select_one(self.title_selector)
                item['title'] = title_el.get_text(strip=True) if title_el else None
            
            # Email
            if self.email_selector:
                email_el = container.select_one(self.email_selector)
                if email_el:
                    href = email_el.get('href', '')
                    item['email'] = href.replace('mailto:', '') if 'mailto:' in href else email_el.get_text(strip=True)
            
            # Profile link
            if self.link_selector:
                link_el = container.select_one(self.link_selector)
                item['profile_url'] = link_el.get('href') if link_el else None
            
            results.append(item)
        
        return results


# Pre-defined strategies for common page patterns
COMMON_STRATEGIES = [
    # DataTables
    SelectorStrategy(
        name="datatable",
        container="table.dataTable tbody tr, table#faculty tbody tr",
        name_selector="td:first-child a, td:first-child",
        title_selector="td:nth-child(2)",
        email_selector="td a[href^='mailto:']",
        link_selector="td:first-child a",
        priority=1
    ),
    
    # Card-based layouts
    SelectorStrategy(
        name="cards",
        container=".card, .faculty-card, .profile-card, .person-card",
        name_selector=".card-title, .name, h3, h4",
        title_selector=".card-subtitle, .title, .position",
        email_selector="a[href^='mailto:']",
        link_selector="a.card-link, .card-title a, h3 a",
        priority=2
    ),
    
    # Grid/list views
    SelectorStrategy(
        name="grid",
        container=".views-row, .grid-item, .faculty-item, .people-item",
        name_selector=".field-name-title a, .name a, h3 a, .title a",
        title_selector=".field-name-field-title, .role, .position",
        email_selector="a[href^='mailto:']",
        link_selector=".field-name-title a, h3 a",
        priority=3
    ),
    
    # Table without DataTables
    SelectorStrategy(
        name="table",
        container="table tr:not(:first-child), table tbody tr",
        name_selector="td:first-child a, td:first-child",
        title_selector="td:nth-child(2), td:nth-child(3)",
        email_selector="td a[href^='mailto:']",
        link_selector="td a[href]",
        priority=4
    ),
    
    # List items
    SelectorStrategy(
        name="list",
        container="ul.faculty li, ol.faculty li, .faculty-list li",
        name_selector="a, strong, .name",
        title_selector=".title, .position, em",
        email_selector="a[href^='mailto:']",
        link_selector="a[href]",
        priority=5
    ),
    
    # Definition lists
    SelectorStrategy(
        name="dl",
        container="dl dt, dl dd",
        name_selector="a, strong",
        link_selector="a[href]",
        priority=6
    ),
    
    # Generic divs with person info
    SelectorStrategy(
        name="generic_div",
        container="div[class*='person'], div[class*='faculty'], div[class*='profile'], div[class*='member']",
        name_selector="h2, h3, h4, .name, [class*='name']",
        title_selector=".title, .position, [class*='title'], [class*='role']",
        email_selector="a[href^='mailto:']",
        link_selector="h2 a, h3 a, h4 a, .name a",
        priority=7
    ),

    # 8. Sibling Strategy (Header + Paragraph pattern)
    # Common in simple pages: <h3>Name</h3><p>Title...</p>
    SelectorStrategy(
        name="sibling_header",
        container="div.content, div.main, section", # Broad container
        name_selector="h3, h4",  # We'll treat the header ITSELF as the item context in logic updates usually, but here we keep standard model
        # This strategy relies on the custom Sibling logic we need to implement or just smart selectors
        # For now, let's use a standard selector that tries to approximate this:
        title_selector="h3 + p, h4 + p",
        email_selector="h3 + p a[href^='mailto:'], h4 + p a[href^='mailto:']",
        link_selector="h3 a, h4 a",
        priority=8,
        min_results=3 # Needs high confidence to avoid extracting all headers
    ),

    # 9. Attribute-based (Robust)
    # Target elements with data- attributes which are often stable
    SelectorStrategy(
        name="attributes",
        container="[data-type='person'], [data-entity='faculty'], [itemtype*='Person']",
        name_selector="[itemprop='name'], [data-field='name']",
        title_selector="[itemprop='jobTitle'], [data-field='title']",
        email_selector="[itemprop='email'], a[href^='mailto:']",
        link_selector="a[itemprop='url']",
        priority=9
    )
]


class FallbackExtractor:
    """
    Tries multiple extraction strategies in order of priority.
    
    Returns results from the first successful strategy.
    """
    
    def __init__(self, strategies: List[SelectorStrategy] = None):
        self.strategies = sorted(
            strategies or COMMON_STRATEGIES,
            key=lambda s: s.priority
        )
    
    def add_strategy(self, strategy: SelectorStrategy, at_priority: int = None):
        """Add a custom strategy."""
        if at_priority is not None:
            strategy.priority = at_priority
        self.strategies.append(strategy)
        self.strategies.sort(key=lambda s: s.priority)
    
    def extract(self, html: str) -> tuple[List[Dict], Optional['SelectorStrategy']]:
        """
        Try all strategies and return first successful result.
        
        Returns:
            Tuple of (results, strategy_object)
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        for strategy in self.strategies:
            try:
                results = strategy.extract(soup)
                
                if len(results) >= strategy.min_results:
                    logger.info(f"   [Selector] Strategy '{strategy.name}' found {len(results)} items")
                    return results, strategy
                    
            except Exception as e:
                logger.debug(f"   Strategy '{strategy.name}' failed: {e}")
                continue
        
        logger.warning("   [Selector] All strategies failed, falling back to LLM")
        return [], None
    
    def extract_with_validation(
        self, 
        html: str, 
        validator: Callable[[Dict], bool] = None
    ) -> tuple[List[Dict], Optional['SelectorStrategy']]:
        """
        Extract with optional validation function.
        
        Args:
            html: Page HTML
            validator: Function to validate each extracted item
            
        Returns:
            Tuple of (valid_results, strategy_object)
        """
        results, strategy = self.extract(html)
        
        if validator:
            results = [r for r in results if validator(r)]
        
        return results, strategy


def create_extractor_with_overrides(url: str) -> FallbackExtractor:
    """
    Create a FallbackExtractor with university-specific overrides.
    
    Args:
        url: Page URL for profile lookup
        
    Returns:
        Configured FallbackExtractor
    """
    from insti_scraper.config import get_university_profile
    
    extractor = FallbackExtractor()
    
    profile = get_university_profile(url)
    if profile and profile.selectors and profile.selectors.container:
        # Add university-specific strategy at highest priority
        custom = SelectorStrategy(
            name=f"custom_{profile.name.lower().replace(' ', '_')}",
            container=profile.selectors.container,
            name_selector=profile.selectors.name or "a, h3, .name",
            title_selector=profile.selectors.title,
            email_selector=profile.selectors.email,
            link_selector=profile.selectors.profile_link,
            priority=0  # Highest priority
        )
        extractor.add_strategy(custom, at_priority=0)
        logger.info(f"   [Selector] Added custom strategy for {profile.name}")
    
    return extractor
