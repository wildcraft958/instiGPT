import asyncio
import json
import os
from urllib.parse import urljoin
from typing import List, Dict, Any

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from .config import settings
from .strategies import (
    determine_extraction_schema,
    create_css_strategy,
    create_fallback_strategy,
    create_detail_strategy
)

class UniversalScraper:
    def __init__(self, model_name: str = settings.MODEL_NAME):
        self.model_name = model_name
        self.seen_urls = set()
        self.all_profiles = []

    async def run(self, start_url: str) -> List[Dict[str, Any]]:
        print(f"🚀 Starting Universal Scraper on {start_url}")
        
        # --- PHASE 1: List Discovery ---
        await self._phase_1_discovery(start_url)
        
        if not self.all_profiles:
            print("❌ No profiles found. Aborting.")
            return []

        # --- PHASE 2: Detail Extraction ---
        final_data = await self._phase_2_extraction()
        return final_data

    async def _phase_1_discovery(self, start_url: str):
        print(f"\n--- PHASE 1: Analyzing {start_url} ---")
        
        run_config = settings.get_run_config(scan_full_page=True)
        current_url = start_url
        page_count = 0
        
        # JavaScript to wait for AJAX content and scroll
        ajax_wait_js = '''
        await new Promise(r => setTimeout(r, 2000));
        window.scrollTo(0, document.body.scrollHeight);
        await new Promise(r => setTimeout(r, 1500));
        '''
        
        async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=True)) as crawler:
            while current_url and page_count < settings.MAX_PAGES:
                page_count += 1
                print(f"📄 Processing Page {page_count}: {current_url}")
                
                # Step 1: CSS Discovery
                try:
                    schema = await determine_extraction_schema(current_url, self.model_name)
                    css_strategy = create_css_strategy(schema)
                    
                    # Debug: show schema
                    print(f"  📋 Schema: base={schema.base_selector}, fields={list(schema.fields.keys())}")
                    
                    # BYPASS cache and wait for AJAX content
                    res = await crawler.arun(
                        url=current_url,
                        config=CrawlerRunConfig(
                            extraction_strategy=css_strategy,
                            cache_mode=CacheMode.BYPASS,
                            scan_full_page=True,
                            js_code=ajax_wait_js
                        )
                    )
                    
                    extracted = []
                    if res.success and res.extracted_content:
                        try:
                            data = json.loads(res.extracted_content)
                            # Debug: show what we got
                            print(f"  📊 Raw extracted: {len(data) if isinstance(data, list) else 'not a list'} items")
                            if isinstance(data, list) and data:
                                print(f"  📊 First item keys: {list(data[0].keys()) if isinstance(data[0], dict) else 'not dict'}")
                            
                            extracted = [item for item in data if isinstance(item, dict) and item.get("profile_url")]
                        except Exception as e:
                            print(f"  ❌ JSON parse error: {e}")
                    
                    # Step 2: Fallback
                    if not extracted:
                        extracted = await self._run_fallback(crawler, current_url, run_config)

                    # Deduplicate & Add
                    self._add_profiles(extracted, current_url)

                except Exception as e:
                    print(f"  ❌ Error processing page {current_url}: {e}")

                # Pagination placeholder - currently we just break to avoid infinite loops on same page
                # In a full implementation, we'd look for "Next" links here.
                break 

    async def _run_fallback(self, crawler: AsyncWebCrawler, url: str, base_config: CrawlerRunConfig) -> List[Dict]:
        print("  ⚠️ CSS extraction yielded 0 results. Switching to LLM Fallback...")
        fallback_strategy = create_fallback_strategy(self.model_name)
        
        # JavaScript to wait for AJAX content
        ajax_wait_js = '''
        await new Promise(r => setTimeout(r, 2000));
        window.scrollTo(0, document.body.scrollHeight);
        await new Promise(r => setTimeout(r, 1500));
        '''
        
        # BYPASS cache and wait for AJAX content with scrolling
        res_fallback = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(
                extraction_strategy=fallback_strategy,
                cache_mode=CacheMode.BYPASS,
                scan_full_page=True,
                js_code=ajax_wait_js
            )
        )
        
        # Debug: Show markdown length
        if res_fallback.markdown:
            print(f"  📊 Markdown length: {len(res_fallback.markdown)} chars")
        
        if res_fallback.success and res_fallback.extracted_content:
            try:
                extracted = json.loads(res_fallback.extracted_content)
                print(f"  📊 LLM Fallback raw: {len(extracted) if isinstance(extracted, list) else type(extracted).__name__}")
                if isinstance(extracted, list):
                    extracted = [x for x in extracted if x.get('profile_url')]
                print(f"  ✅ LLM Fallback found {len(extracted)} profiles.")
                return extracted
            except Exception as e:
                print(f"  ❌ LLM Fallback parse error: {e}")
        return []

    def _add_profiles(self, extracted: List[Dict], current_url: str):
        new_count = 0
        for item in extracted:
            if item.get('profile_url') and item['profile_url'] not in self.seen_urls:
                if not item['profile_url'].startswith("http"):
                    item['profile_url'] = urljoin(current_url, item['profile_url'])
                
                self.seen_urls.add(item['profile_url'])
                self.all_profiles.append(item)
                new_count += 1
        print(f"  -> Found {new_count} new profiles (Total: {len(self.all_profiles)})")

    async def _phase_2_extraction(self) -> List[Dict]:
        print("\n--- PHASE 2: Extracting Details ---")
        llm_strategy = create_detail_strategy(self.model_name)
        final_data = []
        
        chunk_size = settings.CHUNK_SIZE_PHASE_2
        total = len(self.all_profiles)
        
        async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
            for i in range(0, total, chunk_size):
                chunk = self.all_profiles[i:i+chunk_size]
                print(f"🔄 Processing batch {i+1}-{min(i+chunk_size, total)} of {total}...")
                
                tasks = []
                for profile in chunk:
                    tasks.append(crawler.arun(
                        url=profile['profile_url'],
                        config=CrawlerRunConfig(extraction_strategy=llm_strategy, cache_mode=CacheMode.BYPASS)
                    ))
                
                results = await asyncio.gather(*tasks)
                
                for j, res in enumerate(results):
                    profile_orig = chunk[j]
                    if res.success:
                        self._merge_details(profile_orig, res.extracted_content)
                    else:
                        print(f"  ❌ Failed to crawl {profile_orig.get('name', 'Unknown')}")
                    final_data.append(profile_orig)
        
        return final_data

    def _merge_details(self, profile: Dict, extracted_json: str):
        try:
            extracted_list = json.loads(extracted_json)
            combined_detail = {
                "email": None, "research_interests": [], "publications": [], "image_url": None
            }
            
            def ensure_list(val):
                if isinstance(val, str): return [val]
                if isinstance(val, list): return val
                return []

            for item in extracted_list:
                if item.get('email') and not combined_detail['email']:
                    combined_detail['email'] = item['email']
                if item.get('image_url') and not combined_detail['image_url']:
                    combined_detail['image_url'] = item['image_url']
                
                if item.get('research_interests'):
                    combined_detail['research_interests'].extend(ensure_list(item['research_interests']))
                if item.get('publications'):
                    combined_detail['publications'].extend(ensure_list(item['publications']))
            
            combined_detail['research_interests'] = list(set(combined_detail['research_interests']))
            combined_detail['publications'] = list(set(combined_detail['publications']))
            
            profile.update(combined_detail)
            
            if profile.get('email') and isinstance(profile['email'], str):
                profile['email'] = profile['email'].replace('mailto:', '').strip()
            
            print(f"  ✅ Extracted details for {profile.get('name')}")
        except Exception as e:
            print(f"  ⚠️ JSON parse error for {profile.get('name')}: {e}")
