import asyncio
import json
import os
from typing import List, Dict
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy, RegexExtractionStrategy

OUTPUT_FILE = "faculty_data.json"
BASE_URL = "https://engineering.wustl.edu/faculty/"

async def crawl_faculty_list():
    print("📋 Phase 1: Crawling Faculty List...")
    
    schema = {
        "baseSelector": "article.faculty-directory__teaser",
        "fields": [
            {
                "name": "name",
                "selector": "h3.faculty-directory__teaser-name",
                "type": "text",
            },
            {
                "name": "title",
                "selector": "p.faculty-directory__teaser-title",
                "type": "text",
            },
            {
                "name": "profile_url",
                "selector": "a.faculty-directory__teaser-container",
                "type": "attribute",
                "attribute": "href"
            },
             {
                "name": "image_url",
                "selector": "img",
                "type": "attribute",
                "attribute": "src"
            }
        ]
    }

    crawl_config = CrawlerRunConfig(
        extraction_strategy=JsonCssExtractionStrategy(schema),
        cache_mode=CacheMode.BYPASS,
    )
    
    # Use a fresh browser for the list
    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.arun(
            url="https://engineering.wustl.edu/faculty/index.html",
            config=crawl_config
        )
        
        if not result.success:
            print(f"❌ Failed to crawl list: {result.error_message}")
            return []
            
        data = json.loads(result.extracted_content)
        print(f"✅ Found {len(data)} faculty members.")
        return data

async def crawl_profile_details(crawler: AsyncWebCrawler, profile: Dict) -> Dict:
    """Visits a single profile page and extracts extra details."""
    
    # Fix relative URLs
    url = profile['profile_url']
    if not url.startswith("http"):
        # Handle cases like '../index.html' (self references) or relative paths
        if url.startswith(".."):
             # These are usually "Filter Faculty" dummy cards or self-refs, ignore them logic handled in main
             pass
        url = os.path.join(BASE_URL, url)
    
    # Schema for the detail page
    detail_schema = {
        "baseSelector": "body", # Root selector
        "fields": [
            {
                "name": "email",
                "selector": "a[href^='mailto:']",
                "type": "text", 
            },
            {
                "name": "research_areas",
                "selector": "div.faculty-single__researchareas ul li",
                "type": "list-text" # Get list of text items
            }
        ]
    }

    try:
        result = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(detail_schema),
                cache_mode=CacheMode.BYPASS
            )
        )
        
        if result.success:
            details = json.loads(result.extracted_content)
            # details is a list of 1 item usually because baseSelector is body
            if details:
                d = details[0]
                # data cleaning
                profile['email'] = d.get('email', '').strip()
                profile['research_interests'] = d.get('research_areas', [])
                if profile['email']:
                    print(f"  🔹 Fetched details for {profile['name']} ({profile['email']})")
                else:
                    print(f"  🔸 Fetched details for {profile['name']} (No email found)")
            else:
                 print(f"  ⚠️ No details extracted for {profile['name']}")
        else:
            print(f"  ❌ Failed detail crawl for {profile['name']}: {result.error_message}")
            
    except Exception as e:
         print(f"  ❌ Exception for {profile['name']}: {e}")

    # Standardize output format
    profile['university'] = "Washington University in St. Louis"
    profile['publications'] = [] # Not available on page
    
    return profile

async def main():
    # 1. Get the list
    faculty_list = await crawl_faculty_list()
    
    # Filter out garbage (e.g. "Filter Faculty" cards)
    clean_list = [f for f in faculty_list if "Filter Faculty" not in f.get('title', '') and f.get('name')]
    
    print(f"📋 Processing {len(clean_list)} valid profiles...")
    
    # 2. Get details (using a single crawler instance for efficiency)
    final_data = []
    
    # We'll do this in batches to be polite but fast
    batch_size = 5
    
    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        for i in range(0, len(clean_list), batch_size):
            batch = clean_list[i:i+batch_size]
            print(f"🔄 Processing batch {i+1}-{min(i+batch_size, len(clean_list))}...")
            
            tasks = [crawl_profile_details(crawler, profile) for profile in batch]
            results = await asyncio.gather(*tasks)
            final_data.extend(results)
            
            # Short sleep between batches
            await asyncio.sleep(0.5)

    # 3. Save
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_data, f, indent=2)
        
    print(f"\n🎉 Done! Saved {len(final_data)} profiles to {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
