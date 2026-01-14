import asyncio
import json
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from insti_scraper.config import settings
from insti_scraper.strategies import (
    determine_extraction_schema,
    create_css_strategy,
    create_fallback_strategy
)
from insti_scraper.core.schema_cache import SchemaCache

class ListScraper:
    """
    Handles Phase 1: Discovery and extraction of faculty profiles from list pages.
    """
    def __init__(self, model_name: str = settings.MODEL_NAME):
        self.model_name = model_name
        self.schema_cache = SchemaCache()
        self.seen_urls = set()

    async def scrape_list_pages(self, start_url: str, max_pages: int = settings.MAX_PAGES) -> List[Dict[str, Any]]:
        """
        Scrapes a faculty directory handling pagination.
        Returns a list of profile dictionaries (name, profile_url, etc.)
        """
        print(f"\n--- PHASE 1: List Discovery on {start_url} ---")
        
        all_profiles = []
        current_url = start_url
        page_count = 0
        session_id = f"scrape_list_{hash(start_url)}"
        
        # JS to handle DataTables/load max entries
        init_js = '''
        await new Promise(r => setTimeout(r, 2000));
        let select = document.querySelector('select[name*="length"], select[name*="entries"]');
        if (select) {
            let maxVal = 10;
            for (let opt of select.options) {
                let val = parseInt(opt.value);
                if (!isNaN(val) && val > maxVal) maxVal = val;
            }
            select.value = maxVal.toString();
            select.dispatchEvent(new Event('change', { bubbles: true }));
            await new Promise(r => setTimeout(r, 2000));
        }
        window.scrollTo(0, document.body.scrollHeight);
        await new Promise(r => setTimeout(r, 1500));
        '''
        
        next_page_js = '''
        await new Promise(r => setTimeout(r, 500));
        let nextBtn = document.querySelector('a.paginate_button.next:not(.disabled), a.next:not(.disabled), [data-dt-idx="next"]:not(.disabled)');
        if (nextBtn && !nextBtn.classList.contains('disabled')) {
            nextBtn.click();
            await new Promise(r => setTimeout(r, 2000));
        }
        ''' # TODO: Use VisionPageAnalyzer for next button selector in future iteration

        async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=True)) as crawler:
            try:
                # 1. Determine Schema
                schema = await determine_extraction_schema(current_url, self.model_name)
                css_strategy = create_css_strategy(schema)
                print(f"  📋 Schema: {schema.base_selector} -> {list(schema.fields.keys())}")
                
                # 2. Scrape Page 1
                print(f"📄 Processing Page 1: {current_url}")
                res = await crawler.arun(
                    url=current_url,
                    config=CrawlerRunConfig(
                        extraction_strategy=css_strategy,
                        cache_mode=CacheMode.BYPASS, 
                        scan_full_page=True,
                        js_code=init_js,
                        session_id=session_id
                    )
                )
                
                if res.success and res.extracted_content:
                    extracted = self._parse_extracted(res.extracted_content)
                    new_profiles = self._filter_new_profiles(extracted, current_url)
                    all_profiles.extend(new_profiles)
                    page_count = 1
                    
                    # 3. Handle Pagination
                    max_pages_to_try = min(max_pages, 50)
                    prev_count = len(all_profiles)
                    
                    # Simple heuristic: stop if we didn't find anything on page 1 either
                    # But if we did, assume pagination might exist
                    
                    while page_count < max_pages_to_try:
                        page_count += 1
                        print(f"📄 Processing Page {page_count}...")
                        
                        res = await crawler.arun(
                            url=current_url,
                            config=CrawlerRunConfig(
                                extraction_strategy=css_strategy,
                                session_id=session_id,
                                js_only=True, 
                                js_code=next_page_js
                            )
                        )
                        
                        if res.success and res.extracted_content:
                            extracted = self._parse_extracted(res.extracted_content)
                            new_profiles = self._filter_new_profiles(extracted, current_url)
                            all_profiles.extend(new_profiles)
                            
                            if len(all_profiles) == prev_count:
                                print(f"  ℹ️ No new profiles on page {page_count}, stopping.")
                                break
                            prev_count = len(all_profiles)
                        else:
                            print(f"  ⚠️ Page {page_count} extraction failed or end reached.")
                            break
                            
                # Fallback to LLM if CSS failed completely
                if not all_profiles:
                    print("  ⚠️ CSS extraction yielded 0 results. Switching to LLM Fallback...")
                    fallback_profiles = await self._run_fallback(crawler, current_url)
                    all_profiles.extend(self._filter_new_profiles(fallback_profiles, current_url))

            except Exception as e:
                print(f"  ❌ Error in Phase 1: {e}")
                
        return all_profiles

    def _parse_extracted(self, extracted_content: str) -> List[Dict]:
        try:
            data = json.loads(extracted_content)
            if isinstance(data, list):
                # Allow items with just a name, even if no profile_url
                return [item for item in data if isinstance(item, dict) and item.get("name")]
        except Exception:
            pass
        return []

    def _filter_new_profiles(self, extracted: List[Dict], current_url: str) -> List[Dict]:
        new_profiles = []
        for item in extracted:
            p_url = item.get('profile_url')
            name = item.get('name', 'Unknown')
            
            # If no profile URL, synthesize one or use a placeholder
            if not p_url:
                # Create a synthetic URL for list-only items to allow deduplication
                unique_id = f"{name}_{item.get('email', '')}_{item.get('title', '')}"
                item['profile_url'] = f"list_only:{hash(unique_id)}"
                item['source_type'] = 'list_only'
                p_url = item['profile_url']
            
            if p_url and p_url not in self.seen_urls:
                if not p_url.startswith("http") and not p_url.startswith("list_only:"):
                     item['profile_url'] = urljoin(current_url, p_url)
                
                self.seen_urls.add(item['profile_url'])
                new_profiles.append(item)
        
        if new_profiles:
            print(f"  -> Found {len(new_profiles)} new profiles.")
        return new_profiles

    async def _run_fallback(self, crawler: AsyncWebCrawler, url: str) -> List[Dict]:
        fallback_strategy = create_fallback_strategy(self.model_name)
        js = '''
        await new Promise(r => setTimeout(r, 2000));
        window.scrollTo(0, document.body.scrollHeight);
        '''
        res = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(
                extraction_strategy=fallback_strategy,
                cache_mode=CacheMode.BYPASS, 
                scan_full_page=True,
                js_code=js
            )
        )
        if res.success and res.extracted_content:
            try:
                data = json.loads(res.extracted_content)
                if isinstance(data, list):
                    return data
            except:
                pass
        return []
