"""
Vision-based page analyzer using screenshots + multimodal LLM.

Uses GPT-4o-mini with vision to detect pagination patterns automatically.
"""

import base64
import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional, List
from pathlib import Path

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from litellm import completion

from ..core.auto_config import PaginationInfo


@dataclass
class VisualAnalysisResult:
    """Result of vision-based page analysis."""
    pagination_type: str = "unknown"  # datatable, infinite_scroll, click, alpha, none
    total_items: int = 0
    items_per_page: int = 10
    max_pages_needed: int = 10
    next_button_selector: Optional[str] = None
    confidence: float = 0.0
    description: str = ""
    detected_patterns: List[str] = field(default_factory=list)
    
    def to_pagination_info(self) -> PaginationInfo:
        """Convert to PaginationInfo for compatibility."""
        return PaginationInfo(
            total_items=self.total_items,
            items_per_page=self.items_per_page,
            total_pages=self.max_pages_needed,
            pagination_type=self.pagination_type,
            next_selector=self.next_button_selector
        )


VISION_PROMPT = """Analyze this webpage screenshot to identify the pagination mechanism for data extraction.

## Your Task
1. Identify the TYPE of pagination (or lack thereof)
2. Find the TOTAL number of items (look for "Showing X of Y", "1,661 entries", etc.)
3. Determine items PER PAGE
4. Describe how to navigate to the next page

## Pagination Types
- **datatable**: DataTables library with "Show X entries" dropdown and numbered pages
- **infinite_scroll**: No visible pagination, content loads on scroll
- **click**: Traditional "Next" / "→" buttons or numbered page links
- **alpha**: A-Z alphabetical filter tabs
- **load_more**: Single "Load More" button
- **none**: All content visible on single page

## Output Format
Return ONLY valid JSON:
```json
{
    "pagination_type": "datatable|infinite_scroll|click|alpha|load_more|none",
    "total_items": 0,
    "items_per_page": 10,
    "max_pages_needed": 1,
    "next_button_description": "Description of next button location/appearance",
    "next_button_selector_hint": "CSS selector hint like '.next-btn' or 'a[rel=next]'",
    "confidence": 0.8,
    "detected_patterns": ["list of visual cues found"]
}
```

Look carefully for:
- "Showing 1 to 10 of 1,661 entries" → total_items=1661, items_per_page=10
- Dropdown with "10 / 25 / 50 / 100" options → datatable
- "Page 1 of 167" → max_pages_needed=167
- Scroll indicators at bottom → infinite_scroll
- A B C D ... Z tabs → alpha"""


class VisionPageAnalyzer:
    """
    Analyzes webpages using screenshots and multimodal LLM.
    
    Uses GPT-4o-mini vision to automatically detect:
    - Pagination mechanism type
    - Total item count
    - Items per page
    - Next button location
    """
    
    def __init__(self, model: str = "openai/gpt-4o-mini"):
        """
        Initialize the vision analyzer.
        
        Args:
            model: LLM model to use. Must support vision (e.g., gpt-4o, gpt-4o-mini)
        """
        self.model = model
        self._screenshot_cache: dict = {}
    
    async def capture_screenshot(self, url: str) -> Optional[bytes]:
        """
        Capture a screenshot of a webpage.
        
        Args:
            url: URL to capture
            
        Returns:
            Screenshot as bytes, or None on failure
        """
        browser_config = BrowserConfig(headless=True, verbose=False)
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            screenshot=True,
            screenshot_wait_for=3.0  # Wait for dynamic content
        )
        
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)
            
            if result.success and result.screenshot:
                return result.screenshot
        
        return None
    
    async def analyze_screenshot(
        self, 
        screenshot_data,  # Can be bytes or base64 string
        url: str = ""
    ) -> VisualAnalysisResult:
        """
        Analyze a screenshot using vision LLM.
        
        Args:
            screenshot_data: Screenshot as bytes or base64 string
            url: Original URL (for context)
            
        Returns:
            VisualAnalysisResult with detected pagination info
        """
        import io
        
        try:
            from PIL import Image
        except ImportError:
            print("  ⚠️ PIL not installed, run: uv add pillow")
            return VisualAnalysisResult()
        
        # Handle both bytes and base64 string
        if isinstance(screenshot_data, bytes):
            img_bytes = screenshot_data
        else:
            # Decode base64 string from Crawl4AI
            img_bytes = base64.b64decode(screenshot_data)
        
        # Convert to PNG (OpenAI only accepts PNG/JPEG/GIF/WebP)
        try:
            img = Image.open(io.BytesIO(img_bytes))
            # Resize to reduce size (max 2000px width)
            max_width = 1500
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # Convert to JPEG (smaller than PNG)
            png_buffer = io.BytesIO()
            img.convert('RGB').save(png_buffer, format='JPEG', quality=70)
            png_bytes = png_buffer.getvalue()
            screenshot_b64 = base64.b64encode(png_bytes).decode('utf-8')
        except Exception as e:
            print(f"  ⚠️ Image conversion error: {e}")
            return VisualAnalysisResult()
        
        try:
            response = completion(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}",
                                    "detail": "low"  # Use low detail to reduce cost
                                }
                            }
                        ]
                    }
                ],
                temperature=0,
                max_tokens=500
            )
            
            content = response.choices[0].message.content
            
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                data = json.loads(json_match.group())
                
                result = VisualAnalysisResult(
                    pagination_type=data.get("pagination_type", "unknown"),
                    total_items=int(data.get("total_items", 0)),
                    items_per_page=int(data.get("items_per_page", 10)),
                    max_pages_needed=int(data.get("max_pages_needed", 10)),
                    next_button_selector=data.get("next_button_selector_hint"),
                    confidence=float(data.get("confidence", 0.5)),
                    description=data.get("next_button_description", ""),
                    detected_patterns=data.get("detected_patterns", [])
                )
                
                # Auto-calculate pages if total provided but pages not
                if result.total_items > 0 and result.max_pages_needed <= 1:
                    result.max_pages_needed = min(
                        (result.total_items + result.items_per_page - 1) // result.items_per_page,
                        100
                    )
                
                return result
                
        except Exception as e:
            print(f"  ⚠️ Vision analysis error: {e}")
        
        # Return default on failure
        return VisualAnalysisResult()
    
    async def analyze(self, url: str) -> VisualAnalysisResult:
        """
        Full analysis pipeline: capture screenshot and analyze.
        
        Args:
            url: URL to analyze
            
        Returns:
            VisualAnalysisResult with pagination info
        """
        print(f"📸 Capturing screenshot of {url}...")
        screenshot = await self.capture_screenshot(url)
        
        if screenshot is None:
            print("  ⚠️ Screenshot capture failed, using defaults")
            return VisualAnalysisResult()
        
        print(f"🔮 Analyzing with {self.model}...")
        result = await self.analyze_screenshot(screenshot, url)
        
        print(f"  ✅ Detected: {result.pagination_type}")
        print(f"  📊 Total: {result.total_items}, Per page: {result.items_per_page}")
        print(f"  📄 Pages needed: {result.max_pages_needed}")
        
        return result


async def analyze_page_with_vision(
    url: str,
    model: str = "openai/gpt-4o-mini"
) -> VisualAnalysisResult:
    """
    Convenience function to analyze a page with vision.
    
    Args:
        url: URL to analyze
        model: Vision model to use
        
    Returns:
        VisualAnalysisResult
    """
    analyzer = VisionPageAnalyzer(model=model)
    return await analyzer.analyze(url)
