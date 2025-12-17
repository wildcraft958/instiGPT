#!/usr/bin/env python3
"""
University Faculty Web Scraper - CLI Entry Point

A hybrid web scraper that can use either:
- Cloud backend (Gemini + Ollama llama3.2)
- Local vision backend (Ollama Qwen3-VL)

Usage:
    python -m scraper_app.main --url "https://cs.university.edu/faculty" \
        --objective "Scrape all CS professors" \
        --backend auto
"""
import argparse
import sys
import logging

from .manager import CrawlerManager
from .config import settings


def main():
    parser = argparse.ArgumentParser(
        description="Universal University Faculty Web Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto mode - tries local first, falls back to cloud
  python -m scraper_app.main --url "https://engineering.wustl.edu/faculty" \\
      --objective "Scrape all engineering faculty"

  # Force Gemini (cloud) backend
  python -m scraper_app.main --url "https://olin.wustl.edu/faculty" \\
      --objective "Scrape business school faculty" --backend gemini

  # Force local vision backend
  python -m scraper_app.main --url "https://cs.stanford.edu/people" \\
      --objective "Scrape CS faculty" --backend local --headless
        """
    )
    
    # Required arguments
    parser.add_argument(
        "--url", "-u",
        required=True,
        help="Starting URL for the university faculty page"
    )
    parser.add_argument(
        "--objective", "-o",
        required=True,
        help="Scraping objective (e.g., 'Scrape all CS professors')"
    )
    
    # Backend selection
    parser.add_argument(
        "--backend", "-b",
        choices=["auto", "gemini", "local"],
        default="auto",
        help="Backend to use: auto (try local first), gemini (cloud), local (Qwen3-VL)"
    )
    
    # Browser options
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode"
    )
    
    # Crawling options
    parser.add_argument(
        "--delay",
        type=int,
        default=1000,
        help="Delay between requests in milliseconds (default: 1000)"
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=50,
        help="Maximum crawl steps (default: 50)"
    )
    
    # Output options
    parser.add_argument(
        "--output", "-O",
        default="faculty_data.json",
        help="Output JSON file (default: faculty_data.json)"
    )
    
    # Debug options
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable debug logging and save HTML/Markdown snapshots"
    )
    parser.add_argument(
        "--no-robots-check",
        action="store_true",
        help="Skip robots.txt check"
    )
    
    args = parser.parse_args()
    
    # Update settings from CLI args
    settings.REQUEST_DELAY_MS = args.delay
    settings.MAX_STEPS = args.max_steps
    settings.DEBUG_MODE = args.debug
    
    # Show configuration
    print("=" * 60)
    print("🎓 University Faculty Web Scraper")
    print("=" * 60)
    print(f"  URL:       {args.url}")
    print(f"  Objective: {args.objective}")
    print(f"  Backend:   {args.backend}")
    print(f"  Headless:  {args.headless}")
    print(f"  Max Steps: {args.max_steps}")
    print(f"  Output:    {args.output}")
    print("=" * 60)
    
    try:
        # Create and run crawler
        crawler = CrawlerManager(
            backend_mode=args.backend,
            headless=args.headless,
            debug=args.debug
        )
        
        profiles = crawler.run(
            start_url=args.url,
            objective=args.objective,
            max_steps=args.max_steps,
            check_robots=not args.no_robots_check
        )
        
        # Save results
        if profiles:
            crawler.save_results(profiles, args.output)
            print(f"\n✅ Successfully scraped {len(profiles)} faculty profiles!")
            print(f"📁 Results saved to: {args.output}")
        else:
            print("\n⚠️ No profiles were extracted.")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n🛑 Crawling interrupted by user.")
        sys.exit(130)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=args.debug)
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
