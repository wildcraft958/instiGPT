"""
Integration test: Runs full scraping flow on MIT faculty page.
This is a live test that requires API keys and network access.
"""
import asyncio
import os
import sys

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from insti_scraper.main import run_scrape_flow, setup_app


async def test_mit_scrape():
    """Test the full scraping flow on MIT faculty page."""
    target_url = "https://engineering.mit.edu/meet-our-faculty"
    
    print(f"🚀 Testing Full Scraper Pipeline on MIT: {target_url}")
    print("=" * 60)
    
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️ OPENAI_API_KEY not found! Skipping live test.")
        print("   Set OPENAI_API_KEY environment variable to run this test.")
        return
    
    try:
        setup_app()
        await run_scrape_flow(target_url, enrich=False)  # Skip enrichment for faster test
        print("\n✅ MIT Test Completed Successfully!")
    except Exception as e:
        print(f"\n❌ MIT Test Failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(test_mit_scrape())
