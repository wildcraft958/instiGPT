import asyncio
import sys
import argparse
from insti_scraper.orchestration.pipeline import ScrapingPipeline
from insti_scraper.config import settings

def parse_args():
    parser = argparse.ArgumentParser(description="Universal Faculty Scraper (Modular Engine)")
    parser.add_argument("url", help="Starting URL for faculty directory", nargs="?")
    parser.add_argument("--resume", help="Resume from a JSON file (skip Phase 1 discovery)", default=None)
    parser.add_argument("--phase1-only", action="store_true", help="Run only list discovery (Phase 1)")
    parser.add_argument("--model", help="LLM model to use", default=settings.MODEL_NAME)
    return parser.parse_args()

async def main():
    args = parse_args()
    
    if not args.url and not args.resume:
        print("❌ Error: Must provide either a URL or --resume <file>")
        sys.exit(1)

    url = args.url if args.url else "RESUME_MODE"
    
    # Initialize Pipeline
    pipeline = ScrapingPipeline(output_dir="output_data")
    
    # Run
    await pipeline.run(
        start_url=url,
        phase1_only=args.phase1_only,
        resume_file=args.resume
    )

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
