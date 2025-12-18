import asyncio
import os
from universal_faculty_crawler import universal_faculty_scraper

if __name__ == "__main__":
    target_url = "https://engineering.mit.edu/meet-our-faculty"
    
    # We need to monkey-patch the output filename in the imported module 
    # OR better, update the main script to accept an output filename.
    # For now, let's just run it. It will overwrite universal_faculty_data.json, 
    # but that's fine for a demo.
    
    print(f"🚀 Testing Universal Scraper on MIT: {target_url}")
    
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️ OPENAI_API_KEY not found!")
        exit(1)
        
    asyncio.run(universal_faculty_scraper(target_url, model_name="openai/gpt-4o"))
