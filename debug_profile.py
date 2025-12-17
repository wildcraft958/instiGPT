import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

async def main():
    url = "https://engineering.wustl.edu/faculty/Peizhen-Zhu.html"
    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
        )
        print("--- MARKDOWN START ---")
        print(result.markdown)
        print("--- MARKDOWN END ---")

if __name__ == "__main__":
    asyncio.run(main())
