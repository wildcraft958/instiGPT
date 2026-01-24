import os
import json
import logging
from typing import List, Set
from dataclasses import dataclass

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from litellm import completion, completion_cost
from urllib.parse import urljoin

from insti_scraper.core.config import settings, FACULTY_KEYWORDS, FACULTY_URL_PATTERNS
from insti_scraper.core.prompts import Prompts
from insti_scraper.core.cost_tracker import cost_tracker

logger = logging.getLogger(__name__)

@dataclass
class DiscoveredPage:
    url: str
    score: float
    type: str  # 'faculty_directory', 'gateway'

class DiscoveryService:
    def __init__(self):
        pass

    async def discover_faculty_pages(self, start_url: str, max_depth: int = 3, max_pages: int = 30) -> List[DiscoveredPage]:
        """
        Smart discovery logic to find faculty directories starting from a homepage.
        """
        logger.info(f"🔍 Starting discovery for {start_url}")
        
        # 1. Quick Sitemap/Heuristic Scan (Could use sitemap index if available, for now simple crawl)
        # Using a specialized crawler run config for fast link extraction
        
        candidates = set()
        visited = set()
        faculty_pages = []
        
        # Initial Seed
        async with AsyncWebCrawler() as crawler:
             # Basic heuristic crawl
             # Logic simplified for professional service:
             # In a real expanded version, this would be a recursive graph traversal.
             # For now, we implemented a robust single-pass deep scan or limited recursion.
             
             # TODO: Implement robust crawler traversal here.
             # For now, let's assume we use the patterns to filter links from the homepage.
             
             run_conf = CrawlerRunConfig(
                 cache_mode=CacheMode.ENABLED if settings.CACHE_ENABLED else CacheMode.BYPASS, 
                 word_count_threshold=10
             )
             
             result = await crawler.arun(url=start_url, config=run_conf)
             
             if not result.success:
                 logger.error(f"Failed to crawl {start_url}")
                 return []
             
             # Extract links
             internal_links = set()
             for link_obj in result.links.get('internal', []):
                 href = link_obj.get('href', '')
                 full_url = urljoin(start_url, href)
                 if self._is_promising_url(full_url):
                     internal_links.add(full_url)
             
             logger.info(f"   Found {len(internal_links)} promising links on homepage.")
             
             # verify top candidates with LLM classification
             for link in list(internal_links)[:10]: # Check top 10
                 # Ensure proper URL format before classification
                 if not link.startswith(('http', 'https')):
                     continue
                     
                 page_type, confidence = await self.classify_page(link, crawler)
                 if page_type == 'faculty_directory' and confidence > 0.6:
                     faculty_pages.append(DiscoveredPage(url=link, score=confidence, type=page_type))
                 elif page_type == 'staff_directory':
                     # Explicitly ignore staff
                     continue
        
        return faculty_pages

    def _is_promising_url(self, url: str) -> bool:
        """Heuristic check using keywords."""
        url_lower = url.lower()
        if any(p.replace('*', '') in url_lower for p in FACULTY_URL_PATTERNS):
            return True
        return False

    async def classify_page(self, url: str, crawler: AsyncWebCrawler) -> tuple[str, float]:
        """
        Classifies a page using LLM.
        Returns (page_type, confidence).
        """
        try:
            result = await crawler.arun(url=url, config=CrawlerRunConfig(cache_mode=CacheMode.ENABLED))
            if not result.success: 
                return "error", 0.0
            
            content_sample = result.markdown[:10000] # Use markdown for cleaner classification
            
            model_name = settings.get_model_for_task("page_classification")
            
            response = completion(
                model=model_name,
                messages=[
                    {'role': 'system', 'content': Prompts.CLASSIFICATION_SYSTEM},
                    {'role': 'user', 'content': f"Classify this page ({url}):\n\n{content_sample}"}
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
            
            data = json.loads(response.choices[0].message.content)
            return data.get("page_type", "other"), float(data.get("confidence", 0.0))

        except Exception as e:
            logger.warning(f"Classification failed for {url}: {e}")
            return "error", 0.0

    def _extract_university_name(self, url: str) -> str:
        """Extract university name from URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc
        # Simple extraction strategy
        name = domain.replace("www.", "").replace(".edu", "").replace(".ac.in", "")
        name = name.replace(".ac.uk", "").replace(".org", "")
        return name.title()
