import argparse
import asyncio
import os
import json
from .crawler import UniversalScraper

def main():
    parser = argparse.ArgumentParser(description="InstiGPT Universal Faculty Scraper")
    parser.add_argument("--url", required=True, help="Target URL (e.g., https://engineering.wustl.edu/faculty/index.html)")
    parser.add_argument("--output", default="universal_faculty_data.json", help="Output JSON file name")
    parser.add_argument("--model", default="openai/gpt-4o-mini", help="LLM Model (default: openai/gpt-4o-mini)")
    
    args = parser.parse_args()
    
    # Check for API Key
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️ OPENAI_API_KEY not found. Please set it before running.")
        return

    scraper = UniversalScraper(model_name=args.model)
    data = asyncio.run(scraper.run(args.url))
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    
    print(f"\n🎉 DONE! Saved {len(data)} profiles to {args.output}")

if __name__ == "__main__":
    main()
