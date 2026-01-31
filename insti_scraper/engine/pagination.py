"""
Pagination handler for multi-page faculty directories.

Supports:
- DataTables pagination (click-through with JavaScript)
- Standard click pagination (next/prev buttons)
- Alpha pagination (A-Z browsing)
"""
import asyncio
from typing import List, Tuple, Optional, AsyncGenerator
from dataclasses import dataclass

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig
from insti_scraper.core.auto_config import AutoConfig, PaginationInfo, auto_configure_pagination
from insti_scraper.core.logger import logger


@dataclass
class PageResult:
    """Result from scraping a single page."""
    html: str
    page_number: int
    url: str
    success: bool = True
    error: Optional[str] = None


class PaginationHandler:
    """
    Handles pagination for multi-page faculty directories.
    
    Reuses browser session to maintain JavaScript state for DataTables.
    """
    
    def __init__(
        self,
        max_pages: int = 50,
        page_delay: float = 1.0,
        timeout: float = 30.0
    ):
        self.max_pages = max_pages
        self.page_delay = page_delay
        self.timeout = timeout
    
    async def iterate_pages(
        self,
        url: str,
        pagination_info: PaginationInfo,
        next_selector_override: Optional[str] = None
    ) -> AsyncGenerator[PageResult, None]:
        """
        Iterate through all pages of a paginated directory.
        
        Args:
            url: Starting URL
            pagination_info: Pagination configuration from AutoConfig
            next_selector_override: Optional CSS selector from Vision analysis
            
        Yields:
            PageResult for each page
        """
        pages_to_fetch = min(pagination_info.total_pages, self.max_pages)
        logger.info(f"📄 Pagination: {pagination_info.pagination_type}, fetching {pages_to_fetch} pages")
        
        # If override is provided, force 'click' or 'datatable' mode depending on what seems appropriate
        # For now, if we have a selector, we treat it as a click-to-advance mechanism
        if next_selector_override:
            logger.info(f"   🎯 Using vision-detected next selector: {next_selector_override}")
            async for result in self._iterate_click(url, pages_to_fetch, pagination_info, next_selector_override):
                yield result
            return

        if pagination_info.pagination_type == "datatable":
            async for result in self._iterate_datatable(url, pages_to_fetch, pagination_info):
                yield result
        
        elif pagination_info.pagination_type == "click":
            async for result in self._iterate_click(url, pages_to_fetch, pagination_info):
                yield result
        
        elif pagination_info.pagination_type == "alpha":
            async for result in self._iterate_alpha(url):
                yield result
        
        else:
            # No pagination or unknown - just yield the first page
            browser_config = BrowserConfig(headless=True, verbose=False)
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url)
                if result.success:
                    yield PageResult(html=result.html, page_number=1, url=url)
    
    async def _iterate_datatable(
        self,
        url: str,
        max_pages: int,
        pagination_info: PaginationInfo
    ) -> AsyncGenerator[PageResult, None]:
        """Handle DataTables pagination by clicking Next button."""
        next_selector = AutoConfig.get_next_selector("datatable")
        
        browser_config = BrowserConfig(
            headless=True,
            verbose=False,
            extra_args=["--disable-gpu", "--no-sandbox"]
        )
        
        async with AsyncWebCrawler(config=browser_config) as crawler:
            # Initial page
            config = CrawlerRunConfig(
                wait_until="networkidle",
                delay_before_return_html=2.0  # Wait for DataTable to render
            )
            result = await crawler.arun(url, config=config)
            
            if not result.success:
                yield PageResult(html="", page_number=1, url=url, success=False, error=str(result.error_message))
                return
            
            yield PageResult(html=result.html, page_number=1, url=url)
            
            # Click through subsequent pages
            for page_num in range(2, max_pages + 1):
                await asyncio.sleep(self.page_delay)
                
                try:
                    # Execute JavaScript to click Next button
                    click_config = CrawlerRunConfig(
                        js_code=f"""
                        (async () => {{
                            const nextBtn = document.querySelector('{next_selector}');
                            if (nextBtn && !nextBtn.classList.contains('disabled')) {{
                                nextBtn.click();
                                await new Promise(r => setTimeout(r, 1500));
                            }}
                        }})();
                        """,
                        delay_before_return_html=2.0
                    )
                    
                    result = await crawler.arun(url, config=click_config)
                    
                    if result.success:
                        yield PageResult(html=result.html, page_number=page_num, url=url)
                    else:
                        logger.warning(f"   Page {page_num} fetch failed: {result.error_message}")
                        break
                        
                except Exception as e:
                    logger.error(f"   Error on page {page_num}: {e}")
                    break
    
    async def _iterate_click(
        self,
        url: str,
        max_pages: int,
        pagination_info: PaginationInfo,
        next_selector_override: Optional[str] = None
    ) -> AsyncGenerator[PageResult, None]:
        """Handle standard click pagination."""
        next_selector = next_selector_override or AutoConfig.get_next_selector("click")
        
        browser_config = BrowserConfig(headless=True, verbose=False)
        
        async with AsyncWebCrawler(config=browser_config) as crawler:
            current_url = url
            
            for page_num in range(1, max_pages + 1):
                result = await crawler.arun(current_url)
                
                if not result.success:
                    yield PageResult(html="", page_number=page_num, url=current_url, success=False)
                    break
                
                yield PageResult(html=result.html, page_number=page_num, url=current_url)
                
                # Find next page URL from HTML
                # Strategy: 
                # 1. If we have a custom selector, try to find element and click it (complex) OR extract href (simpler)
                # 2. If it's a standard link loop, look for href
                
                next_href = None
                
                # If using override selector, try to extract href from it first
                if next_selector_override:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(result.html, 'html.parser')
                    next_el = soup.select_one(next_selector_override)
                    if next_el and next_el.name == 'a':
                        next_href = next_el.get('href')
                
                # Fallback to standard regex patterns if no href found yet
                if not next_href:
                    import re
                    next_match = re.search(r'<a[^>]*rel=["\']next["\'][^>]*href=["\']([^"\']+)["\']', result.html)
                    if not next_match:
                         next_match = re.search(r'<a[^>]*class=["\'][^"\']*next[^"\']*["\'][^>]*href=["\']([^"\']+)["\']', result.html)
                    
                    if next_match:
                        next_href = next_match.group(1)
                
                if next_href:
                    if not next_href.startswith("http"):
                        from urllib.parse import urljoin
                        next_href = urljoin(current_url, next_href)
                    current_url = next_href
                else:
                    logger.info(f"   No next page link found after page {page_num}")
                    break
                
                await asyncio.sleep(self.page_delay)
    
    async def _iterate_alpha(self, url: str) -> AsyncGenerator[PageResult, None]:
        """Handle A-Z alphabetical pagination."""
        browser_config = BrowserConfig(headless=True, verbose=False)
        
        async with AsyncWebCrawler(config=browser_config) as crawler:
            # Try to find A-Z links on the page
            initial = await crawler.arun(url)
            if not initial.success:
                return
            
            yield PageResult(html=initial.html, page_number=1, url=url)
            
            # Extract letter URLs
            import re
            letter_pattern = r'href=["\']([^"\']*(?:/[A-Z]/|[?&]letter=[A-Z]|browse/[a-z]))["\']'
            matches = re.findall(letter_pattern, initial.html, re.IGNORECASE)
            
            from urllib.parse import urljoin
            letter_urls = list(set(urljoin(url, m) for m in matches))[:26]  # Max 26 letters
            
            for i, letter_url in enumerate(letter_urls, 2):
                result = await crawler.arun(letter_url)
                if result.success:
                    yield PageResult(html=result.html, page_number=i, url=letter_url)
                await asyncio.sleep(0.5)


async def extract_with_pagination(
    url: str,
    extraction_service,
    max_pages: int = 50
) -> Tuple[List, str]:
    """
    Convenience function to extract from paginated pages.
    
    Args:
        url: Starting URL
        extraction_service: ExtractionService instance
        max_pages: Maximum pages to process
        
    Returns:
        Tuple of (all_professors, department_name)
    """
    from crawl4ai import AsyncWebCrawler
    
    # First fetch to detect pagination
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url)
        if not result.success:
            return [], "General"
        
        pagination_info = AutoConfig.analyze_page(result.html)
        next_selector_override = None
        
        # [NEW] Lazy Vision Evaluation for Pagination
        # If standard regex failed to detect pagination, ask Vision
        if pagination_info.pagination_type in ("none", "unknown"):
             try:
                 from insti_scraper.engine.vision_analyzer import VisionPageAnalyzer
                 logger.info("   👀 Standard pagination detection failed. Trying Vision Anchor...")
                 
                 analyzer = VisionPageAnalyzer()
                 # We need to re-capture or just call analyze (which captures)
                 vision_result = await analyzer.analyze(url)
                 
                 if vision_result.pagination_type != "none" and vision_result.pagination_type != "unknown":
                     logger.info(f"   ✅ Vision detected pagination: {vision_result.pagination_type}")
                     # Update info
                     pagination_info.pagination_type = vision_result.pagination_type
                     pagination_info.total_pages = vision_result.max_pages_needed
                     # Save selector
                     next_selector_override = vision_result.next_button_selector
                 else:
                     logger.info("   ❌ Vision also found no pagination.")
                     
             except ImportError:
                 pass
             except Exception as e:
                 logger.warning(f"   ⚠️ Vision pagination check failed: {e}")
    
    if pagination_info.pagination_type in ("none", "unknown") and not next_selector_override:
        # No pagination - single page extraction
        professors, dept = await extraction_service.extract_with_fallback(url, result.html, skip_vision=True)
        return professors, dept
    
    # Multi-page extraction
    handler = PaginationHandler(max_pages=max_pages)
    all_professors = []
    department_name = "General"
    
    async for page_result in handler.iterate_pages(url, pagination_info, next_selector_override):
        if page_result.success and page_result.html:
            professors, dept = await extraction_service.extract_with_fallback(
                url, 
                page_result.html, 
                skip_vision=True  # Skip vision for subsequent pages
            )
            all_professors.extend(professors)
            if dept and dept != "General":
                department_name = dept
            
            logger.info(f"   Page {page_result.page_number}: {len(professors)} professors")
    
    return all_professors, department_name
