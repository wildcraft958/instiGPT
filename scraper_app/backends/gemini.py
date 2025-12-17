"""
Gemini Backend - Cloud-based crawler using Google Gemini for planning
and Ollama llama3.2 for extraction.

Refactored from the original university_crawler.py
"""
import json
import logging
import os
from typing import List, Tuple, Optional

import google.genai as genai
import ollama
from bs4 import BeautifulSoup

import sys
sys.path.insert(0, '../..')
from models import ProfessorProfile
from prompts import GEMINI_ANALYSIS_PROMPT, GEMINI_CORRECTION_PROMPT, OLLAMA_EXTRACTION_PROMPT

from ..state import CrawlerState, NavigationAction, ActionType
from ..browser import BrowserManager
from ..config import settings
from ..utils import extract_json_from_response, html_to_markdown
from .base import BaseCrawlerBackend

logger = logging.getLogger(__name__)


class GeminiBackend(BaseCrawlerBackend):
    """
    Cloud-based backend using Google Gemini for page analysis/planning
    and Ollama llama3.2 for data extraction.
    
    This is the refactored version of the original university_crawler.py logic.
    """
    
    def __init__(self, browser: BrowserManager):
        super().__init__(browser)
        self.name = "gemini"
        
        # Initialize Gemini client
        self.gemini_client = None
        try:
            self.gemini_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
            self.gemini_client.models.list()  # Validate API key
            logger.info("✅ Gemini client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
        
        # Initialize Ollama client
        self.ollama_client = None
        try:
            ollama.pull(settings.OLLAMA_TEXT_MODEL)
            self.ollama_client = ollama.Client(host=settings.OLLAMA_URL)
            logger.info(f"✅ Ollama client initialized with {settings.OLLAMA_TEXT_MODEL}.")
        except Exception as e:
            logger.error(f"Failed to initialize Ollama client: {e}")
    
    def is_ready(self) -> bool:
        """Check if both LLM clients are initialized."""
        return self.gemini_client is not None and self.ollama_client is not None
    
    def plan_next_action(self, state: CrawlerState) -> NavigationAction:
        """
        Use Gemini to analyze the page and determine the next action.
        """
        if not self.gemini_client:
            logger.error("Gemini client not initialized")
            return NavigationAction(
                action_type=ActionType.FINISH,
                reason="Gemini client not available"
            )
        
        html_content = self.browser.get_html()
        current_url = self.browser.get_url()
        objective = state.get("objective", "")
        
        logger.info("🧠 Analyzing page with Gemini...")
        
        prompt = GEMINI_ANALYSIS_PROMPT.format(
            objective=objective,
            current_url=current_url,
            html_content=html_content[:50000]  # Limit token usage
        )
        
        try:
            response = self.gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            
            action_plan = extract_json_from_response(response.text)
            
            if not action_plan:
                return NavigationAction(
                    action_type=ActionType.FINISH,
                    reason="Failed to parse Gemini response"
                )
            
            logger.info(f"🤖 Gemini suggested action: {action_plan.get('action')}")
            return self._parse_action_plan(action_plan)
            
        except Exception as e:
            logger.error(f"Error analyzing page with Gemini: {e}")
            return NavigationAction(
                action_type=ActionType.FINISH,
                reason=f"Gemini analysis failed: {str(e)}"
            )
    
    def _parse_action_plan(self, plan: dict) -> NavigationAction:
        """Convert Gemini's response to a NavigationAction."""
        action = plan.get("action", "").upper()
        args = plan.get("args", {})
        
        # Map Gemini's action names to our ActionType
        action_mapping = {
            "NAVIGATE_TO_LIST": ActionType.EXTRACT_LIST,
            "EXTRACT_LIST": ActionType.EXTRACT_LIST,
            "EXTRACT_PROFILE": ActionType.EXTRACT_PROFILE,
            "CLICK": ActionType.CLICK,
            "NAVIGATE": ActionType.NAVIGATE,
            "FINISH": ActionType.FINISH,
        }
        
        action_type = action_mapping.get(action, ActionType.FINISH)
        
        return NavigationAction(
            action_type=action_type,
            selector=args.get("selector"),
            url=args.get("url"),
            reason=plan.get("reason", ""),
            card_selector=args.get("card_selector"),
            link_selector=args.get("link_selector"),
            name_selector=args.get("name_selector"),
            title_selector=args.get("title_selector"),
            next_page_selector=args.get("next_page_selector"),
            load_more_selector=args.get("load_more_selector"),
        )
    
    def extract_profiles(
        self,
        html_or_markdown: str,
        partial_profiles: Optional[List[ProfessorProfile]] = None
    ) -> List[ProfessorProfile]:
        """
        Use Ollama to extract faculty profiles from page content.
        """
        if not self.ollama_client:
            logger.error("Ollama client not initialized")
            return partial_profiles or []
        
        results = []
        profiles_to_process = partial_profiles or [ProfessorProfile(name="Unknown", title="Unknown", profile_url="")]
        
        for partial_profile in profiles_to_process:
            logger.info(f"🖋️ Extracting details for {partial_profile.name}...")
            
            # Convert HTML to clean text
            soup = BeautifulSoup(html_or_markdown, 'html.parser')
            main_content = soup.find('main') or soup.find('article') or soup.body
            page_text = main_content.get_text(separator='\n', strip=True) if main_content else html_or_markdown
            
            prompt = OLLAMA_EXTRACTION_PROMPT.format(
                partial_data=partial_profile.model_dump_json(indent=2),
                page_text_content=page_text[:20000]  # Limit token usage
            )
            
            try:
                response = self.ollama_client.generate(
                    model=settings.OLLAMA_TEXT_MODEL,
                    prompt=prompt
                )
                
                extracted_json = extract_json_from_response(response['response'])
                
                if extracted_json:
                    # Update profile with extracted data
                    updated_profile = partial_profile.model_copy(update=extracted_json)
                    logger.info(f"✅ Extracted profile for: {updated_profile.name}")
                    results.append(updated_profile)
                else:
                    logger.warning(f"Could not parse extraction for {partial_profile.name}")
                    results.append(partial_profile)
                    
            except Exception as e:
                logger.error(f"Error extracting data for {partial_profile.name}: {e}")
                results.append(partial_profile)
        
        return results
    
    def validate_action(self, action: NavigationAction) -> Tuple[bool, str]:
        """
        Validate that an action plan is well-formed.
        """
        if action.action_type == ActionType.CLICK:
            if not action.selector:
                return False, "CLICK action requires a selector"
        
        if action.action_type in [ActionType.EXTRACT_LIST]:
            required = ['card_selector', 'link_selector', 'name_selector', 'title_selector']
            missing = [k for k in required if not getattr(action, k)]
            if missing:
                return False, f"EXTRACT_LIST missing: {', '.join(missing)}"
        
        if action.action_type == ActionType.NAVIGATE:
            if not action.url:
                return False, "NAVIGATE action requires a URL"
        
        return True, "Valid"
    
    def request_correction(
        self,
        state: CrawlerState,
        failed_action: NavigationAction,
        failure_reason: str
    ) -> NavigationAction:
        """
        Request Gemini to provide a corrected action plan.
        """
        if not self.gemini_client:
            return NavigationAction(action_type=ActionType.FINISH, reason="No Gemini client")
        
        html_content = self.browser.get_html()
        current_url = self.browser.get_url()
        objective = state.get("objective", "")
        
        # Convert failed action to dict for prompt
        invalid_plan = {
            "action": failed_action.action_type.value,
            "args": {
                "selector": failed_action.selector,
                "card_selector": failed_action.card_selector,
                "link_selector": failed_action.link_selector,
                "name_selector": failed_action.name_selector,
                "title_selector": failed_action.title_selector,
            }
        }
        
        logger.info("🧠 Re-analyzing page with Gemini for a correction...")
        
        prompt = GEMINI_CORRECTION_PROMPT.format(
            objective=objective,
            current_url=current_url,
            invalid_plan=json.dumps(invalid_plan, indent=2),
            failure_reason=failure_reason,
            html_content=html_content[:50000]
        )
        
        try:
            response = self.gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            
            action_plan = extract_json_from_response(response.text)
            
            if action_plan:
                return self._parse_action_plan(action_plan)
            
        except Exception as e:
            logger.error(f"Error getting correction from Gemini: {e}")
        
        return NavigationAction(action_type=ActionType.FINISH, reason="Correction failed")
