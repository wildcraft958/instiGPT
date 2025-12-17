"""
Ollama Vision Backend - Local vision-based crawler using Qwen3-VL.

This backend "sees" the page like a human via screenshots, making it more
resilient to unusual HTML structures.
"""
import json
import logging
import base64
from typing import List, Tuple, Optional

import ollama

import sys
sys.path.insert(0, '../..')
from models import ProfessorProfile

from ..state import CrawlerState, NavigationAction, ActionType
from ..browser import BrowserManager
from ..config import settings
from ..utils import extract_json_from_response, html_to_markdown
from .base import BaseCrawlerBackend

logger = logging.getLogger(__name__)


# Vision-specific prompts
VISION_PLANNING_PROMPT = """You are a web crawler agent analyzing a university faculty directory page.

**Objective:** {objective}
**Current URL:** {current_url}

Look at this screenshot of a webpage. Your job is to identify:
1. Is this a faculty DIRECTORY page (list of multiple professors) or a single PROFILE page?
2. Where are the clickable links to individual professor profiles?
3. Is there pagination (Next button, page numbers, or "Load More")?

Respond with a JSON object:
{{
    "page_type": "directory" | "profile" | "other",
    "faculty_links_description": "Description of where faculty profile links are located",
    "faculty_link_pattern": "CSS selector or description of the clickable element",
    "pagination": {{
        "has_next": true/false,
        "type": "numbered" | "load_more" | "none",
        "selector_description": "Description of the next/load more button"
    }},
    "recommended_action": "EXTRACT_LIST" | "EXTRACT_PROFILE" | "CLICK" | "FINISH",
    "reason": "Brief explanation"
}}
"""

VISION_EXTRACTION_PROMPT = """Extract faculty information from this professor's profile page.

The page content (in Markdown format):
{markdown_content}

Extract and return a JSON object with these fields:
{{
    "name": "Full name of the professor",
    "title": "Job title or position",
    "email": "Email address if visible",
    "research_interests": ["List", "of", "research", "areas"],
    "publications": ["Recent publication titles if visible"],
    "lab": "Lab name if mentioned",
    "description": "Brief bio or description",
    "image_url": "Profile photo URL if found"
}}

Only include fields that you can actually find in the content. Leave missing fields as null.
Return ONLY the JSON object, no other text.
"""

VISION_SELECTOR_PROMPT = """Look at this screenshot of a webpage.

I need to click on faculty/professor profile links. Based on what you see:
1. Describe where the clickable names/links are
2. Suggest a CSS selector that would match these elements
3. Are there multiple faculty members visible?

Respond with JSON:
{{
    "visible_faculty_count": number,
    "link_location": "description of where links are",
    "suggested_selector": "CSS selector suggestion",
    "fallback_selector": "alternative CSS selector",
    "confidence": "high" | "medium" | "low"
}}
"""


class OllamaVisionBackend(BaseCrawlerBackend):
    """
    Local vision-based backend using Qwen3-VL for visual understanding.
    
    Key advantage: "Sees" the page like a human, making it robust against
    unusual HTML structures or heavily nested DOM trees.
    """
    
    def __init__(self, browser: BrowserManager):
        super().__init__(browser)
        self.name = "ollama_vision"
        
        # Initialize Ollama client
        self.client = None
        self.vision_model = settings.OLLAMA_VISION_MODEL
        self.text_model = settings.OLLAMA_TEXT_MODEL
        
        try:
            self.client = ollama.Client(host=settings.OLLAMA_URL)
            
            # Try to pull the vision model
            logger.info(f"📦 Checking for {self.vision_model}...")
            try:
                ollama.pull(self.vision_model)
                logger.info(f"✅ Vision model {self.vision_model} ready.")
            except Exception as e:
                logger.warning(f"Could not pull {self.vision_model}: {e}")
                logger.info("Trying to use existing model...")
            
            logger.info("✅ Ollama Vision client initialized.")
            
        except Exception as e:
            logger.error(f"Failed to initialize Ollama client: {e}")
    
    def is_ready(self) -> bool:
        """Check if the Ollama client is initialized."""
        return self.client is not None
    
    def _send_vision_request(self, prompt: str, image_b64: str) -> Optional[dict]:
        """Send a vision request to the model."""
        try:
            response = self.client.generate(
                model=self.vision_model,
                prompt=prompt,
                images=[image_b64]
            )
            return extract_json_from_response(response['response'])
        except Exception as e:
            logger.error(f"Vision request failed: {e}")
            return None
    
    def plan_next_action(self, state: CrawlerState) -> NavigationAction:
        """
        Use vision model to analyze a screenshot and determine next action.
        """
        if not self.client:
            return NavigationAction(
                action_type=ActionType.FINISH,
                reason="Ollama client not available"
            )
        
        current_url = self.browser.get_url()
        objective = state.get("objective", "")
        
        logger.info("👁️ Analyzing page visually with Qwen3-VL...")
        
        # Take screenshot
        screenshot_b64 = self.browser.screenshot_base64()
        
        prompt = VISION_PLANNING_PROMPT.format(
            objective=objective,
            current_url=current_url
        )
        
        result = self._send_vision_request(prompt, screenshot_b64)
        
        if not result:
            # Fallback: try text-based analysis
            logger.warning("Vision analysis failed, trying text fallback...")
            return self._text_based_planning(state)
        
        logger.info(f"👁️ Vision analysis: {result.get('page_type')} page, action: {result.get('recommended_action')}")
        
        # Convert vision result to NavigationAction
        action = result.get("recommended_action", "FINISH").upper()
        
        action_mapping = {
            "EXTRACT_LIST": ActionType.EXTRACT_LIST,
            "EXTRACT_PROFILE": ActionType.EXTRACT_PROFILE,
            "CLICK": ActionType.CLICK,
            "FINISH": ActionType.FINISH,
        }
        
        action_type = action_mapping.get(action, ActionType.FINISH)
        
        # For EXTRACT_LIST, we need to get selectors
        if action_type == ActionType.EXTRACT_LIST:
            selectors = self._get_faculty_selectors(screenshot_b64)
            if selectors:
                return NavigationAction(
                    action_type=action_type,
                    reason=result.get("reason", ""),
                    card_selector=selectors.get("suggested_selector"),
                    link_selector=selectors.get("suggested_selector") + " a",
                    name_selector="a",  # Usually the link itself contains the name
                    title_selector=selectors.get("fallback_selector", "span"),
                    next_page_selector=self._get_pagination_selector(result),
                )
        
        return NavigationAction(
            action_type=action_type,
            selector=result.get("faculty_link_pattern"),
            reason=result.get("reason", ""),
        )
    
    def _get_faculty_selectors(self, screenshot_b64: str) -> Optional[dict]:
        """Get CSS selectors for faculty elements using vision."""
        result = self._send_vision_request(VISION_SELECTOR_PROMPT, screenshot_b64)
        return result
    
    def _get_pagination_selector(self, vision_result: dict) -> Optional[str]:
        """Extract pagination selector from vision analysis."""
        pagination = vision_result.get("pagination", {})
        if pagination.get("has_next"):
            # The vision model gives descriptions, we'll need to find the actual selector
            # This is a simplified version - real implementation would do more sophisticated matching
            return pagination.get("selector_description")
        return None
    
    def _text_based_planning(self, state: CrawlerState) -> NavigationAction:
        """Fallback: use text model to analyze HTML."""
        html = self.browser.get_html()
        markdown = html_to_markdown(html)
        
        prompt = f"""Analyze this webpage content and determine the next action for scraping faculty data.

Objective: {state.get('objective', '')}
Current URL: {self.browser.get_url()}

Page content (Markdown):
{markdown[:15000]}

Respond with JSON:
{{
    "action": "EXTRACT_LIST" | "EXTRACT_PROFILE" | "CLICK" | "FINISH",
    "reason": "brief explanation",
    "suggested_selector": "CSS selector if applicable"
}}
"""
        try:
            response = self.client.generate(model=self.text_model, prompt=prompt)
            result = extract_json_from_response(response['response'])
            
            if result:
                action = result.get("action", "FINISH").upper()
                action_mapping = {
                    "EXTRACT_LIST": ActionType.EXTRACT_LIST,
                    "EXTRACT_PROFILE": ActionType.EXTRACT_PROFILE,
                    "CLICK": ActionType.CLICK,
                    "FINISH": ActionType.FINISH,
                }
                return NavigationAction(
                    action_type=action_mapping.get(action, ActionType.FINISH),
                    selector=result.get("suggested_selector"),
                    reason=result.get("reason", ""),
                )
        except Exception as e:
            logger.error(f"Text-based planning failed: {e}")
        
        return NavigationAction(action_type=ActionType.FINISH, reason="Planning failed")
    
    def extract_profiles(
        self,
        html_or_markdown: str,
        partial_profiles: Optional[List[ProfessorProfile]] = None
    ) -> List[ProfessorProfile]:
        """
        Extract faculty profiles using vision or text model.
        
        Converts HTML to Markdown first for cleaner extraction.
        """
        if not self.client:
            return partial_profiles or []
        
        # Convert to Markdown if it looks like HTML
        if html_or_markdown.strip().startswith('<'):
            markdown = html_to_markdown(html_or_markdown)
        else:
            markdown = html_or_markdown
        
        results = []
        profiles_to_process = partial_profiles or [ProfessorProfile(name="Unknown", title="Unknown", profile_url="")]
        
        for partial_profile in profiles_to_process:
            logger.info(f"🖋️ Extracting details for {partial_profile.name}...")
            
            prompt = VISION_EXTRACTION_PROMPT.format(
                markdown_content=markdown[:20000]
            )
            
            try:
                response = self.client.generate(model=self.text_model, prompt=prompt)
                extracted_json = extract_json_from_response(response['response'])
                
                if extracted_json:
                    # Merge with partial profile
                    updated_profile = partial_profile.model_copy(update=extracted_json)
                    logger.info(f"✅ Extracted profile for: {updated_profile.name}")
                    results.append(updated_profile)
                else:
                    results.append(partial_profile)
                    
            except Exception as e:
                logger.error(f"Extraction failed for {partial_profile.name}: {e}")
                results.append(partial_profile)
        
        return results
    
    def validate_action(self, action: NavigationAction) -> Tuple[bool, str]:
        """
        Validate action - vision backend is more lenient since it can
        adaptively find elements.
        """
        if action.action_type == ActionType.FINISH:
            return True, "Valid"
        
        # For vision backend, we're more lenient since it can adapt
        if action.action_type == ActionType.CLICK and not action.selector:
            return False, "CLICK needs a selector"
        
        return True, "Valid"
    
    def request_correction(
        self,
        state: CrawlerState,
        failed_action: NavigationAction,
        failure_reason: str
    ) -> NavigationAction:
        """
        Vision backend can take a new screenshot and try again.
        """
        logger.info(f"🔄 Attempting correction after: {failure_reason}")
        
        # Take a fresh screenshot and re-analyze
        screenshot_b64 = self.browser.screenshot_base64()
        
        prompt = f"""The previous action failed: {failure_reason}
        
Previous attempted selector: {failed_action.selector}

Look at the current page screenshot and suggest an alternative way to:
1. Find faculty/professor profiles
2. Navigate to individual profile pages

Respond with JSON:
{{
    "alternative_selector": "new CSS selector to try",
    "action": "CLICK" | "EXTRACT_LIST" | "FINISH",
    "reason": "explanation"
}}
"""
        
        result = self._send_vision_request(prompt, screenshot_b64)
        
        if result:
            action = result.get("action", "FINISH").upper()
            action_mapping = {
                "EXTRACT_LIST": ActionType.EXTRACT_LIST,
                "CLICK": ActionType.CLICK,
                "FINISH": ActionType.FINISH,
            }
            return NavigationAction(
                action_type=action_mapping.get(action, ActionType.FINISH),
                selector=result.get("alternative_selector"),
                reason=result.get("reason", "Correction attempt"),
            )
        
        return NavigationAction(action_type=ActionType.FINISH, reason="Correction failed")
