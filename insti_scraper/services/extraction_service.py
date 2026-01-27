import json
import os
import re
from typing import List, Optional, Dict
from litellm import completion, completion_cost
from litellm.exceptions import RateLimitError

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from insti_scraper.core.config import settings
from insti_scraper.core.prompts import Prompts
from insti_scraper.core.cost_tracker import cost_tracker
from insti_scraper.domain.models import Professor
from insti_scraper.core.schema_cache import get_schema_cache, SelectorSchema
from insti_scraper.core.retry_wrapper import retry_async, DEFAULT_RETRY_CONFIG
from insti_scraper.analyzers.vision_analyzer import VisionPageAnalyzer

import logging
logger = logging.getLogger(__name__)

class ExtractionService:
    def __init__(self):
        self.vision_analyzer = VisionPageAnalyzer()
        self.force_local = False

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

    @retry_async(DEFAULT_RETRY_CONFIG)
    async def extract_with_fallback(self, url: str, html_content: str) -> tuple[List[Professor], str]:
        """
        Extracts professors and department context using a rigorous LLM approach.
        Returns: (List[Professor], department_name)
        """
        model_name = settings.get_model_for_task("detail_extraction")
        
        # 0. Check Schema Cache
        schema_cache = get_schema_cache()
        cached_schema = schema_cache.get(url)
        if cached_schema:
            logger.info(f"      [Cache] Found existing schema for {url}")
            # TODO: Implement selector-based extraction using cached_schema
            # For now, we fall back to LLM but this acknowledges the cache exists
        else:
            # 1. Vision Analysis for Schema Discovery
            logger.info(f"      [Vision] Analyzing page structure for {url}...")
            try:
                vision_result = await self.vision_analyzer.analyze(url)
                if vision_result.schema_hints:
                    logger.info(f"      [Vision] Found schema hints: {vision_result.schema_hints.keys()}")
                    # We can use these hints to guide the LLM or save a new schema
                    # For now, we'll append hints to the prompt context
                    html_content = f"VISION_HINTS: {json.dumps(vision_result.schema_hints)}\n\n" + html_content
            except Exception as e:
                logger.warning(f"      [Vision] Analysis failed (ignoring): {e}")

        # Smart Prompting: Explicitly filter out navigation links
        user_prompt = f"""Extract ALL ACADEMIC FACULTY from this page: {url}
        
        HTML Content:
        {html_content[:60000]} # Limit context window
        
        CRITICAL INSTRUCTIONS:
        1. **Department Context**: Analyze the page title/header to infer the specific Department Name (e.g., "Computer Science", "Electrical Engineering"). Return this as top-level key 'department_name'.
        2. **Rich Data**: For each faculty member, extract:
           - publications: A short string summary (e.g. "Top papers in AI/ML") or list of top papers.
           - research_interests: List of strings.
           - education: String detail (e.g. "PhD from MIT").
        3. **Filtering**: IGNORE Admin/Staff/Students.
        
        Return JSON object with keys: "department_name", "faculty" (list of objects)."""
        
        # Check if we are forced to local model due to previous rate limits
        if self.force_local:
             model_name = settings.get_model_for_task("detail_extraction", prefer_local=True)
             logger.info(f"      [Fallback] Using local model: {model_name}")

        try:
            response = completion(
                model=model_name,
                messages=[
                    {'role': 'system', 'content': Prompts.EXTRACTION_SYSTEM},
                    {'role': 'user', 'content': user_prompt}
                ],
                response_format={"type": "json_object"},
                api_base=os.getenv("OLLAMA_BASE_URL") if "ollama" in model_name else None
            )
        except RateLimitError:
            logger.error("      ⚠️ OpenAI Quota Exceeded! Switching to local model (Ollama) for this and future requests.")
            self.force_local = True
            model_name = settings.get_model_for_task("detail_extraction", prefer_local=True)
            
            # Double check: if config still gave us OpenAI, force Ollama
            if "openai" in model_name.lower():
                 model_name = "ollama/llama3.1:8b"
                 logger.warning("      ⚠️ Config returned OpenAI model for local fallback. Forcing 'ollama/llama3.1:8b'.")

            # Retry with local model
            response = completion(
                model=model_name,
                messages=[
                    {'role': 'system', 'content': Prompts.EXTRACTION_SYSTEM},
                    {'role': 'user', 'content': user_prompt}
                ],
                response_format={"type": "json_object"},
                api_base=os.getenv("OLLAMA_BASE_URL")
            )
        
        # Track Cost
        try:
             cost = completion_cost(completion_response=response)
             cost_tracker.track_usage(model_name, response.usage.prompt_tokens, response.usage.completion_tokens, cost)
        except:
             pass

        try:
            content = response.choices[0].message.content
            raw_data = json.loads(content)
            
            logger.info(f"      [LLM Response Keys]: {raw_data.keys() if isinstance(raw_data, dict) else 'LIST'}")
            
            # Extract Department logic
            department_name = "General"
            if isinstance(raw_data, dict):
                department_name = raw_data.get("department_name", "General")
                profiles_list = raw_data.get("faculty") or raw_data.get("profiles") or []
            else:
                profiles_list = raw_data if isinstance(raw_data, list) else []
            
            logger.info(f"      [DEBUG] Inferred Department: {department_name}")
            logger.info(f"      [DEBUG] Raw extracted count: {len(profiles_list)}")
            
            valid_professors = []
            for p in profiles_list:
                name = p.get('name', '').strip()
                p_url = p.get('profile_url', '')
                
                # 1. Name Check is strict
                if self._is_garbage_link(name):
                    logger.info(f"      [FILTER] Skipped garbage name: {name}")
                    continue
                
                # 2. URL Check
                if not p_url or self._is_garbage_link(p_url):
                    p_url = None
                
                # Handle dictionary or string for rich fields if schema varies
                res_ints = p.get('research_interests', [])
                if isinstance(res_ints, str): res_ints = [res_ints]
                
                valid_professors.append(Professor(
                    name=name,
                    profile_url=p_url,
                    title=p.get('title'),
                    email=p.get('email'),
                    research_interests=res_ints,
                    publication_summary=p.get('publications') if isinstance(p.get('publications'), str) else str(p.get('publications')),
                    education=p.get('education')
                ))
            return valid_professors, department_name
            
        except json.JSONDecodeError:
            return [], "General"
            
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
