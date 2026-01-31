"""
Auto configuration module for dynamic settings.

Automatically adjusts MAX_PAGES and other settings based on page analysis.
"""

import re
from dataclasses import dataclass
from typing import Optional
from math import ceil


@dataclass
class PaginationInfo:
    """Information about pagination on a page."""
    total_items: int = 0
    items_per_page: int = 10
    current_page: int = 1
    total_pages: int = 0
    pagination_type: str = "unknown"  # datatable, infinite_scroll, click, alpha, none
    next_selector: Optional[str] = None
    
    def calculate_pages(self) -> int:
        """Calculate total pages needed."""
        if self.total_items == 0:
            return 10  # Default fallback
        if self.items_per_page == 0:
            return 10
        return min(ceil(self.total_items / self.items_per_page), 100)  # Cap at 100


class AutoConfig:
    """
    Dynamically adjusts scraping configuration based on page analysis.
    
    Features:
    - Extracts total count from "Showing X of Y" patterns
    - Auto-calculates required MAX_PAGES
    - Detects pagination type from HTML patterns
    """
    
    # Common patterns for extracting total count
    TOTAL_PATTERNS = [
        r'of\s+(\d+(?:,\d+)?)\s+(?:entries|results|items|records)',
        r'(\d+(?:,\d+)?)\s+(?:total|results|items|entries)',
        r'showing\s+\d+\s*[-–]\s*\d+\s+of\s+(\d+(?:,\d+)?)',
        r'page\s+\d+\s+of\s+(\d+)',
        r'(\d+(?:,\d+)?)\s+faculty|staff|members|people',
    ]
    
    # Patterns indicating pagination type
    PAGINATION_INDICATORS = {
        "datatable": [
            "datatable", "dataTable", "table_id", "data-dt-",
            'name="length"', "show entries", "entries per page"
        ],
        "infinite_scroll": [
            "infinite-scroll", "load-more-trigger", "scroll-load",
            "IntersectionObserver", "waypoint"
        ],
        "click": [
            "pagination", "pager", "page-numbers", "next-page",
            'rel="next"', "paginate_button"
        ],
        "alpha": [
            "a-z", "alphabet", "browse-letter", "filter-letter"
        ]
    }
    
    @classmethod
    def extract_total_from_html(cls, html: str) -> int:
        """
        Extract total item count from HTML content.
        
        Looks for patterns like:
        - "Showing 1 to 10 of 1,661 entries"
        - "1,661 results"
        - "Page 1 of 167"
        """
        html_lower = html.lower()
        
        for pattern in cls.TOTAL_PATTERNS:
            match = re.search(pattern, html_lower)
            if match:
                total_str = match.group(1).replace(',', '')
                try:
                    return int(total_str)
                except ValueError:
                    continue
        
        return 0
    
    @classmethod
    def detect_pagination_type(cls, html: str) -> str:
        """
        Detect the pagination mechanism from HTML.
        
        Returns one of: datatable, infinite_scroll, click, alpha, none
        """
        html_lower = html.lower()
        
        scores = {ptype: 0 for ptype in cls.PAGINATION_INDICATORS.keys()}
        
        for ptype, indicators in cls.PAGINATION_INDICATORS.items():
            for indicator in indicators:
                if indicator.lower() in html_lower:
                    scores[ptype] += 1
        
        if max(scores.values()) == 0:
            return "none"
        
        return max(scores, key=scores.get)
    
    @classmethod
    def detect_items_per_page(cls, html: str) -> int:
        """
        Detect items per page from HTML.
        
        Looks for DataTable length selector or counts visible items.
        """
        # Look for selected option in length dropdown
        match = re.search(r'<option[^>]*selected[^>]*>(\d+)</option>', html, re.IGNORECASE)
        if match:
            return int(match.group(1))
        
        # Look for "Showing 1 to X" pattern
        match = re.search(r'showing\s+\d+\s+to\s+(\d+)', html, re.IGNORECASE)
        if match:
            return int(match.group(1))
        
        return 10  # Default
    
    @classmethod
    def analyze_page(cls, html: str) -> PaginationInfo:
        """
        Analyze HTML and return pagination configuration.
        
        Args:
            html: Page HTML content
            
        Returns:
            PaginationInfo with detected settings
        """
        total = cls.extract_total_from_html(html)
        items_per_page = cls.detect_items_per_page(html)
        pagination_type = cls.detect_pagination_type(html)
        
        info = PaginationInfo(
            total_items=total,
            items_per_page=items_per_page,
            pagination_type=pagination_type
        )
        
        info.total_pages = info.calculate_pages()
        
        return info
    
    @classmethod
    def get_next_selector(cls, pagination_type: str) -> str:
        """Get the CSS selector for the Next button based on pagination type."""
        selectors = {
            "datatable": 'a.paginate_button.next:not(.disabled), [data-dt-idx="next"]:not(.disabled)',
            "click": 'a.next:not(.disabled), a[rel="next"], .pagination a:contains("Next"), [aria-label="Next"]',
            "alpha": None,  # A-Z doesn't use next buttons
            "infinite_scroll": None,  # Infinite scroll uses scrolling
        }
        return selectors.get(pagination_type)


def auto_configure_pagination(html: str) -> dict:
    """
    Convenience function to get auto-configured pagination settings.
    
    Returns:
        Dict with max_pages, pagination_type, items_per_page, next_selector
    """
    info = AutoConfig.analyze_page(html)
    
    return {
        "max_pages": info.calculate_pages(),
        "total_items": info.total_items,
        "items_per_page": info.items_per_page,
        "pagination_type": info.pagination_type,
        "next_selector": AutoConfig.get_next_selector(info.pagination_type)
    }
