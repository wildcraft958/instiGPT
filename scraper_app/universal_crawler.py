import asyncio
import json
import os
from typing import List, Dict, Optional
from pydantic import BaseModel, Field

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, LLMConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy, LLMExtractionStrategy

# Configuration
# OLLAMA_BASE_URL = "http://localhost:11434"
# Using GPT-4o for robust selector generation
MODEL_NAME = "openai/gpt-4o" 

class SelectorSchema(BaseModel):
    base_selector: str = Field(..., description="The CSS selector for the repeating container element (e.g. 'div.card', 'tr.row')")
    fields: Dict[str, str] = Field(..., description="Map of field names to their relative CSS selectors (e.g. {'name': 'h3', 'link': 'a.profile'}")

async def analyze_page_structure(url: str, fields_to_extract: List[str]) -> SelectorSchema:
    """
    Uses LLM to analyze the page and deduce CSS selectors.
    """
    print(f"🧠 [Universal] Analyzing structure of {url}...")
    
    # 1. Fetch the raw HTML structure (minimized)
    # We use a lightweight config just to get the HTML/Markdown
    browser_conf = BrowserConfig(headless=True)
    run_conf = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        # We don't need extraction yet, just the raw content
    )
    
    async with AsyncWebCrawler(config=browser_conf) as crawler:
        result = await crawler.arun(url=url, config=run_conf)
        
        if not result.success:
            raise Exception(f"Failed to fetch page for analysis: {result.error_message}")
    
    # 2. Prepare prompt for LLM
    html_content = result.html
    
    # Better heuristic: Find the main content area to avoid nav noise
    start_index = 0
    if "<main" in html_content:
        start_index = html_content.find("<main")
    elif 'role="main"' in html_content:
        start_index = html_content.find('role="main"')
    elif "<article" in html_content:
        start_index = html_content.find("<article")
    elif "<body" in html_content:
        start_index = html_content.find("<body")
        
    # Take a larger chunk (50k chars) to match modern context windows
    # ensuring we get deep enough into the lists
    content_sample = html_content[start_index : start_index + 40000]

    # 3. Call LLM with System Prompt + Few Shot to enforce behavior
    
    system_prompt = """You are a Web Scraping Configuration Tool.
    Your ONLY job is to return a JSON configuration with CSS selectors based on the provided HTML.
    
    NEVER extract the actual data content.
    NEVER return 'faculties' or 'employees' lists.
    ONLY return 'base_selector' and 'fields'.
    """
    
    user_prompt = f"""
    Goal: Find CSS selectors to extract a list of items.
    Target Fields: {', '.join(fields_to_extract)}

    --- ONE-SHOT EXAMPLE ---
    Input HTML:
    <ul class="product-list">
      <li class="p-item">
         <h3 class="name">Widget A</h3>
         <span class="price">$10</span>
      </li>
      <li class="p-item">
         <h3 class="name">Widget B</h3>
         <span class="price">$20</span>
      </li>
    </ul>

    Output JSON:
    {{
      "base_selector": "li.p-item",
      "fields": {{
        "name": "h3.name",
        "price": "span.price"
      }}
    }}
    ------------------------

    Now analyze THIS HTML and return the JSON config:
    {content_sample}
    
    RETURN ONLY JSON.
    """
    
    # 3. Call LLM using LiteLLM (supports OpenAI, Gemini, Ollama, etc.)
    from litellm import completion
    import os
    
    # Example config for users to swap:
    # model="ollama/llama3.2" (Local)
    # model="openai/gpt-4o" (Needs OPENAI_API_KEY)
    # model="gemini/gemini-1.5-pro" (Needs GEMINI_API_KEY)
    
    try:
        print(f"🤖 Asking LLM ({MODEL_NAME}) to analyze structure...")
        
        response = completion(
            model=MODEL_NAME, 
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ],
            response_format={"type": "json_object"}, # Works for OpenAI/Ollama recent versions
            api_base=OLLAMA_BASE_URL if "ollama" in MODEL_NAME else None
        )
        
        content = response.choices[0].message.content
        print(f"🔍 Raw LLM Response: {content}") 
        
        data = json.loads(content)
        
        # Validate/clean keys
        if 'baseSelector' in data: data['base_selector'] = data.pop('baseSelector')
        
        # Validation Hack: If fields is a list, try to fix it or ignore
        if isinstance(data.get('fields'), list):
            print("⚠️ LLM returned fields as list. Attempting to fix...")
            # If list contains strings, maybe these are the selectors? No, likely garbage or attributes.
            # We can't easily recover. Let's try to map target fields to generic tags if possible, or just fail gracefully.
            # actually, if we have base_selector, we can fallback to generic tags for common fields
            fixed_fields = {}
            tags = ['h2', 'h3', 'h4', 'span', 'p', 'a']
            for i, field in enumerate(fields_to_extract):
                if i < len(tags):
                    fixed_fields[field] = tags[i]
            print(f"⚠️ Fallback fields: {fixed_fields}")
            data['fields'] = fixed_fields

        return SelectorSchema(base_selector=data.get('base_selector', 'div'), fields=data.get('fields', {}))
        
    except Exception as e:
        print(f"❌ LLM Analysis failed: {e}")
        if 'content' in locals():
            print(f"Context: {content}")
        # Fallback to generic text search
        return SelectorSchema(base_selector="div", fields={})

async def universal_crawl(url: str, fields: List[str]):
    
    # Step 1: Analyze
    try:
        schema_plan = await analyze_page_structure(url, fields)
        print(f"✅ Generated Schema: {schema_plan}")
    except Exception as e:
        print(f"Analysis failed: {e}")
        return

    # Step 2: Configure Crawler with deduced schema
    # Map the simple schema to Crawl4AI's specific structure
    
    css_fields = []
    for field_name, selector in schema_plan.fields.items():
        field_def = {
            "name": field_name,
            "selector": selector,
            "type": "text"
        }
        # Heuristic: if field is 'url' or 'link' or 'image', likely an attribute
        if 'url' in field_name or 'link' in field_name:
            field_def['type'] = "attribute"
            field_def['attribute'] = "href"
        if 'image' in field_name or 'img' in field_name:
            field_def['type'] = "attribute"
            field_def['attribute'] = "src"
            
        css_fields.append(field_def)

    extraction_strategy = JsonCssExtractionStrategy({
        "baseSelector": schema_plan.base_selector,
        "fields": css_fields
    })
    
    print("🚀 Executing Universal Crawl...")
    
    async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
        result = await crawler.arun(
            url=url,
            config=CrawlerRunConfig(
                extraction_strategy=extraction_strategy,
                cache_mode=CacheMode.BYPASS
            )
        )
        
        if result.success:
            print(f"🎉 Success! Extracted {len(json.loads(result.extracted_content))} items.")
            print(result.extracted_content[:500] + "...")
        else:
            print(f"❌ Crawl failed: {result.error_message}")

# Interface
if __name__ == "__main__":
    target = "https://engineering.wustl.edu/faculty/index.html"
    wanted_fields = ["name", "title", "profile_url"]
    
    asyncio.run(universal_crawl(target, wanted_fields))
