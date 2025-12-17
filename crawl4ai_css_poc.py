import asyncio
import json
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

async def main():
    print("🚀 Starting Crawl4AI CSS Extraction POC...")

    # True schema based on inspecting page.html
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

    # Since I don't know the exact selectors yet (because the previous LLM attempt failed),
    # I will first try to just DUMP the HTML structure so I can see the classes.
    # BUT, I will try a generic crawl first.
    
    extraction_strategy = JsonCssExtractionStrategy(schema)

    crawl_config = CrawlerRunConfig(
        extraction_strategy=extraction_strategy,
        cache_mode=CacheMode.BYPASS,
    )

    browser_config = BrowserConfig(headless=True)

    target_url = "https://engineering.wustl.edu/faculty/index.html"

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=target_url, config=crawl_config)

        if result.success:
            print("\n✅ CSS Crawl Successful!")
            # Save raw content specifically to inspect HTML if needed
            with open("faculty_page_dump.html", "w", encoding="utf-8") as f:
                f.write(result.html)
            
            print(f"Extracted Content Length: {len(result.extracted_content)}")
            print("Extracted Content Preview:", result.extracted_content[:500])
            
            # Also printing the markdown structure can help guess selectors
            with open("faculty_page.md", "w", encoding="utf-8") as f:
                f.write(result.markdown)
                
        else:
            print("❌ CSS Crawl Failed:", result.error_message)

if __name__ == "__main__":
    asyncio.run(main())
