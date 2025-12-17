"""
Abstract base class for crawler backends.
"""
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional

import sys
sys.path.insert(0, '..')
from models import ProfessorProfile

from ..state import CrawlerState, NavigationAction
from ..browser import BrowserManager


class BaseCrawlerBackend(ABC):
    """
    Abstract base class for crawler backends.
    
    Implements the Strategy Pattern - different backends can be swapped
    without changing the orchestration logic.
    """
    
    def __init__(self, browser: BrowserManager):
        """
        Initialize the backend with a shared browser manager.
        
        Args:
            browser: Shared BrowserManager instance
        """
        self.browser = browser
        self.name = "base"  # Override in subclasses
    
    @abstractmethod
    def plan_next_action(self, state: CrawlerState) -> NavigationAction:
        """
        Analyze the current page and determine the next navigation action.
        
        Uses either HTML analysis (Gemini) or visual analysis (Vision models)
        to understand page structure and decide what to do next.
        
        Args:
            state: Current crawler state
        
        Returns:
            NavigationAction describing what to do next
        """
        pass
    
    @abstractmethod
    def extract_profiles(
        self,
        html_or_markdown: str,
        partial_profiles: Optional[List[ProfessorProfile]] = None
    ) -> List[ProfessorProfile]:
        """
        Extract faculty profiles from page content.
        
        Args:
            html_or_markdown: Page content (HTML or Markdown depending on backend)
            partial_profiles: Optional list of partially-filled profiles to complete
        
        Returns:
            List of extracted ProfessorProfile objects
        """
        pass
    
    @abstractmethod
    def validate_action(self, action: NavigationAction) -> Tuple[bool, str]:
        """
        Validate that an action plan is well-formed and executable.
        
        Args:
            action: The action to validate
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        pass
    
    def request_correction(
        self,
        state: CrawlerState,
        failed_action: NavigationAction,
        failure_reason: str
    ) -> NavigationAction:
        """
        Request a corrected action plan after a failure.
        
        Default implementation just calls plan_next_action again.
        Subclasses can override for more sophisticated self-correction.
        
        Args:
            state: Current crawler state
            failed_action: The action that failed
            failure_reason: Why it failed
        
        Returns:
            New NavigationAction
        """
        # Default: just try planning again
        return self.plan_next_action(state)
    
    def get_page_context(self, state: CrawlerState) -> dict:
        """
        Get context information about the current page.
        
        Returns:
            Dict with url, html, screenshot_b64, and markdown
        """
        html = self.browser.get_html()
        
        return {
            "url": self.browser.get_url(),
            "html": html,
            "screenshot_b64": self.browser.screenshot_base64() if hasattr(self.browser, 'screenshot_base64') else None,
            "markdown": state.get("last_markdown"),
        }
