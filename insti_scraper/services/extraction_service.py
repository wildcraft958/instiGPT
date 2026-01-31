import json
import os
import re
from typing import List, Optional, Dict, Tuple
from litellm import completion, completion_cost
from litellm.exceptions import RateLimitError

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from insti_scraper.core.config import settings
from insti_scraper.core.prompts import Prompts
from insti_scraper.core.cost_tracker import cost_tracker
from insti_scraper.domain.models import Professor
from insti_scraper.core.schema_cache import get_schema_cache, SelectorSchema
from insti_scraper.core.retry_wrapper import retry_async, DEFAULT_RETRY_CONFIG
from insti_scraper.analyzers.vision_analyzer import VisionPageAnalyzer, PageType, BlockType, VisualAnalysisResult

import logging
logger = logging.getLogger(__name__)

class ExtractionService:
    def __init__(self):
        self.vision_analyzer = VisionPageAnalyzer()
        self.force_local = False
        self._last_vision_result: Optional[VisualAnalysisResult] = None

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

    async def analyze_page(self, url: str) -> Tuple[VisualAnalysisResult, str]:
        """
        Run vision analysis on a URL and return classification status.
        
        Returns:
            Tuple of (VisualAnalysisResult, status_message)
            Status can be: "ok", "blocked", "gateway", "paginated"
        """
        try:
            result = await self.vision_analyzer.analyze(url)
            self._last_vision_result = result
            
            # Check for blocked access
            if result.is_blocked():
                block_msg = f"Page blocked: {result.block_type.value} - {result.block_description}"
                logger.warning(f"      ❌ {block_msg}")
                return result, "blocked"
            
            # Check page type
            page_type = result.page_type
            
            if page_type == PageType.DEPARTMENT_GATEWAY:
                logger.info(f"      📂 Detected Department Gateway (Type C) - needs deeper crawling")
                return result, "gateway"
            
            if page_type == PageType.PAGINATED_LIST:
                logger.info(f"      📄 Detected Paginated List (Type D) - {result.max_pages_needed} pages estimated")
                return result, "paginated"
            
            if page_type == PageType.INDIVIDUAL_PROFILE:
                logger.info(f"      👤 Detected Individual Profile (Type F) - not a directory")
                return result, "profile"
            
            # Normal directory pages (Type A/B)
            logger.info(f"      ✅ Page Type: {page_type.value} (confidence: {result.page_type_confidence:.0%})")
            return result, "ok"
            
        except Exception as e:
            logger.warning(f"      ⚠️ Vision analysis failed: {e}")
            return VisualAnalysisResult(), "ok"  # Fall back to extraction anyway

    @retry_async(DEFAULT_RETRY_CONFIG)
    async def extract_with_fallback(self, url: str, html_content: str, skip_vision: bool = False) -> tuple[List[Professor], str]:
        """
        Extracts professors and department context using a rigorous LLM approach.
        
        Args:
            url: Page URL
            html_content: HTML to extract from
            skip_vision: If True, skip vision analysis (for paginated sub-pages)
            
        Returns: (List[Professor], department_name)
        """
        model_name = settings.get_model_for_task("detail_extraction")
        vision_context = ""
        
        # 0. Check Schema Cache
        schema_cache = get_schema_cache()
        cached_schema = schema_cache.get(url)
        if cached_schema:
            logger.info(f"      [Cache] Found existing schema for {url}")
            # TODO: Implement selector-based extraction using cached_schema
        
        # 1. Vision Analysis (unless skipped)
        if not skip_vision:
            result, status = await self.analyze_page(url)
            
            if status == "blocked":
                return [], f"BLOCKED:{result.block_type.value}"
            
            if status == "gateway":
                return [], "GATEWAY"  # Signal to main.py to crawl department links
            
            if status == "profile":
                return [], "PROFILE"  # Single profile, not a directory
            
            if status == "paginated":
                return [], "PAGINATED"  # Signal to main.py to use pagination handler
            
            # Add vision hints to prompt context
            if result.schema_hints:
                logger.info(f"      [Vision] Schema hints: {list(result.schema_hints.keys())}")
                vision_context = f"VISION_HINTS: {json.dumps(result.schema_hints)}\n"
            
            if result.pagination_type not in ("unknown", "none"):
                vision_context += f"PAGINATION_TYPE: {result.pagination_type}, ESTIMATED_PAGES: {result.max_pages_needed}\n"

        # 2. Try CSS Selector Extraction First (Fast Path)
        from insti_scraper.core.selector_strategies import create_extractor_with_overrides
        from bs4 import BeautifulSoup
        
        logger.info("      [Extraction] Step 1: CSS selectors...")
        extractor = create_extractor_with_overrides(url)
        # Now returns (results, strategy_object)
        css_results, strategy = extractor.extract(html_content)
        
        if css_results and len(css_results) >= 3:  # At least 3 faculty
            logger.info(f"      ✅ CSS success ({strategy.name}): {len(css_results)} faculty")
            
            # Learn: Update profile with working selectors if applicable
            try:
                from insti_scraper.config.profile_updater import profile_updater
                from insti_scraper.config import get_university_profile
                
                profile = get_university_profile(url)
                if profile:
                    profile_updater.update_profile_selectors(profile.domain_pattern, strategy)
                    profile_updater.add_faculty_url(profile.domain_pattern, url)
            except Exception as e:
                logger.warning(f"      ⚠️ Failed to update profile config: {e}")
            
            # Infer department from page
            soup = BeautifulSoup(html_content, 'html.parser')
            dept_name = "General"
            title = soup.find('title')
            if title:
                dept_name = self._infer_department_from_text(title.get_text())
            
            professors = []
            for item in css_results:
                if not item.get('name'):
                    continue
                prof = Professor(
                    name=item['name'],
                    title=item.get('title', ''),
                    email=item.get('email'),
                    profile_url=item.get('profile_url') or item.get('link'),
                    research_interests=item.get('research_interests', [])
                )
                professors.append(prof)
            
            return professors, dept_name
        else:
            logger.info(f"      ⚠️ CSS: {len(css_results)} results, trying Visual Heuristic...")
            
            # [Step 1.5] Visual Heuristic Selector Generation
            # If standard selectors failed, use Vision to see "Anchor Names" and reverse-engineer a selector.
            
            # Use the Vision result we got earlier (or fetch it now if skipped? currently main.py does vision analysis?)
            # Wait, main.py passes `html`, not vision result. 
            # We need to run vision analysis here if we want sample names.
            
            try:
                # Import here to avoid circular dependencies
                from insti_scraper.analyzers.vision_analyzer import VisionPageAnalyzer
                from insti_scraper.core.selector_generator import visual_selector_generator
                from insti_scraper.config.profile_updater import profile_updater
                from insti_scraper.config import get_university_profile
                
                # Check if we have sample names from previous Vision pass (if passed in context?)
                # Actually, main.py -> extract_with_fallback doesn't accept vision result object.
                # Let's run a quick vision analysis specifically for names if not already robust
                
                analyzer = VisionPageAnalyzer()
                # Run lightweight analysis just for names? The full analysis covers it.
                logger.info("      [Visual] Capturing screenshot to find visual anchors...")
                vision_result = await analyzer.analyze(url)
                
                if vision_result and vision_result.sample_names:
                    logger.info(f"      [Visual] Found anchors: {vision_result.sample_names}")
                    
                    # Generate Selector
                    generated_strategy = visual_selector_generator.generate_from_names(html_content, vision_result.sample_names)
                    
                    if generated_strategy:
                        # Try extracting with new strategy
                        gen_results = generated_strategy.extract(BeautifulSoup(html_content, 'html.parser'))
                        
                        if len(gen_results) >= 3:
                            logger.info(f"      ✅ Visual Heuristic Success! Found {len(gen_results)} faculty")
                            
                            # Save this new strategy to Config!
                            profile = get_university_profile(url)
                            if profile:
                                profile_updater.update_profile_selectors(profile.domain_pattern, generated_strategy)
                                profile_updater.add_faculty_url(profile.domain_pattern, url)
                                logger.info(f"      💾 Learned new selectors for {profile.name}")
                            
                            # Return results
                            professors = []
                            for item in gen_results:
                                if not item.get('name'): continue
                                professors.append(Professor(
                                    name=item['name'],
                                    title=item.get('title', ''),
                                    email=item.get('email'),
                                    profile_url=item.get('profile_url') or item.get('link'),
                                    research_interests=[]
                                ))
                            return professors, "General" # TODO: Infer dept
                        else:
                            logger.warning(f"      ⚠️ Generated selector '{generated_strategy.container}' found only {len(gen_results)} items. ignoring.")
                    else:
                        logger.warning("      ⚠️ Could not generate valid selector from anchors.")
                else:
                    logger.warning("      ⚠️ No visual anchors found.")
                    
            except Exception as e:
                logger.error(f"      ❌ Visual extraction failed: {e}")
            
            logger.info("      [Fallback] Proceeding to deep LLM extraction...")

        # 3. LLM Fallback - Convert to Markdown (cleaner + smaller)
        logger.info("      [Extraction] Step 2: Converting to markdown...")
        from markdownify import markdownify as md
        
        markdown_content = md(html_content, heading_style="ATX", strip=['script', 'style', 'nav', 'footer'])
        markdown_content = markdown_content[:200000]  # ~200k chars for GPT-4
        
        logger.info(f"      [Extraction] Markdown size: {len(markdown_content)} chars")

        user_prompt = f"""Extract ALL ACADEMIC FACULTY from this page: {url}
        
        {vision_context}
        PAGE CONTENT (Markdown):
        {markdown_content}
        
        CRITICAL INSTRUCTIONS:
        1. **Department Context**: Infer department name from headers/title. Return as 'department_name'.
        2. **Extract ALL faculty**: Process entire page, don't stop early.
        3. **Rich Data**: For each faculty:
           - name (required)
           - title (e.g. "Professor")
           - email (if available)
           - profile_url (link to their page)
           - research_interests (list)
        4. **Filtering**: IGNORE Admin/Staff/Students.
        
        Return JSON: {{"department_name": "...", "faculty": [...]}}"""

        
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
            
            # Learn: If LLM found faculty, this is a valid faculty URL
            if len(profiles_list) >= 3:
                try:
                    from insti_scraper.config.profile_updater import profile_updater
                    from insti_scraper.config import get_university_profile
                    
                    profile = get_university_profile(url)
                    if profile:
                        profile_updater.add_faculty_url(profile.domain_pattern, url)
                except Exception as e:
                    logger.warning(f"      ⚠️ Failed to update profile URL: {e}")
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
