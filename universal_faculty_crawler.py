import asyncio
import json
import os
import sys
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from litellm import completion

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, LLMConfig as C4AILLMConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy, LLMExtractionStrategy
from urllib.parse import urljoin

# Configuration
# MODEL_NAME = "openai/gpt-4o"
# API Key must be set in env: os.environ['OPENAI_API_KEY']

class SelectorSchema(BaseModel):
    base_selector: str = Field(..., description="The CSS selector for the repeating container (or 'body' for single page)")
    fields: Dict[str, str] = Field(..., description="Map of field names to CSS selectors")

async def get_html_sample(url: str, headless: bool = True) -> str:
    """Fetches the raw HTML of a page for analysis."""
    print(f"🔍 Fetching sample from {url}...")
    async with AsyncWebCrawler(config=BrowserConfig(headless=headless)) as crawler:
        result = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
        )
        if not result.success:
            raise Exception(f"Failed to fetch {url}: {result.error_message}")
        
        # Heuristic to get the useful part of the HTML
        html = result.html
        if "<main" in html:
            start = html.find("<main")
            return html[start : start + 50000]
        elif "<body" in html:
            start = html.find("<body")
            return html[start : start + 50000]
        return html[:50000]

async def analyze_with_llm(html_content: str, goal: str, fields: List[str], model_name: str) -> SelectorSchema:
    """Asks the LLM to deduce CSS selectors."""
    
    system_prompt = """You are a CSS Selector Expert.
    Your task is to analyze HTML and return a JSON configuration for extracting specific fields.
    RETURN ONLY JSON. NO MARKDOWN. NO EXPLANATION.
    """
    
    user_prompt = f"""
    GOAL: {goal}
    
    I need CSS selectors for these fields: {', '.join(fields)}
    
    Return a JSON object with:
    1. "base_selector": 
       - If extracting a LIST of items, this is the repeating container (e.g. "div.card", "tr").
       - If extracting details from a SINGLE page, this is usually "body" or the main wrapper class.
       
    2. "fields": A dictionary mapping MY field names to CSS selectors.
       - Selectors must be RELATIVE to the base_selector.
       - For Attributes: append the attribute like "a[href]" or "img[src]". Actually, standard CSS selectors don't support that syntax in many libraries, so just give the tag.
       - WAIT: For crawl4ai, just give the selector.
    
    HTML CONTENT:
    {html_content}
    
    JSON OUTPUT FORMAT:
    {{
        "base_selector": "...",
        "fields": {{
            "field1": "selector1",
            "field2": "selector2"
        }}
    }}
    """
    
    print(f"🧠 Asking {model_name} to analyze...")
    response = completion(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"}
    )
    
    content = response.choices[0].message.content
    print(f"✅ LLM Response: {content}")
    data = json.loads(content)
    return SelectorSchema(base_selector=data.get('base_selector', 'body'), fields=data.get('fields', {}))

async def crawl_with_schema(url: str, schema: SelectorSchema, headless: bool = True) -> List[Dict]:
    """Runs the actual crawl using the deduced schema."""
    
    # map schema fields to Crawl4AI format
    css_fields = []
    for name, selector in schema.fields.items():
        field_def = {"name": name, "selector": selector, "type": "text"}
        if "href" in selector or "url" in name or "link" in name:
            field_def["type"] = "attribute"
            field_def["attribute"] = "href"
        elif "src" in selector or "image" in name or "img" in name:
            field_def["type"] = "attribute"
            field_def["attribute"] = "src"
        elif "mailto" in selector or "email" in name:
             # email usually in mailto link
             if "a" in selector:
                field_def["type"] = "attribute"
                field_def["attribute"] = "href"
        
        css_fields.append(field_def)
        
    strategy = JsonCssExtractionStrategy({
        "baseSelector": schema.base_selector,
        "fields": css_fields
    })
    
    async with AsyncWebCrawler(config=BrowserConfig(headless=headless)) as crawler:
        result = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(
                extraction_strategy=strategy,
                cache_mode=CacheMode.ENABLED
            )
        )
        if result.success:
            return json.loads(result.extracted_content)
        return []

async def determine_extraction_schema(url: str, model_name: str) -> SelectorSchema:
    """Determines the CSS extraction schema for a given URL using LLM analysis."""
    print(f"🔍 Determining CSS schema for {url}...")
    html_sample = await get_html_sample(url)
    
    list_fields = ["name", "title", "profile_url"]
    schema = await analyze_with_llm(
        html_sample, 
        goal="Extract list of faculty members", 
        fields=list_fields, 
        model_name=model_name
    )
    print(f"✅ Schema determined: Base Selector='{schema.base_selector}', Fields={schema.fields}")
    return schema

async def universal_faculty_scraper(start_url: str, model_name: str = "openai/gpt-4o"):
    print(f"🚀 Starting Universal Scraper on {start_url}")
    
    # --- PHASE 1: LIST DISCOVERY ---
    print(f"\n--- PHASE 1: Analyzing {start_url} ---")
    
    # Enable Infinite Scroll & Anti-Bot
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        scan_full_page=True,  # Built-in Infinite Scroll
        scroll_delay=0.5,
        word_count_threshold=5,
        magic=True,            # Anti-bot
    )

    all_profiles = []
    seen_urls = set()
    current_url = start_url
    
    # Pagination Limit
    MAX_PAGES = 5
    page_count = 0

    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=True)) as crawler:
        while current_url and page_count < MAX_PAGES:
            page_count += 1
            print(f"📄 Processing Page {page_count}: {current_url}")
            
            # Step 1: CSS Discovery
            schema = await determine_extraction_schema(current_url, model_name)
            
            # Convert Pydantic schema to Crawl4AI expected dict (camelCase)
            css_schema_dict = {
                "baseSelector": schema.base_selector,
                "fields": []
            }
            # Helper to map fields
            for name, selector in schema.fields.items():
                field_def = {"name": name, "selector": selector, "type": "text"}
                if "href" in selector or "url" in name.lower() or "link" in name.lower():
                    field_def["type"] = "attribute"
                    field_def["attribute"] = "href"
                elif "src" in selector or "image" in name.lower() or "img" in name.lower():
                    field_def["type"] = "attribute"
                    field_def["attribute"] = "src"
                css_schema_dict["fields"].append(field_def)

            css_strategy = JsonCssExtractionStrategy(schema=css_schema_dict)
            
            res = await crawler.arun(
                url=current_url,
                config=run_config.clone(extraction_strategy=css_strategy)
            )
            
            extracted = []
            if res.success and res.extracted_content:
                try:
                    data = json.loads(res.extracted_content)
                    extracted = [item for item in data if isinstance(item, dict) and item.get("profile_url")]
                except:
                    pass
            
            # Step 2: Fallback (Pure LLM) if CSS fails
            if not extracted:
                print("  ⚠️ CSS extraction yielded 0 results. Switching to LLM Fallback (Raw Content Analysis)...")
                # Define a Pydantic schema for the expected output of the LLM fallback
                class FallbackProfileSchema(BaseModel):
                    name: str
                    profile_url: str
                    title: Optional[str] = None

                fallback_strategy = LLMExtractionStrategy(
                    llm_config=C4AILLMConfig(provider=model_name, api_token=os.getenv("OPENAI_API_KEY")),
                    instruction="Find all faculty/staff profile URLs, names, and titles in this content. Return a JSON list of objects, each with 'name', 'profile_url', and optionally 'title'.",
                    schema=FallbackProfileSchema.model_json_schema(),
                    extraction_type="schema"
                )
                res_fallback = await crawler.arun(
                    url=current_url,
                    config=run_config.clone(extraction_strategy=fallback_strategy)
                )
                if res_fallback.success and res_fallback.extracted_content:
                    try: 
                        extracted = json.loads(res_fallback.extracted_content)
                        # Normalize format if needed
                        if isinstance(extracted, list):
                            extracted = [x for x in extracted if x.get('profile_url')]
                        print(f"  ✅ LLM Fallback found {len(extracted)} profiles.")
                    except Exception as e:
                        print(f"  ❌ LLM Fallback parse error: {e}")

            # Deduplicate & Add
            new_count = 0
            for item in extracted:
                if item.get('profile_url') and item['profile_url'] not in seen_urls:
                    # Resolve relative URLs
                    if not item['profile_url'].startswith("http"):
                        item['profile_url'] = urljoin(current_url, item['profile_url'])
                    
                    seen_urls.add(item['profile_url'])
                    all_profiles.append(item)
                    new_count += 1
            
            print(f"  -> Found {new_count} new profiles (Total: {len(all_profiles)})")

            # Simple Pagination Check (Look for 'Next' link in links)
            break 
    
    if not all_profiles:
        print("❌ No profiles found. Aborting.")
        return

    # --- PHASE 2: DETAIL EXTRACTION (LLM-BASED) ---
    print("\n--- PHASE 2: Extracting Details (Hybrid Approach) ---")
    print("✨ Using LLM to extract details from each profile page (slower but much more accurate)...")
    
    # We define a Pydantic schema for the details
    class FacultyDetail(BaseModel):
        email: Optional[str] = Field(None, description="The faculty member's email address")
        research_interests: List[str] = Field(default_factory=list, description="List of research areas or interests")
        publications: List[str] = Field(default_factory=list, description="Latest publications (max 5)")
        image_url: Optional[str] = Field(None, description="Profile image URL")

    # Configure the LLM Strategy
    
    # Map our generic model name to crawl4ai config
    provider = model_name
    api_token = os.environ.get("OPENAI_API_KEY")
    
    llm_strategy = LLMExtractionStrategy(
        llm_config=C4AILLMConfig(provider=provider, api_token=api_token),
        schema=FacultyDetail.model_json_schema(),
        extraction_type="schema",
        instruction=(
            "Extract the following:"
            "1. Email (look for mailto links or evident email text)."
            "2. Research Interests: Look for sections named 'Research', 'Expertise', or 'Current Work'. "
            "   - If it's a list, extract items."
            "   - If it's a paragraph, summarize key topics/areas into a list."
            "3. Publications: Look for 'Selected Publications' or similar lists. Max 5."
            "If 'Research' is missing, check 'Expertise' or 'Biography' for implied interests."
        ),
        chunk_token_threshold=4000,
        input_format="markdown",
        verbose=False
    )

    final_data = []

    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        # Crawl in chunks - smaller chunk size for LLM to avoid rate limits
        chunk_size = 5
        
        # Limit for demo purposes if list is huge? No, user wants completion.
        # But let's process at least the first 20 to show it working well, or all.
        # User said "complete the job", so we try all.
        
        total = len(all_profiles)
        
        for i in range(0, total, chunk_size):
            chunk = all_profiles[i:i+chunk_size]
            print(f"🔄 Processing batch {i+1}-{min(i+chunk_size, total)} of {total}...")
            
            tasks = []
            for profile in chunk:
                # We merge list data with detail data
                tasks.append(crawler.arun(
                    url=profile['profile_url'],
                    config=CrawlerRunConfig(
                        extraction_strategy=llm_strategy,
                        cache_mode=CacheMode.BYPASS
                    )
                ))
            
            results = await asyncio.gather(*tasks)
            
            for j, res in enumerate(results):
                profile_orig = chunk[j]
                if res.success:
                    # LLM extraction returns JSON string
                    try:
                        extracted_list = json.loads(res.extracted_content)
                        # LLM strategy usually returns a list of items found in chunks.
                        # We merge them.
                        combined_detail = {
                            "email": None,
                            "research_interests": [],
                            "publications": [],
                            "image_url": None
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
                             
                             # Fix string vs list bug
                             if item.get('research_interests'):
                                 combined_detail['research_interests'].extend(ensure_list(item['research_interests']))
                             if item.get('publications'):
                                 combined_detail['publications'].extend(ensure_list(item['publications']))
                        
                        # Deduplicate lists
                        combined_detail['research_interests'] = list(set(combined_detail['research_interests']))
                        combined_detail['publications'] = list(set(combined_detail['publications']))
                        
                        profile_orig.update(combined_detail)
                        
                        # Cleanup email
                        if profile_orig.get('email') and isinstance(profile_orig['email'], str):
                            profile_orig['email'] = profile_orig['email'].replace('mailto:', '').strip()
                        
                        print(f"  ✅ Extracted details for {profile_orig['name']}")
                        
                    except Exception as e:
                        print(f"  ⚠️ JSON parse error for {profile_orig['name']}: {e}")
                else:
                    print(f"  ❌ Failed to crawl {profile_orig['name']}")
                        
                final_data.append(profile_orig)

    # Output
    with open("universal_faculty_data.json", "w", encoding="utf-8") as f:
        json.dump(final_data, f, indent=2)
    print(f"\n🎉 DONE! Saved {len(final_data)} profiles to universal_faculty_data.json")

if __name__ == "__main__":
    # Example Usage
    target_url = "https://engineering.wustl.edu/faculty/index.html"
    
    # Check for API Key
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️ OPENAI_API_KEY not found in environment. This script requires it for GPT-4o analysis.")
        # For testing, you might let it fail or prompt.
    
    asyncio.run(universal_faculty_scraper(target_url, model_name="openai/gpt-4o"))
