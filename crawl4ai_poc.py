import os
import asyncio
import json
from typing import List, Optional
from pydantic import BaseModel, Field
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, LLMConfig
from crawl4ai.extraction_strategy import LLMExtractionStrategy

# Define the schema for the data we want to extract
class FacultyMember(BaseModel):
    name: str = Field(..., description="Name of the faculty member")
    title: str = Field(..., description="Job title or position (e.g., Professor, Lecturer)")
    profile_url: str = Field(..., description="Full URL to their detailed profile page")
    image_url: Optional[str] = Field(None, description="URL of their profile picture")
    research_areas: Optional[str] = Field(None, description="Brief summary of research interests if available on the card")

class FacultyList(BaseModel):
    faculty: List[FacultyMember] = Field(..., description="List of faculty members found on the page")

async def main():
    print("🚀 Starting Crawl4AI Faculty Scraper POC...")

    # 1. Define the LLM extraction strategy
    # We use 'ollama/qwen3-vl' as the provider string for LiteLLM
    # We point to the local Ollama instance (default port 11434)
    llm_strategy = LLMExtractionStrategy(
        llm_config=LLMConfig(
            provider="ollama/llama3.2", # Llama 3.2 is much better at text-only JSON tasks than VLM
            base_url="http://localhost:11434",
            api_token="ollama" 
        ),
        schema=FacultyList.model_json_schema(),
        extraction_type="schema",
        instruction=(
            "You are a data extraction machine. "
            "Extract all faculty members from the input markdown. "
            "Return EXACTLY and ONLY valid JSON matching the schema. "
            "Do not add any explanations, preamble, or 'Here is the JSON'. "
            "If no faculty are found in a chunk, return empty list."
        ),
        chunk_token_threshold=2000, # Increased slightly as Llama3.2 has decent context
        overlap_rate=0.0, # No overlap needed for list items usually
        apply_chunking=True,
        input_format="markdown",
        extra_args={
            "temperature": 0.0, # Strict deterministic output
            "num_predict": 2048, # Prevent endless generation
        },
        verbose=True
    )

    # 2. Build the crawler config
    crawl_config = CrawlerRunConfig(
        extraction_strategy=llm_strategy,
        cache_mode=CacheMode.BYPASS, # Always fetch fresh content for this test
        process_iframes=False,
        remove_overlay_elements=True,
        exclude_external_links=True,
    )

    # 3. Create a browser config
    browser_cfg = BrowserConfig(
        headless=True,
        verbose=True
    )

    target_url = "https://engineering.wustl.edu/faculty/index.html"

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        print(f"🕷️  Crawling {target_url}...")
        
        result = await crawler.arun(
            url=target_url,
            config=crawl_config
        )

        if result.success:
            print("\n✅ Crawl Successful!")
            print(f"Structure Length: {len(result.extracted_content)}")
            
            # Save the raw result
            with open("faculty_crawl_result.json", "w", encoding="utf-8") as f:
                f.write(result.extracted_content)
            
            print("💾 Saved raw JSON to 'faculty_crawl_result.json'")
            
            # Try to parse it to see if it's valid
            try:
                data = json.loads(result.extracted_content)
                if "faculty" in data:
                    print(f"🎓 Found {len(data['faculty'])} faculty members.")
                    # Print first 3 as sample
                    for i, fac in enumerate(data['faculty'][:3]):
                        print(f"  {i+1}. {fac['name']} - {fac['title']}")
                else:
                    print("⚠️ JSON format valid, but 'faculty' key missing.")
            except json.JSONDecodeError:
                print("❌ Failed to parse extracted content as JSON.")
            
            # Show token usage if available
            llm_strategy.show_usage()
            
        else:
            print("❌ Crawl Failed:", result.error_message)

if __name__ == "__main__":
    # Ensure we act like we are in a main async loop
    asyncio.run(main())
