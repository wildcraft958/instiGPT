import os
import json
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, LLMConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy, LLMExtractionStrategy
from .models import SelectorSchema, FallbackProfileSchema, FacultyDetail
from .config import settings

async def determine_extraction_schema(url: str, model_name: str) -> SelectorSchema:
    """Determines the CSS extraction schema for a given URL using LLM analysis."""
    print(f"🧠 Analyzing structure of {url}...")
    
    browser_conf = BrowserConfig(headless=True)
    run_conf = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
    
    async with AsyncWebCrawler(config=browser_conf) as crawler:
        result = await crawler.arun(url=url, config=run_conf)
        if not result.success:
            raise Exception(f"Failed to fetch page for analysis: {result.error_message}")
    
    html_content = result.html
    # Optimize content for LLM
    start_index = 0
    if "<main" in html_content: start_index = html_content.find("<main")
    elif 'role="main"' in html_content: start_index = html_content.find('role="main"')
    elif "<article" in html_content: start_index = html_content.find("<article")
    elif "<body" in html_content: start_index = html_content.find("<body")
        
    content_sample = html_content[start_index : start_index + 40000]

    from litellm import completion
    
    system_prompt = """You are a Web Scraping Configuration Tool.
    Your ONLY job is to return a JSON configuration with CSS selectors based on the provided HTML.
    NEVER extract the actual data content.
    ONLY return 'base_selector' and 'fields'.
    """
    
    user_prompt = f"""
    Goal: Find CSS selectors to extract a list of faculty profiles.
    Target Fields: name, profile_url, title
    
    Input HTML:
    {content_sample}
    
    RETURN ONLY JSON fitting SelectorSchema.
    """
    
    print(f"🤖 Asking LLM ({model_name}) to analyze structure...")
    response = completion(
        model=model_name,
        messages=[{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_prompt}],
        response_format={"type": "json_object"},
        api_base=os.getenv("OLLAMA_BASE_URL") if "ollama" in model_name else None
    )
    
    content = response.choices[0].message.content
    data = json.loads(content)
    
    # Normalize keys
    if 'baseSelector' in data: data['base_selector'] = data.pop('baseSelector')
    
    return SelectorSchema(base_selector=data.get('base_selector', 'div'), fields=data.get('fields', {}))

def create_css_strategy(schema: SelectorSchema) -> JsonCssExtractionStrategy:
    css_schema_dict = {
        "baseSelector": schema.base_selector,
        "fields": []
    }
    for name, selector in schema.fields.items():
        field_def = {"name": name, "selector": selector, "type": "text"}
        if "href" in selector or "url" in name.lower() or "link" in name.lower():
            field_def["type"] = "attribute"
            field_def["attribute"] = "href"
        elif "src" in selector or "image" in name.lower() or "img" in name.lower():
            field_def["type"] = "attribute"
            field_def["attribute"] = "src"
        css_schema_dict["fields"].append(field_def)
    
    return JsonCssExtractionStrategy(schema=css_schema_dict)

def create_fallback_strategy(model_name: str) -> LLMExtractionStrategy:
    return LLMExtractionStrategy(
        llm_config=LLMConfig(provider=model_name, api_token=os.getenv("OPENAI_API_KEY")),
        instruction="Find all faculty/staff profile URLs, names, and titles in this content. Return a JSON list of objects, each with 'name', 'profile_url', and optionally 'title'.",
        schema=FallbackProfileSchema.model_json_schema(),
        extraction_type="schema"
    )

def create_detail_strategy(model_name: str) -> LLMExtractionStrategy:
    return LLMExtractionStrategy(
        llm_config=LLMConfig(provider=model_name, api_token=os.getenv("OPENAI_API_KEY")),
        schema=FacultyDetail.model_json_schema(),
        extraction_type="schema",
        instruction=(
            "Extract the following:"
            "1. Email (look for mailto links or evident email text)."
            "2. Research Interests: Look for sections named 'Research', 'Expertise', or 'Current Work'. "
            "   - If it's a list, extract items."
            "   - If it's a paragraph, summarize key topics/areas into a list."
            "3. Publications: Look for 'Selected Publications' or similar lists. Max 5."
            "If 'Research' is missing, check 'Expertise' or 'Biography' for implied interests."
        ),
        chunk_token_threshold=4000,
        input_format="markdown",
        verbose=False
    )


async def classify_page_type(url: str, html_content: str, model_name: str) -> dict:
    """
    Use LLM to classify a page type based on its content.
    Returns dict with 'page_type' and 'confidence' (0-1).
    
    Page types:
    - faculty_directory: List of faculty members with names, titles, profile links
    - staff_directory: List of non-academic staff
    - policy: HR policies, procedures, guidelines
    - news: News articles, events, announcements
    - other: Any other type of page
    """
    from litellm import completion
    
    # Take a sample of the content
    content_sample = html_content[:15000] if html_content else ""
    
    system_prompt = """You are a page classifier. Analyze the webpage content and classify it.
Return JSON with exactly these fields:
- page_type: one of 'faculty_directory', 'staff_directory', 'policy', 'news', 'other'
- confidence: float between 0.0 and 1.0
- reason: brief explanation

Classification criteria:
- faculty_directory: Page listing ACADEMIC faculty/professors with names, often with photos, emails, titles like "Professor", "PhD", research areas
- staff_directory: Page listing administrative/support staff (HR, admin assistants, etc)
- policy: HR policies, leave policies, procedures, guidelines documents
- news: News articles, event announcements, press releases
- other: Homepage, about page, statistics, or anything else"""

    user_prompt = f"""URL: {url}

Page content:
{content_sample}

Classify this page. Return only valid JSON."""

    try:
        response = completion(
            model=model_name,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ],
            response_format={"type": "json_object"},
            api_base=os.getenv("OLLAMA_BASE_URL") if "ollama" in model_name.lower() else None
        )
        
        result = json.loads(response.choices[0].message.content)
        return {
            "page_type": result.get("page_type", "other"),
            "confidence": float(result.get("confidence", 0.5)),
            "reason": result.get("reason", "")
        }
    except Exception as e:
        return {"page_type": "other", "confidence": 0.0, "reason": str(e)}
