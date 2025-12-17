"""
Shared Playwright browser management with stealth settings.
"""
import os
import base64
import logging
from pathlib import Path
from typing import Optional
from playwright.sync_api import sync_playwright, Page, BrowserContext, Playwright

from .config import settings

logger = logging.getLogger(__name__)


class BrowserManager:
    """
    Manages Playwright browser instance with stealth settings.
    Shared between all backends.
    """
    
    def __init__(self, headless: Optional[bool] = None):
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # Auto-detect headless mode if not specified
        if headless is None:
            self.headless = settings.is_colab_or_headless_env() or settings.HEADLESS_MODE
        else:
            self.headless = headless
            
        self._user_data_dir = Path.home() / ".playwright_user_data"
        
    def setup(self) -> Page:
        """Initialize browser with stealth settings. Returns the main page."""
        if self.playwright:
            return self.page
            
        logger.info("🔧 Setting up browser...")
        self.playwright = sync_playwright().__enter__()
        
        # Create user data directory for persistent context
        self._user_data_dir.mkdir(exist_ok=True)
        
        # Launch options
        launch_args = ["--start-maximized", "--disable-blink-features=AutomationControlled"]
        if self.headless:
            launch_args.append("--headless=new")
        
        self.context = self.playwright.chromium.launch_persistent_context(
            str(self._user_data_dir),
            headless=self.headless,
            user_agent=settings.USER_AGENT,
            args=launch_args,
            ignore_https_errors=True,
            viewport={"width": settings.VIEWPORT_WIDTH, "height": settings.VIEWPORT_HEIGHT}
        )
        
        self.page = self.context.new_page()
        self.page.set_default_timeout(settings.PAGE_TIMEOUT_MS)
        
        logger.info(f"✅ Browser setup complete (headless={self.headless})")
        return self.page
    
    def navigate(self, url: str, wait_until: str = "domcontentloaded") -> None:
        """Navigate to a URL and wait for load."""
        if not self.page:
            raise RuntimeError("Browser not initialized. Call setup() first.")
        
        logger.info(f"🌐 Navigating to: {url}")
        self.page.goto(url, wait_until=wait_until)
        
    def get_html(self) -> str:
        """Get the current page HTML content."""
        if not self.page:
            raise RuntimeError("Browser not initialized. Call setup() first.")
        return self.page.content()
    
    def get_url(self) -> str:
        """Get the current page URL."""
        if not self.page:
            raise RuntimeError("Browser not initialized. Call setup() first.")
        return self.page.url
    
    def take_screenshot(self, save_path: Optional[str] = None) -> bytes:
        """
        Take a screenshot of the current page.
        Returns the screenshot as bytes.
        Optionally saves to a file.
        """
        if not self.page:
            raise RuntimeError("Browser not initialized. Call setup() first.")
        
        screenshot = self.page.screenshot(full_page=False)
        
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(screenshot)
            logger.debug(f"📸 Screenshot saved to: {save_path}")
            
        return screenshot
    
    def screenshot_base64(self) -> str:
        """Take a screenshot and return as base64 string for LLM consumption."""
        screenshot = self.take_screenshot()
        return base64.b64encode(screenshot).decode("utf-8")
    
    def click(self, selector: str) -> None:
        """Click on an element matching the selector."""
        if not self.page:
            raise RuntimeError("Browser not initialized. Call setup() first.")
        
        logger.info(f"🖱️ Clicking: {selector}")
        self.page.click(selector)
        self.page.wait_for_load_state("domcontentloaded")
        
    def query_selector_all(self, selector: str):
        """Query all elements matching selector."""
        if not self.page:
            raise RuntimeError("Browser not initialized. Call setup() first.")
        return self.page.query_selector_all(selector)
    
    def query_selector(self, selector: str):
        """Query single element matching selector."""
        if not self.page:
            raise RuntimeError("Browser not initialized. Call setup() first.")
        return self.page.query_selector(selector)
    
    def new_page(self) -> Page:
        """Create a new page in the same context."""
        if not self.context:
            raise RuntimeError("Browser not initialized. Call setup() first.")
        return self.context.new_page()
    
    def go_back(self) -> None:
        """Navigate back in history."""
        if not self.page:
            raise RuntimeError("Browser not initialized. Call setup() first.")
        self.page.go_back()
        self.page.wait_for_load_state("domcontentloaded")
    
    def cleanup(self) -> None:
        """Clean up browser resources."""
        if self.context:
            self.context.close()
            self.context = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None
        self.page = None
        logger.info("🧹 Browser cleaned up.")
        
    def __enter__(self):
        self.setup()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False
