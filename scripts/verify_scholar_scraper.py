
import os
import sys

# Ensure the project root is in the python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from insti_scraper.scrapers.google_scholar_scraper import GoogleScholarScraper
from dotenv import load_dotenv

load_dotenv()

import asyncio

async def verify():
    print("🧪 Verifying Google Scholar Scraper (Async)...")
    
    # Test Data: Professor Inder Sekhar Yadav from IIT Kharagpur (known to have a profile)
    test_profile = {
        "name": "Inder Sekhar Yadav",
        "university": "IIT Kharagpur",
        "department": "Humanities"
    }
    
    scraper = GoogleScholarScraper()
    result = await scraper.enrich_profile(test_profile)
    
    if result.get('h_index') and result.get('total_citations'):
        print("\n✅ Verification SUCCESS!")
        print(f"Name: {result['name']}")
        print(f"URL: {result.get('google_scholar_url')}")
        print(f"H-index: {result.get('h_index')}")
        print(f"Total Citations: {result.get('total_citations')}")
        print(f"Top Paper: {result.get('paper_titles')[0] if result.get('paper_titles') else 'None'}")
    else:
        print("\n❌ Verification FAILED.")
        print(f"Error: {result.get('google_scholar_error', 'Unknown error')}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(verify())
