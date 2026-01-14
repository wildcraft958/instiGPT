import argparse
import asyncio
import os
import json
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from .crawler import UniversalScraper
from .discovery import FacultyPageDiscoverer, DiscoveryResult
from .page_classifier import classify_page_type  # Updated to new hybrid classifier
from .config import settings


async def run_with_discovery(
    url: str,
    model: str,
    discover_mode: str,
    prefer_local: bool
) -> list:
    """Run scraper with automatic faculty page discovery and LLM validation."""
    # Step 1: Discover faculty pages (URL-based)
    discoverer = FacultyPageDiscoverer(
        max_depth=settings.DISCOVER_MAX_DEPTH,
        max_pages=settings.DISCOVER_MAX_PAGES
    )
    
    result = await discoverer.discover(url, mode=discover_mode, model=model)
    
    if not result.pages:
        print("❌ No faculty pages discovered. Try with a different URL.")
        return []
    
    print(f"\n📋 Discovered {len(result.pages)} potential faculty pages")
    print(f"   Method: {result.discovery_method}")
    
    # Step 2: LLM-based validation of top candidates
    # IMPORTANT: Exclude profile pages (individual person pages) - only validate directories
    directory_candidates = [p for p in result.faculty_pages if p.page_type != "profile"]
    candidates = directory_candidates[:10]
    
    print(f"\n🤖 Validating top {len(candidates)} pages with LLM...")
    validated_pages = []
    
    browser_config = BrowserConfig(headless=True, verbose=False)
    run_config = CrawlerRunConfig(cache_mode=CacheMode.ENABLED)
    
    async with AsyncWebCrawler(config=browser_config) as crawler:
        for page in candidates:
            try:
                # Fetch page content
                res = await crawler.arun(page.url, config=run_config)
                if not res.success:
                    continue
                
                # Classify with LLM
                classification = await classify_page_type(page.url, res.html or "", model)
                
                page_type = classification.get("page_type", "other")
                confidence = classification.get("confidence", 0)
                reason = classification.get("reason", "")
                
                if page_type == "faculty_directory" and confidence >= 0.6:
                    print(f"   ✅ {page.url}")
                    print(f"      → Faculty Directory (confidence: {confidence:.0%})")
                    validated_pages.append(page)
                else:
                    print(f"   ❌ {page.url}")
                    print(f"      → {page_type} ({reason[:50]}...)")
                    
            except Exception as e:
                print(f"   ⚠️ Error validating {page.url}: {e}")
    
    if not validated_pages:
        print("\n❌ No faculty directories found after LLM validation.")
        print("   Try a specific department URL like: https://nse.mit.edu/people")
        return []
    
    print(f"\n📊 Found {len(validated_pages)} validated faculty directories")
    
    # Step 3: Scrape validated pages
    all_profiles = []
    scraper = UniversalScraper(model_name=model)
    
    for page in validated_pages[:3]:  # Limit to top 3 to avoid over-extraction
        print(f"\n🔍 Scraping: {page.url}")
        try:
            profiles = await scraper.run(page.url)
            all_profiles.extend(profiles)
            print(f"   Found {len(profiles)} profiles")
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    # Deduplicate by profile URL
    seen_urls = set()
    unique_profiles = []
    for p in all_profiles:
        profile_url = p.get("profile_url", "")
        if profile_url and profile_url not in seen_urls:
            seen_urls.add(profile_url)
            unique_profiles.append(p)
    
    return unique_profiles


def main():
    parser = argparse.ArgumentParser(
        description="InstiGPT Universal Faculty Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Direct URL (existing behavior)
  insti-scraper --url "https://university.edu/faculty"
  
  # Auto-discover faculty pages from any URL
  insti-scraper --url "https://university.edu" --discover
  
  # Use Ollama for free local inference
  insti-scraper --url "https://university.edu" --model "ollama/llama3.1:8b"
        """
    )
    
    # Required arguments
    parser.add_argument(
        "--url", required=True,
        help="Target URL (can be homepage if using --discover)"
    )
    
    # Output options
    parser.add_argument(
        "--output", default="faculty_data.json",
        help="Output JSON file name (default: faculty_data.json)"
    )
    
    # Model options
    parser.add_argument(
        "--model", default=None,
        help="LLM Model (default: gpt-4o-mini, or ollama if OLLAMA_BASE_URL is set)"
    )
    parser.add_argument(
        "--prefer-local", action="store_true",
        help="Prefer Ollama models when available (saves API costs)"
    )
    
    # Discovery options
    parser.add_argument(
        "--discover", action="store_true",
        help="Enable auto-discovery from any URL (not just faculty pages)"
    )
    parser.add_argument(
        "--discover-mode", choices=["search", "sitemap", "deep", "auto"],
        default="auto",
        help="Discovery mode: search (DuckDuckGo, default), sitemap, deep, auto"
    )
    
    args = parser.parse_args()
    
    # Determine model to use
    if args.model:
        model = args.model
    elif args.prefer_local and settings.is_ollama_available():
        model = settings.get_model_for_task("schema_discovery", prefer_local=True)
        print(f"🏠 Using local Ollama model: {model}")
    else:
        model = settings.MODEL_NAME
    
    # Check for API Key (not needed for Ollama)
    if not "ollama" in model.lower() and not os.getenv("OPENAI_API_KEY"):
        print("⚠️ OPENAI_API_KEY not found. Please set it or use --prefer-local with Ollama.")
        return
    
    # Run with or without discovery
    if args.discover:
        print(f"🔍 Discovery mode enabled ({args.discover_mode})")
        data = asyncio.run(run_with_discovery(
            args.url, model, args.discover_mode, args.prefer_local
        ))
    else:
        scraper = UniversalScraper(model_name=model)
        data = asyncio.run(scraper.run(args.url))
    
    # Save results
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    
    print(f"\n🎉 DONE! Saved {len(data)} profiles to {args.output}")


if __name__ == "__main__":
    main()

