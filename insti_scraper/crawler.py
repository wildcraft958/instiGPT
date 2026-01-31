"""
Web crawling and HTTP fetching.

Consolidated from infrastructure/crawler.py and core/rate_limiter.py
"""

import asyncio
import random
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List
from contextlib import asynccontextmanager

import httpx
from crawl4ai import AsyncWebCrawler, BrowserConfig

from .config import settings

logger = logging.getLogger(__name__)


class FetchMode(Enum):
    """How to fetch the page."""
    HTML = "html"           # Simple HTTP GET
    BROWSER = "browser"     # Full browser rendering
    AUTO = "auto"           # Choose based on content


@dataclass
class FetchResult:
    """Result of a fetch operation."""
    url: str
    html: str = ""
    success: bool = False
    error: Optional[str] = None
    status_code: int = 0
    
    @property
    def ok(self) -> bool:
        return self.success and bool(self.html)


class CrawlerManager:
    """
    Manages HTTP and browser-based fetching with rate limiting.
    
    Usage:
        async with CrawlerManager() as crawler:
            result = await crawler.fetch(url)
    """
    
    def __init__(
        self,
        base_delay: tuple = (1.0, 2.0),
        max_concurrent: int = 5,
        timeout: float = 30.0
    ):
        self.base_delay = base_delay
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self._browser: Optional[AsyncWebCrawler] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def __aenter__(self):
        """Initialize resources."""
        self._http_client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup resources."""
        if self._http_client:
            await self._http_client.aclose()
        if self._browser:
            await self._browser.close()
    
    async def _get_browser(self) -> AsyncWebCrawler:
        """Get or create browser instance."""
        if self._browser is None:
            config = BrowserConfig(headless=True, verbose=False)
            self._browser = AsyncWebCrawler(config=config)
            await self._browser.start()
        return self._browser
    
    async def _rate_limit(self):
        """Apply rate limiting delay."""
        delay = random.uniform(*self.base_delay)
        await asyncio.sleep(delay)
    
    async def fetch(
        self,
        url: str,
        mode: FetchMode = FetchMode.HTML,
        use_cache: bool = True
    ) -> FetchResult:
        """
        Fetch a URL.
        
        Args:
            url: URL to fetch
            mode: HTML (simple) or BROWSER (JavaScript)
            use_cache: Whether to use caching
        
        Returns:
            FetchResult with HTML content
        """
        async with self._semaphore:
            await self._rate_limit()
            
            try:
                if mode == FetchMode.HTML:
                    return await self._fetch_http(url)
                elif mode == FetchMode.BROWSER:
                    return await self._fetch_browser(url, use_cache)
                else:  # AUTO
                    result = await self._fetch_http(url)
                    if not result.ok or self._needs_js(result.html):
                        result = await self._fetch_browser(url, use_cache)
                    return result
                    
            except Exception as e:
                logger.error(f"Fetch error for {url}: {e}")
                return FetchResult(url=url, error=str(e))
    
    async def _fetch_http(self, url: str) -> FetchResult:
        """Simple HTTP fetch."""
        try:
            response = await self._http_client.get(url)
            return FetchResult(
                url=url,
                html=response.text,
                success=response.status_code == 200,
                status_code=response.status_code
            )
        except Exception as e:
            return FetchResult(url=url, error=str(e))
    
    async def _fetch_browser(self, url: str, use_cache: bool) -> FetchResult:
        """Browser-based fetch with JS rendering."""
        try:
            browser = await self._get_browser()
            run_config = settings.get_run_config(use_cache=use_cache)
            result = await browser.arun(url, config=run_config)
            
            return FetchResult(
                url=url,
                html=result.html if result.success else "",
                success=result.success,
                status_code=200 if result.success else 0
            )
        except Exception as e:
            return FetchResult(url=url, error=str(e))
    
    def _needs_js(self, html: str) -> bool:
        """Check if page likely needs JavaScript rendering."""
        if not html:
            return True
        
        # Signs of JS-heavy page
        indicators = [
            "window.__INITIAL_STATE__",
            "react-root",
            "ng-app",
            "__NEXT_DATA__",
            "loading...",
        ]
        html_lower = html.lower()
        return any(ind.lower() in html_lower for ind in indicators)
    
    async def fetch_many(
        self,
        urls: List[str],
        mode: FetchMode = FetchMode.HTML
    ) -> List[FetchResult]:
        """Fetch multiple URLs concurrently."""
        tasks = [self.fetch(url, mode) for url in urls]
        return await asyncio.gather(*tasks)


@asynccontextmanager
async def get_crawler(**kwargs):
    """Context manager for CrawlerManager."""
    crawler = CrawlerManager(**kwargs)
    async with crawler:
        yield crawler
