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
