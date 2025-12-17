import asyncio
import os
import sys
from unittest.mock import MagicMock, patch
from universal_faculty_crawler import universal_faculty_scraper, SelectorSchema

# Mock function to simulate a broken schema
async def mock_determine_schema(url, model_name):
    print("😈 Mocking broken CSS schema to force Fallback...")
    return SelectorSchema(
        base_selector="div.non_existent_class", 
        fields={"name": "span.nope", "profile_url": "a.broken"}
    )

if __name__ == "__main__":
    target_url = "https://engineering.wustl.edu/faculty/index.html" # Use WashU as it's known to work with CSS, so failure proves mocking
    
    # Patch the function in the module
    with patch("universal_faculty_crawler.determine_extraction_schema", side_effect=mock_determine_schema):
        print("🚀 Running Scraper with BROKEN CSS Schema...")
        try:
            asyncio.run(universal_faculty_scraper(target_url, model_name="openai/gpt-4o"))
        except Exception as e:
            print(f"❌ Test Failed: {e}")
