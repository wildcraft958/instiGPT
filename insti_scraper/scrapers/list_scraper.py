import asyncio
import json
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from insti_scraper.core.config import settings
from insti_scraper.strategies.extraction_strategies import (
    determine_extraction_schema,
    determine_gateway_schema,
    create_css_strategy,
    create_fallback_strategy
)
from insti_scraper.core.schema_cache import SchemaCache
from insti_scraper.analyzers.vision_analyzer import VisionPageAnalyzer, PageType
from insti_scraper.strategies.search_navigation import SearchNavigator

class ListScraper:
    """
    Handles Phase 1: Discovery and extraction of faculty profiles from list pages.
    """
    def __init__(self, model_name: str = settings.MODEL_NAME):
        self.model_name = model_name
        self.schema_cache = SchemaCache()
        self.vision_analyzer = VisionPageAnalyzer(model=model_name)
        self.search_navigator = SearchNavigator()
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
                # 0. Classify Page Type
                print(f"🤖 Classifying {current_url}...")
                p_type, conf, reason = await self.vision_analyzer.classify_page(current_url)
                print(f"  📊 Type: {p_type.value} ({conf:.2f}) - {reason}")
                
                # Check for Gateway OR if it's a list but lacks profile images (likely just a contact list)
                # We assume valid faculty directory MUST have images/placeholders
                is_gateway = p_type == PageType.DEPARTMENT_GATEWAY
                is_directory = p_type == PageType.DIRECTORY_CLICKABLE or p_type == PageType.DIRECTORY_VISIBLE
                has_no_images = "no profile images" in reason.lower() or "text-only" in reason.lower()
                
                if is_gateway or (is_directory and has_no_images):
                    print(f"  🚪 Detected Gateway/Directory Hub (or image-less list). Switching to Discovery Mode.")
                    # Use the robust internal method which includes Search Teleport fallback
                    return await self._run_gateway_extraction(crawler, current_url)

                # 1. Determine Schema (Profile Mode)
                schema = await determine_extraction_schema(current_url, self.model_name, crawler)
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
                
                extracted_profiles = []
                if res.success and res.extracted_content:
                    extracted = self._parse_extracted(res.extracted_content)
                    extracted_profiles = self._filter_new_profiles(extracted, current_url)
                    all_profiles.extend(extracted_profiles)
                
                # If CSS Profile Extraction failed, try LLM Fallback for profiles
                if not all_profiles:
                     print("  ⚠️ CSS extraction yielded 0 results. Switching to LLM Fallback...")
                     fallback_profiles = await self._run_fallback(crawler, current_url)
                     all_profiles.extend(self._filter_new_profiles(fallback_profiles, current_url))

                # DOUBLE FALLBACK: If we STILL have 0 profiles, check if this is actually a Gateway/Directory Hub
                if not all_profiles:
                    print(f"  🤔 No profiles found. Checking if '{current_url}' is actually a Directory Gateway...")
                    gateway_links = await self._run_gateway_extraction(crawler, current_url)
                    if gateway_links:
                        print(f"  ✅ Fallback successful: Found {len(gateway_links)} sub-directory links.")
                        return gateway_links

                # 3. Handle Pagination (Only if we found profiles)
                if all_profiles:
                    page_count = 1
                    max_pages_to_try = min(max_pages, 50)
                    prev_count = len(all_profiles)
                    
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
                            break

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

    
    def _validate_profile(self, item: Dict, p_url: str, is_discovery: bool = False) -> bool:
        """
        Validates if an extracted item is likely a real person/profile 
        and not a tender, notice, or system link.
        """
        name = item.get('name', '').strip()
        title = item.get('title', '').lower() if item.get('title') else ""
        url_lower = p_url.lower()
        
        # 0. Whitelist Academic Units for Discovery
        if is_discovery:
            if any(x in name.lower() for x in ['department', 'school', 'centre', 'center', 'academy', 'institute']):
                return True

        # 1. Block File Extensions (Tenders, Notices)
        if any(url_lower.endswith(ext) for ext in ['.pdf', '.doc', '.docx', '.zip', '.xls', '.xlsx']):
            # print(f"  🚫 Filtered (File): {name}")
            return False
            
        # 2. Block Junk Keywords in Name/Title
        junk_keywords = {
            'tender', 'purchase', 'repair', 'procurement', 'supply', 'installation', 
            'construction', 'renovation', 'maintenance', 'providing', 'disposal', 
            'sign in', 'sign up', 'login', 'register', 'payment', 'fee', 
            'anti-ragging', 'committee', 'page not found', 'contact us'
        }
        # 'home' removed from junk to avoid false positives on breadcrumbs, 
        # but we should check title carefully.

        if any(k in name.lower() for k in junk_keywords):
            # print(f"  🚫 Filtered (Keyword): {name}")
            return False
        if any(k in title for k in junk_keywords):
            return False
            
        # 3. Heuristic: Name Length
        # Real names are rarely longer than 5-6 words.
        # But allow longer names if it's a discovery link (might be a long department name)
        limit = 10 if is_discovery else 6
        if len(name.split()) > limit:
            # print(f"  🚫 Filtered (Length {len(name.split())}): {name}")
            return False
            
        # 4. Block System URLs
        if "feePayment" in url_lower or "supplierfacilities" in url_lower:
            return False
            
        return True

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
            
            # Normalize URL
            if p_url and not p_url.startswith("http") and not p_url.startswith("list_only:"):
                 p_url = urljoin(current_url, p_url)
                 item['profile_url'] = p_url

            # Determine if this looks like a discovery link (heuristic)
            from urllib.parse import urlparse
            directory_keywords = {'staff', 'faculty', 'people', 'directory', 'list', 'members', 'team'}
            
            parsed = urlparse(p_url)
            path_segments = [s for s in parsed.path.split('/') if s]
            last_segment = path_segments[-1].lower() if path_segments else ""
            is_directory_end = last_segment in directory_keywords
            
            # Additional check: If name contains "Department" or "School", treat as discovery candidate
            if any(x in name.lower() for x in ['department', 'school', 'centre', 'center']):
                is_directory_end = True

            # --- VALIDATION STEP ---
            # Pass is_discovery flag so we don't block long department names
            if not self._validate_profile(item, p_url, is_discovery=is_directory_end):
                continue
            
            if p_url and p_url not in self.seen_urls:
                if is_directory_end:
                    print(f"  🔄 Converting Profile -> Discovery Link: {item['name']} -> {item['profile_url']}")
                    item['type'] = 'discovery_link'
                    item['url'] = item.pop('profile_url')
                    # Keep name for context
                
                self.seen_urls.add(item.get('profile_url') or item.get('url'))
                new_profiles.append(item)
        
        if new_profiles:
            print(f"  -> Found {len(new_profiles)} new profiles/links.")
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

    async def _run_gateway_extraction(self, crawler: AsyncWebCrawler, url: str) -> List[Dict]:
        """
        Attempt to extract directory/department links using Gateway Schema.
        """
        print(f"  🚪 Attempting Gateway Discovery fallback on {url}...")
        try:
            # Re-use existing crawler session if possible, but schema changes
            schema = await determine_gateway_schema(url, self.model_name, crawler)
            css_strategy = create_css_strategy(schema)
            print(f"  📋 Gateway Schema: {schema.base_selector} -> {list(schema.fields.keys())}")
            
            # We need to re-run the crawl with new strategy
            js = '''
            await new Promise(r => setTimeout(r, 2000));
            '''
            res = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(extraction_strategy=css_strategy, cache_mode=CacheMode.BYPASS, scan_full_page=True, js_code=js)
            )
            
            if res.success and res.extracted_content:
                data = json.loads(res.extracted_content)
                discovered_items = []
                for item in data:
                    link = item.get("link") or item.get("profile_url") or item.get("url")
                    name = item.get("name")
                    if link:
                        full_link = urljoin(url, link)
                        
                        # Validate discovery link using the same robust filter
                        # Check name and URL to avoid following "Tenders", "Notices", etc.
                        if not self._validate_profile({"name": name, "title": ""}, full_link, is_discovery=True):
                            continue

                        discovered_items.append({
                            "type": "discovery_link",
                            "url": full_link,
                            "name": name,
                            "source": "gateway_fallback"
                        })
                return discovered_items
        except Exception as e:
            print(f"  ❌ Gateway fallback failed: {e}")
        
        # TRIPLE FALLBACK: Search Teleport
        # If internal gateway scraping failed, ask DuckDuckGo where the faculty list is
        print(f"  🛰️ Gateway failed. Attempting Search Teleport...")
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace("www.", "")
        path_parts = [p for p in urlparse(url).path.split("/") if p and p.lower() not in ["department", "school", "centre"]]
        context = path_parts[-1] if path_parts else "faculty"
        
        search_url = await self.search_navigator.find_faculty_directory(domain, context)
        if search_url:
             print(f"  ✅ Search Teleport successful: {search_url}")
             return [{
                 "type": "discovery_link",
                 "url": search_url,
                 "name": f"Search Result: {context}",
                 "source": "search_teleport"
             }]
        
        return []
