import asyncio
import sys
import argparse
import os
import json
from insti_scraper.orchestration.pipeline import ScrapingPipeline
from insti_scraper.core.config import settings
from insti_scraper.discovery.discovery import discover_faculty_pages

def parse_args():
    parser = argparse.ArgumentParser(description="Universal Faculty Scraper (Modular Engine)")
    
    # URL is optional if verifying or resuming, but typically required
    parser.add_argument("--url", help="Starting URL for faculty directory")
    parser.add_argument("--output", help="Output JSON file path", default="faculty_data_new.json")
    parser.add_argument("--resume", help="Resume from a JSON file (skip Phase 1 discovery)", default=None)
    
    # Discovery options
    parser.add_argument("--discover", action="store_true", help="Enable smart auto-discovery of faculty pages")
    parser.add_argument("--discovery-only", action="store_true", help="Run only list discovery (Phase 1)")
    
    parser.add_argument("--depth", type=int, default=20, help="Maximum recursion depth for discovery")
    parser.add_argument("--model", help="LLM model to use", default=settings.MODEL_NAME)
    
    # Allow positional url for backward compatibility
    parser.add_argument("pos_url", nargs="?", help="Positional URL argument")
    
    return parser.parse_args()

async def async_main():
    args = parse_args()
    
    # Handle positional URL fallback
    url = args.url or args.pos_url
    
    if not url and not args.resume:
        print("❌ Error: Must provide either --url or --resume <file>")
        sys.exit(1)

    # Determine Start URLs
    start_urls = []
    if url:
        if args.discover:
            print(f"🔍 Discovery Mode enabled. Finding faculty pages for {url}...")
            # Use auto mode which tries sitemap then deep crawl
            discovery_result = await discover_faculty_pages(
                url, 
                mode="auto",
                max_depth=3, # Limit discovery depth to keep it fast
                max_pages=30
            )
            
            # Prioritize 'directory' pages
            if discovery_result.pages:
                print(f"   Found {len(discovery_result.pages)} potential pages.")
                # Take top 5 distinct pages
                for page in discovery_result.faculty_pages[:5]:
                     print(f"   Target: {page.url} (Score: {page.score:.2f})")
                     start_urls.append(page.url)
            else:
                 print("⚠️ No specific faculty pages found. Falling back to start URL.")
                 start_urls = [url]
        else:
            start_urls = [url]
    else:
        # Resume mode
        start_urls = ["RESUME"]

    # Initialize Pipeline
    # Output dir defaults to where the output file is, or 'output_data'
    output_dir = os.path.dirname(args.output)
    if not output_dir:
        output_dir = "output_data"
        
    pipeline = ScrapingPipeline(output_dir=output_dir)
    
    all_final_data = []

    print(f"🚀 Starting scrape on {len(start_urls)} targets...")
    
    for target_url in start_urls:
        try:
            if target_url == "RESUME":
                data = await pipeline.run(start_url="RESUME", resume_file=args.resume)
                all_final_data.extend(data)
            else:
                # If we have multiple start URLs (from discovery), treat them as separate runs
                # but allow pipeline recursion within them
                data = await pipeline.run(
                    start_url=target_url,
                    discovery_only=args.discovery_only,
                    max_depth=args.depth
                )
                all_final_data.extend(data)
        except Exception as e:
            print(f"❌ Error scraping {target_url}: {e}")

    # Save aggregated output to the requested file
    if args.output and all_final_data:
        # De-duplicate by profile_url
        seen_urls = set()
        unique_data = []
        for profile in all_final_data:
            p_url = profile.get('profile_url') or profile.get('url') # Fallback
            if p_url and p_url not in seen_urls:
                seen_urls.add(p_url)
                unique_data.append(profile)
            elif not p_url:
                unique_data.append(profile)
                
        with open(args.output, 'w') as f:
            json.dump(unique_data, f, indent=2)
        print(f"\n💾 Aggregated data saved to {args.output} ({len(unique_data)} unique profiles)")
    elif not all_final_data:
        print("\n⚠️ No profiles found.")

def main():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
