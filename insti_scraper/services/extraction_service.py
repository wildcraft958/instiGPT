import json
import os
import re
from typing import List, Optional, Dict
from litellm import completion, completion_cost

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from insti_scraper.core.config import settings
from insti_scraper.core.prompts import Prompts
from insti_scraper.core.cost_tracker import cost_tracker
from insti_scraper.domain.models import Professor

import logging
logger = logging.getLogger(__name__)

class ExtractionService:
    def __init__(self):
        pass

    async def analyze_structure(self, url: str, html_content: str, model_name: str) -> dict:
        """
        Analyzes page structure to determine CSS selectors.
        Uses a cheaper model for this structural analysis.
        """
        # Truncate for analysis
        content_sample = html_content[:40000]
        
        response = completion(
            model=model_name,
            messages=[
                {'role': 'system', 'content': Prompts.CSS_DISCOVERY_SYSTEM},
                {'role': 'user', 'content': f"Analyze this HTML from {url} and return CSS selectors:\n\n{content_sample}"}
            ],
            response_format={"type": "json_object"},
            api_base=os.getenv("OLLAMA_BASE_URL") if "ollama" in model_name else None
        )
        
        # Track Cost
        try:
             cost = completion_cost(completion_response=response)
             cost_tracker.track_usage(
                 model_name, 
                 response.usage.prompt_tokens, 
                 response.usage.completion_tokens, 
                 cost
             )
        except:
             pass 

        content = response.choices[0].message.content
        return json.loads(content)

    async def extract_with_fallback(self, url: str, html_content: str) -> List[Professor]:
        """
        Extracts professors using a rigorous LLM approach if CSS fails.
        Forces high-reasoning model (GPT-4o/Claude) for this step.
        """
        model_name = settings.get_model_for_task("detail_extraction")
        
        # Smart Prompting: Explicitly filter out navigation links
        user_prompt = f"""Extract ALL ACADEMIC FACULTY from this page: {url}
        
        HTML Content:
        {html_content[:60000]} # Limit context window to save cost/avoid noise
        
        CRITICAL FILTERING:
        - IGNORE links like 'Home', 'Research', 'Calendar', 'Contact Us', 'Student Resources'.
        - IGNORE Staff/Admin profiles.
        - ONLY return people with academic titles (Professor, Lecturer, Fellow).
        
        Return JSON list of objects matching the schema."""
        
        response = completion(
            model=model_name,
            messages=[
                {'role': 'system', 'content': Prompts.EXTRACTION_SYSTEM},
                {'role': 'user', 'content': user_prompt}
            ],
            response_format={"type": "json_object"},
            api_base=os.getenv("OLLAMA_BASE_URL") if "ollama" in model_name else None
        )
        
        # Track Cost
        try:
             cost = completion_cost(completion_response=response)
             cost_tracker.track_usage(
                 model_name, 
                 response.usage.prompt_tokens, 
                 response.usage.completion_tokens, 
                 cost
             )
        except:
             pass

        try:
            content = response.choices[0].message.content
            raw_data = json.loads(content)
            
            # DEBUG LOG
            logger.info(f"      [LLM Response Keys]: {raw_data.keys() if isinstance(raw_data, dict) else 'LIST'}")
            
            # data content might be wrapped in a key like "faculty" or just a list
            if isinstance(raw_data, list):
                profiles_list = raw_data
            else:
                # Try common keys
                keys = ["faculty", "profiles", "professors", "people", "staff", "members"]
                profiles_list = []
                for k in keys:
                    if k in raw_data:
                        profiles_list = raw_data[k]
                        break
            
            logger.info(f"      [DEBUG] Raw extracted count: {len(profiles_list)}")
            
            valid_professors = []
            for p in profiles_list:
                name = p.get('name', '').strip()
                p_url = p.get('profile_url', '')
                
                # 1. Name Check is strict
                if self._is_garbage_link(name):
                    logger.info(f"      [FILTER] Skipped garbage name: {name}")
                    continue
                
                # 2. URL Check is loose (allow empty, handle garbage)
                # If URL is missing or garbage, generate a synthetic one to allow DB save
                if not p_url or self._is_garbage_link(p_url):
                    # Create synthetic URL using name hash to satisfy DB constraint
                    import hashlib
                    name_hash = hashlib.md5(name.encode()).hexdigest()[:8]
                    p_url = f"{url}#{name_hash}"
                
                valid_professors.append(Professor(
                    name=name,
                    profile_url=p_url,
                    title=p.get('title'),
                    email=p.get('email')
                ))
            return valid_professors
            
        except json.JSONDecodeError:
            return []

    def _is_garbage_link(self, text: str) -> bool:
        """Returns True if the text looks like a navigation link or noise."""
        if not text: return True
        
        dirty_keywords = [
            "calendar", "contact", "home", "research", "teaching", "academics", 
            "events", "news", "login", "sitemap", "about", "history", "apply"
        ]
        
        text_lower = text.lower()
        if any(w == text_lower for w in dirty_keywords):
            return True
        
        # Check for weird protocols or javascript links
        if "javascript:" in text_lower or "mailto:" in text_lower:
            return False # mailto is fine for email but not for profile_url, but here we check generic text
            
        return False
