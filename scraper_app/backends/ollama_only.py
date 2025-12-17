"""
Ollama-Only Backend - Uses Qwen3-VL for both planning and extraction.

Designed for Google Colab / resource-constrained environments where
running Gemini API is not desired.
"""
import json
import logging
import base64
from typing import List, Tuple, Optional

import ollama
from bs4 import BeautifulSoup

import sys
sys.path.insert(0, '../..')
from models import ProfessorProfile

from ..state import CrawlerState, NavigationAction, ActionType
from ..browser import BrowserManager
from ..config import settings
from ..utils import extract_json_from_response, html_to_markdown
from .base import BaseCrawlerBackend

logger = logging.getLogger(__name__)


# Prompts optimized for Qwen3-VL
QWEN_PLANNING_PROMPT = """Analyze this university faculty webpage screenshot.

Objective: {objective}
URL: {current_url}

Determine:
1. Is this a DIRECTORY (list of faculty) or a single PROFILE page?
2. Where are the clickable faculty links?
3. Is there a "Next" page or "Load More" button?

Return ONLY this JSON:
{{
    "page_type": "directory" or "profile",
    "action": "EXTRACT_LIST" or "EXTRACT_PROFILE" or "CLICK" or "FINISH",
    "card_selector": "CSS selector for faculty cards",
    "link_selector": "CSS selector for profile links",
    "name_selector": "CSS selector for names",
    "title_selector": "CSS selector for titles",
    "next_page_selector": "pagination selector or null",
    "reason": "brief explanation"
}}
"""

QWEN_EXTRACTION_PROMPT = """Extract professor information from this page content.

{markdown_content}

Return ONLY this JSON (omit fields without data):
{{
    "name": "Full Name",
    "title": "Position/Title",
    "email": "email@university.edu",
    "research_interests": ["area1", "area2"],
    "publications": ["pub1", "pub2"],
    "lab": "Lab name",
    "description": "Short bio",
    "image_url": "photo URL"
}}
"""

QWEN_TEXT_PLANNING_PROMPT = """Analyze this faculty webpage HTML to plan scraping.

Objective: {objective}
URL: {current_url}

HTML (truncated):
{html_content}

Common patterns to look for:
- Faculty cards: .faculty-card, .person-card, .profile-card
- Links: a.profile-link, a[href*="faculty"], a[href*="people"]
- Names: h2, h3, .name, .faculty-name
- Titles: .title, .position, .role
- Pagination: .next, .pagination a, .load-more

Return ONLY JSON:
{{
    "action": "EXTRACT_LIST" or "EXTRACT_PROFILE" or "CLICK" or "FINISH",
    "card_selector": "selector for cards",
    "link_selector": "selector for links",
    "name_selector": "selector for names",
    "title_selector": "selector for titles",
    "next_page_selector": "pagination selector or null",
    "reason": "explanation"
}}
"""


class OllamaOnlyBackend(BaseCrawlerBackend):
    """
    Ollama-only backend using Qwen3-VL for everything.
    No Gemini dependency - works completely offline.
    
    Ideal for:
    - Google Colab environments
    - Offline/air-gapped systems
    - Cost-free operation
    """
    
    def __init__(self, browser: BrowserManager):
        super().__init__(browser)
        self.name = "ollama_only"
        
        self.client = None
        self.model = settings.OLLAMA_VISION_MODEL  # qwen3-vl
        
        try:
            self.client = ollama.Client(host=settings.OLLAMA_URL)
            logger.info(f"✅ Ollama client connected to {settings.OLLAMA_URL}")
            
            # Try to pull model if not available
            try:
                self.client.show(self.model)
                logger.info(f"✅ Model {self.model} ready")
            except:
                logger.info(f"📦 Pulling {self.model}...")
                ollama.pull(self.model)
                logger.info(f"✅ Model {self.model} pulled successfully")
                
        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {e}")
    
    def is_ready(self) -> bool:
        """Check if Ollama is available."""
        return self.client is not None
    
    def _vision_request(self, prompt: str, screenshot_b64: str) -> Optional[dict]:
        """Send vision request to Qwen3-VL."""
        try:
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                images=[screenshot_b64]
            )
            return extract_json_from_response(response['response'])
        except Exception as e:
            logger.error(f"Vision request failed: {e}")
            return None
    
    def _text_request(self, prompt: str) -> Optional[dict]:
        """Send text-only request."""
        try:
            response = self.client.generate(
                model=self.model,
                prompt=prompt
            )
            return extract_json_from_response(response['response'])
        except Exception as e:
            logger.error(f"Text request failed: {e}")
            return None
    
    def plan_next_action(self, state: CrawlerState) -> NavigationAction:
        """Use Qwen3-VL to analyze the page and plan next action."""
        if not self.client:
            return NavigationAction(action_type=ActionType.FINISH, reason="Ollama not available")
        
        current_url = self.browser.get_url()
        objective = state.get("objective", "")
        
        logger.info("👁️ Analyzing page with Qwen3-VL...")
        
        # Try vision-based planning first
        result = None
        try:
            screenshot_b64 = self.browser.screenshot_base64()
            logger.info(f"📸 Screenshot captured ({len(screenshot_b64)} bytes)")
            
            prompt = QWEN_PLANNING_PROMPT.format(
                objective=objective,
                current_url=current_url
            )
            result = self._vision_request(prompt, screenshot_b64)
            
            if result:
                logger.info(f"✅ Vision response: action={result.get('action')}, card_selector={result.get('card_selector')}")
            else:
                logger.warning("⚠️ Vision request returned None/empty")
                
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}, trying text-based planning")
        
        # Fallback to text-based planning
        if not result:
            logger.info("📝 Falling back to text-based planning...")
            html = self.browser.get_html()
            logger.info(f"📄 Got HTML ({len(html)} chars)")
            
            prompt = QWEN_TEXT_PLANNING_PROMPT.format(
                objective=objective,
                current_url=current_url,
                html_content=html[:30000]
            )
            result = self._text_request(prompt)
            
            if result:
                logger.info(f"✅ Text response: action={result.get('action')}, card_selector={result.get('card_selector')}")
            else:
                logger.warning("⚠️ Text request also returned None/empty")
        
        if not result:
            return NavigationAction(action_type=ActionType.FINISH, reason="Planning failed - no response")
        
        # Parse result into NavigationAction
        action_str = result.get("action", "FINISH").upper()
        action_mapping = {
            "EXTRACT_LIST": ActionType.EXTRACT_LIST,
            "EXTRACT_PROFILE": ActionType.EXTRACT_PROFILE,
            "CLICK": ActionType.CLICK,
            "FINISH": ActionType.FINISH,
        }
        
        card_sel = result.get("card_selector") or ""
        link_sel = result.get("link_selector") or ""
        name_sel = result.get("name_selector") or ""
        title_sel = result.get("title_selector") or ""
        
        logger.info(f"🎯 Parsed selectors: card='{card_sel}', link='{link_sel}', name='{name_sel}'")
        
        return NavigationAction(
            action_type=action_mapping.get(action_str, ActionType.FINISH),
            reason=result.get("reason", ""),
            card_selector=card_sel if card_sel else None,
            link_selector=link_sel if link_sel else None,
            name_selector=name_sel if name_sel else None,
            title_selector=title_sel if title_sel else None,
            next_page_selector=result.get("next_page_selector"),
        )
    
    def extract_profiles(
        self,
        html_or_markdown: str,
        partial_profiles: Optional[List[ProfessorProfile]] = None
    ) -> List[ProfessorProfile]:
        """Extract profiles using Qwen3-VL."""
        if not self.client:
            return partial_profiles or []
        
        # Convert to markdown for cleaner extraction
        if html_or_markdown.strip().startswith('<'):
            markdown = html_to_markdown(html_or_markdown)
        else:
            markdown = html_or_markdown
        
        results = []
        profiles_to_process = partial_profiles or [
            ProfessorProfile(name="Unknown", title="Unknown", profile_url="")
        ]
        
        for partial in profiles_to_process:
            logger.info(f"🖋️ Extracting: {partial.name}")
            
            prompt = QWEN_EXTRACTION_PROMPT.format(
                markdown_content=markdown[:15000]
            )
            
            extracted = self._text_request(prompt)
            
            if extracted:
                updated = partial.model_copy(update=extracted)
                logger.info(f"✅ Extracted: {updated.name}")
                results.append(updated)
            else:
                results.append(partial)
        
        return results
    
    def validate_action(self, action: NavigationAction) -> Tuple[bool, str]:
        """Validate action - Ollama backend is lenient."""
        if action.action_type == ActionType.FINISH:
            return True, "Valid"
        
        if action.action_type == ActionType.CLICK and not action.selector:
            return False, "CLICK requires selector"
        
        return True, "Valid"
    
    def request_correction(
        self,
        state: CrawlerState,
        failed_action: NavigationAction,
        failure_reason: str
    ) -> NavigationAction:
        """Try to get a corrected action."""
        logger.info(f"🔄 Correcting after: {failure_reason}")
        
        # Take fresh screenshot and re-analyze
        try:
            screenshot_b64 = self.browser.screenshot_base64()
            prompt = f"""Previous action failed: {failure_reason}
Failed selector: {failed_action.selector}

Look at the page again and suggest alternative selectors.
Return JSON with new selectors."""
            
            result = self._vision_request(prompt, screenshot_b64)
            if result:
                return NavigationAction(
                    action_type=ActionType.EXTRACT_LIST,
                    card_selector=result.get("card_selector"),
                    link_selector=result.get("link_selector"),
                    name_selector=result.get("name_selector"),
                    title_selector=result.get("title_selector"),
                    reason="Correction attempt",
                )
        except:
            pass
        
        return NavigationAction(action_type=ActionType.FINISH, reason="Correction failed")
