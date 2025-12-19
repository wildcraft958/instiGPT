import argparse
import asyncio
import os
import json
from .crawler import UniversalScraper
from .discovery import FacultyPageDiscoverer, DiscoveryResult
from .config import settings


async def run_with_discovery(
    url: str,
    model: str,
    discover_mode: str,
    prefer_local: bool
) -> list:
    """Run scraper with automatic faculty page discovery."""
    # Step 1: Discover faculty pages
    discoverer = FacultyPageDiscoverer(
        max_depth=settings.DISCOVER_MAX_DEPTH,
        max_pages=settings.DISCOVER_MAX_PAGES
    )
    
    result = await discoverer.discover(url, mode=discover_mode)
    
    if not result.pages:
        print("❌ No faculty pages discovered. Try with a different URL.")
        return []
    
    print(f"\n📋 Discovered {len(result.pages)} potential faculty pages")
    print(f"   Method: {result.discovery_method}")
    
    # Filter for directory pages (most likely to have faculty lists)
    directory_pages = [p for p in result.pages if p.page_type == "directory"]
    if not directory_pages:
        # Fall back to highest scoring pages
        directory_pages = result.faculty_pages[:5]
    
    print(f"   Processing top {len(directory_pages)} pages...")
    
    # Step 2: Scrape each discovered page
    all_profiles = []
    scraper = UniversalScraper(model_name=model)
    
    for page in directory_pages:
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
        url = p.get("profile_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
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
        "--discover-mode", choices=["sitemap", "deep", "auto"],
        default="auto",
        help="Discovery mode: sitemap (fast), deep (thorough), auto (default)"
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

