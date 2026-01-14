import asyncio
import json
import signal
from typing import List, Dict, Any, Union
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from insti_scraper.config import settings
from insti_scraper.strategies import create_detail_strategy

class DetailScraper:
    """
    Handles Phase 2: Extraction of detailed profile information (email, interests, etc.)
    Uses robust concurrency and incremental saving.
    """
    def __init__(self, model_name: str = settings.MODEL_NAME, chunk_size: int = 20):
        self.model_name = model_name
        self.chunk_size = chunk_size
        self.strategy = create_detail_strategy(model_name)
    
    async def process_batch(self, profiles: List[Dict[str, Any]], progress_callback=None) -> List[Dict[str, Any]]:
        """
        Process a list of profiles to enrich them with details.
        
        Args:
            profiles: List of profile dicts (must have 'profile_url')
            progress_callback: Optional async function(completed_profiles: List[Dict]) to call periodically
            
        Returns:
            List of enriched profile dictionaries
        """
        print(f"\n--- PHASE 2: Detail Extraction on {len(profiles)} profiles ---")
        
        enriched_profiles = []
        total = len(profiles)
        
        browser_addr = BrowserConfig(headless=True, verbose=False)
        
        # We need a way to stop gracefully if integrated into larger pipeline but 
        # for now we'll handle chunks.
        
        async with AsyncWebCrawler(config=browser_addr) as crawler:
            cursor = 0
            while cursor < total:
                chunk = profiles[cursor : cursor + self.chunk_size]
                print(f"🔄 Batch {cursor+1}-{min(cursor+self.chunk_size, total)} of {total}...")
                
                tasks = []
                for profile in chunk:
                    tasks.append(self._safely_extract(crawler, profile))
                
                results = await asyncio.gather(*tasks)
                enriched_profiles.extend(results)
                
                if progress_callback:
                    await progress_callback(enriched_profiles)
                
                cursor += self.chunk_size
                
        return enriched_profiles

    async def _safely_extract(self, crawler: AsyncWebCrawler, profile: Dict) -> Dict:
        """Extract details for a single profile with error handling."""
        # Don't mutate original in place immediately to avoid side effects if retrying
        p_copy = profile.copy()
        url = p_copy.get('profile_url')
        
        if not url: 
            return p_copy

        # Skip if purely list-based (no profile page)
        if url.startswith("list_only:"):
            print(f"  ℹ️ Skipping enrichment for list-only profile: {p_copy.get('name')}")
            return p_copy

        try:
            res = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(
                    extraction_strategy=self.strategy,
                    cache_mode=CacheMode.BYPASS,
                    page_timeout=30000 
                )
            )
            
            if res.success and res.extracted_content:
                try:
                    data = json.loads(res.extracted_content)
                    if data:
                        details = data[0] # Strategy returns list
                        
                        # Data cleaning
                        if details.get('email'):
                            details['email'] = details['email'].replace('mailto:', '').strip()
                        
                        p_copy.update(details)
                        print(f"  ✅ Extracted: {p_copy.get('name')} ({p_copy.get('email', 'no email')})")
                    else:
                        print(f"  ⚠️ No details found for {p_copy.get('name')}")
                except json.JSONDecodeError:
                    p_copy['error'] = "JSON parse error"
                    print(f"  ❌ JSON error for {p_copy.get('name')}")
            else:
                 print(f"  ❌ Failed crawl for {p_copy.get('name')}: {res.error_message}")
                 p_copy['error'] = res.error_message if res.error_message else "Crawl failed"
                 
        except Exception as e:
            print(f"  ❌ Exception for {p_copy.get('name')}: {e}")
            p_copy['error'] = str(e)
            
        return p_copy
