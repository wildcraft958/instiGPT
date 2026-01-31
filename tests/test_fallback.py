import asyncio
import os
import sys
# Add parent dir to path so we can import insti_scraper
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
from insti_scraper.crawler import UniversalScraper
from insti_scraper.models import SelectorSchema

# Mock function to simulate a broken schema
async def mock_determine_schema(url, model_name):
    print("😈 Mocking broken CSS schema to force Fallback...")
    return SelectorSchema(
        base_selector="div.non_existent_class", 
        fields={"name": "span.nope", "profile_url": "a.broken"}
    )

if __name__ == "__main__":
    target_url = "https://engineering.wustl.edu/faculty/index.html" # Use WashU as it's known to work with CSS, so failure proves mocking
    
    # Patch the function in the crawler module
    with patch("insti_scraper.crawler.determine_extraction_schema", side_effect=mock_determine_schema):
        print("🚀 Running Scraper with BROKEN CSS Schema...")
        try:
            scraper = UniversalScraper(model_name="openai/gpt-4o")
            asyncio.run(scraper.run(target_url))
        except Exception as e:
            print(f"❌ Test Failed: {e}")

