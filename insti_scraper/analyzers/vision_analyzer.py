"""
Comprehensive Vision Page Analyzer with 10 AI-Powered Features.

Features:
1. CSS Selector Generation - Vision-based element identification
2. Schema from Screenshots - Visual schema extraction  
3. Vision Page Classifier - Pure vision classification
4. CAPTCHA/Block Detection - Auto-detect access blocks
5. Dynamic Wait Detection - Visual stability detection
6. Infinite Scroll Depth - Spinner/end detection
7. Multi-Language Support - Language-agnostic prompts
8. Error Recovery Guidance - Visual failure diagnosis
9. Mobile/Desktop Detection - Viewport auto-switching
10. Domain Pre-Analysis - Cache analysis per domain
"""

import base64
import io
import json
import os
import re
import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from litellm import completion

from ..core.auto_config import PaginationInfo


# =============================================================================
# Data Classes
# =============================================================================

class PageType(Enum):
    """Page classification types."""
    DIRECTORY_CLICKABLE = "A"  # Faculty list with clickable profiles
    DIRECTORY_VISIBLE = "B"   # Faculty cards with visible info
    DEPARTMENT_GATEWAY = "C"  # Links to sub-pages
    PAGINATED_LIST = "D"      # DataTable or paginated content
    SEARCH_INTERFACE = "E"    # Search/filter interface
    INDIVIDUAL_PROFILE = "F"  # Single person page
    BLOCKED = "Z"             # CAPTCHA, login, etc.
    UNKNOWN = "X"


class BlockType(Enum):
    """Types of access blocks."""
    NONE = "none"
    CAPTCHA = "captcha"
    LOGIN_REQUIRED = "login"
    COOKIE_CONSENT = "cookie"
    CLOUDFLARE = "cloudflare"
    RATE_LIMITED = "rate_limit"
    PAYWALL = "paywall"
    ERROR_PAGE = "error"


class ViewportType(Enum):
    """Detected viewport type."""
    DESKTOP = "desktop"
    TABLET = "tablet"
    MOBILE = "mobile"


@dataclass
class VisualAnalysisResult:
    """Comprehensive result of vision-based page analysis."""
    # Pagination (Feature 1, 2)
    pagination_type: str = "unknown"
    total_items: int = 0
    items_per_page: int = 10
    max_pages_needed: int = 10
    next_button_selector: Optional[str] = None
    
    # Page Classification (Feature 3)
    page_type: PageType = PageType.UNKNOWN
    page_type_confidence: float = 0.0
    page_type_reason: str = ""
    
    # Block Detection (Feature 4)
    block_type: BlockType = BlockType.NONE
    block_description: str = ""
    
    # Content State (Feature 5, 6)
    content_loaded: bool = True
    has_loading_indicator: bool = False
    has_infinite_scroll: bool = False
    scroll_end_detected: bool = False
    
    # Viewport (Feature 9)
    detected_viewport: ViewportType = ViewportType.DESKTOP
    recommended_viewport: ViewportType = ViewportType.DESKTOP
    
    # Schema Hints (Feature 2)
    schema_hints: Dict[str, str] = field(default_factory=dict)
    
    # Recovery (Feature 8)
    recovery_suggestions: List[str] = field(default_factory=list)
    
    # Meta
    confidence: float = 0.0
    detected_patterns: List[str] = field(default_factory=list)
    language_detected: str = "en"
    
    # [NEW] Visual Anchors for Selector Generation
    sample_names: List[str] = field(default_factory=list)
    
    def to_pagination_info(self) -> PaginationInfo:
        """Convert to PaginationInfo for compatibility."""
        return PaginationInfo(
            total_items=self.total_items,
            items_per_page=self.items_per_page,
            total_pages=self.max_pages_needed,
            pagination_type=self.pagination_type,
            next_selector=self.next_button_selector
        )
    
    def is_blocked(self) -> bool:
        """Check if page access is blocked."""
        return self.block_type != BlockType.NONE
    
    def needs_mobile(self) -> bool:
        """Check if mobile viewport is recommended."""
        return self.recommended_viewport == ViewportType.MOBILE


@dataclass
class DomainProfile:
    """Cached analysis for an entire domain."""
    domain: str
    pagination_type: str
    typical_items_per_page: int
    common_selectors: Dict[str, str]
    has_captcha: bool
    preferred_viewport: ViewportType
    language: str
    analyzed_at: str
    sample_urls: List[str]


# =============================================================================
# Prompts
# =============================================================================

COMPREHENSIVE_VISION_PROMPT = """Analyze this webpage screenshot comprehensively for web scraping.

## ANALYSIS TASKS

### 1. PAGINATION
- Type: datatable | infinite_scroll | click | alpha | load_more | none
- Find total items (look for "X entries", "X results", "Page X of Y")
- Items per page
- Next button location/selector hint

### 2. PAGE CLASSIFICATION
- A: Directory with clickable profile links AND profile images (or placeholders)
- B: Cards/list with visible contact info AND profile images
- C: Department gateway (links to sub-pages, usually text-only or icon-based)
- D: Paginated DataTable
- E: Search/filter interface
- F: Individual profile page
- Z: Blocked/inaccessible

CRITICAL: If a list DOES NOT have profile images/photos for people, it is likely Type C (Gateway) or a Contact List, NOT a Faculty Directory (A/B). Faculty directories almost always have photos.

### 3. ACCESS BLOCKS (check carefully!)
- CAPTCHA (reCAPTCHA, hCaptcha images)
- Login form blocking content
- Cookie consent overlay
- Cloudflare challenge
- Rate limit message
- Paywall

### 4. CONTENT STATE
- Is main content visible or still loading?
- Any loading spinners/skeletons?
- "Load more" or "Show all" buttons?

### 5. VIEWPORT
- Is this desktop or mobile layout?
- Hamburger menu visible? (indicates mobile)
- Content too wide/narrow?

### 6. SCHEMA HINTS
For faculty/people listings, identify:
- Container element pattern (card, row, table row)
- Name element location
- Link/URL pattern
- Title/position location
- Email pattern

### 7. LANGUAGE
What is the primary language of content?

### 8. VISUAL ANCHORS (New!)
Identify 3-4 distinct faculty/person names visible in the screenshot.
- Choose names that look like they are part of the main list/grid.
- Avoid header/footer links or navigation items.
- These will be used to reverse-engineer CSS selectors.

## OUTPUT FORMAT (JSON only)
```json
{
  "pagination": {
    "type": "datatable|infinite_scroll|click|alpha|load_more|none",
    "total_items": 0,
    "items_per_page": 10,
    "max_pages": 1,
    "next_button_hint": "selector or description"
  },
  "page_type": "A|B|C|D|E|F|Z",
  "page_type_confidence": 0.9,
  "page_type_reason": "explanation",
  "block": {
    "type": "none|captcha|login|cookie|cloudflare|rate_limit|paywall|error",
    "description": ""
  },
  "content": {
    "loaded": true,
    "loading_indicator": false,
    "infinite_scroll": false,
    "scroll_end_visible": false
  },
  "viewport": {
    "detected": "desktop|tablet|mobile",
    "recommended": "desktop|mobile"
  },
  "schema_hints": {
    "container": "CSS hint for repeating element",
    "name": "CSS hint for name",
    "link": "CSS hint for profile URL",
    "title": "CSS hint for job title"
  },
  "content_visuals": {
    "has_profile_images": true/false,
    "images_are_placeholders": true/false,
    "layout_density": "high|medium|low"
  },
  "language": "en|hi|zh|ar|etc",
  "confidence": 0.85,
  "patterns": ["list of visual observations"],
  "sample_names": ["Name 1", "Name 2", "Name 3"]
}
```"""


CSS_SELECTOR_PROMPT = """Given this screenshot, I need to click on or select a specific element.

TARGET: {target_description}

Describe the element's:
1. EXACT visual position (top-left, center, bottom-right, etc.)
2. Color and appearance
3. Text content if any
4. Surrounding elements

Then suggest 3 possible CSS selectors in order of specificity:
1. ID-based (if visible)
2. Class-based
3. Position-based fallback

Return JSON:
```json
{{
  "position": "description of where on page",
  "appearance": "color, size, shape",
  "text": "visible text",
  "context": "what's around it",
  "selectors": [
    {{"selector": "...", "confidence": 0.9}},
    {{"selector": "...", "confidence": 0.7}},
    {{"selector": "...", "confidence": 0.5}}
  ]
}}
```"""


ERROR_DIAGNOSIS_PROMPT = """This webpage scraping attempt failed. Analyze the screenshot to diagnose why.

ERROR: {error_message}
EXPECTED: {expected_content}

Analyze:
1. Is the expected content visible at all?
2. Is content hidden behind an overlay?
3. Is the page fully loaded?
4. Is there an error message visible?
5. Is the page structure different than expected?

Suggest recovery actions:
- Wait longer for content?
- Click to dismiss overlay?
- Try different viewport?
- Content doesn't exist on this page?

Return JSON:
```json
{
  "content_visible": true/false,
  "blocking_issue": "description or null",
  "page_state": "loaded|loading|error|blocked",
  "probable_cause": "explanation",
  "recovery_actions": [
    {"action": "description", "priority": 1},
    {"action": "description", "priority": 2}
  ]
}
```"""


# =============================================================================
# Vision Analyzer Class
# =============================================================================

class VisionPageAnalyzer:
    """
    Comprehensive vision-based page analyzer with 10 AI-powered features.
    
    Uses multimodal LLM (GPT-4o-mini) to understand web pages visually
    instead of relying on brittle HTML parsing rules.
    """
    
    def __init__(
        self, 
        model: str = "openai/gpt-4o-mini",
        cache_dir: str = None
    ):
        """
        Initialize the vision analyzer.
        
        Args:
            model: Vision-capable LLM model
            cache_dir: Directory for domain analysis cache
        """
        self.model = model
        
        # Setup cache
        if cache_dir is None:
            cache_dir = str(Path.home() / ".insti_scraper")
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        self.cache_path = str(Path(cache_dir) / "vision_cache.db")
        self._init_cache()
    
    def _init_cache(self):
        """Initialize SQLite cache for domain profiles."""
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS domain_profiles (
                    domain TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
    
    # =========================================================================
    # Core Methods
    # =========================================================================
    
    async def capture_screenshot(
        self, 
        url: str,
        viewport: ViewportType = ViewportType.DESKTOP,
        wait_time: float = 3.0
    ) -> Optional[str]:
        """
        Capture a screenshot of a webpage.
        
        Args:
            url: URL to capture
            viewport: Viewport type (desktop/mobile)
            wait_time: Seconds to wait for content
            
        Returns:
            Screenshot as base64 string, or None on failure
        """
        # Set viewport dimensions
        if viewport == ViewportType.MOBILE:
            viewport_width, viewport_height = 390, 844  # iPhone 14
        elif viewport == ViewportType.TABLET:
            viewport_width, viewport_height = 820, 1180  # iPad
        else:
            viewport_width, viewport_height = 1920, 1080  # Desktop
        
        browser_config = BrowserConfig(
            headless=True, 
            verbose=False,
            viewport_width=viewport_width,
            viewport_height=viewport_height
        )
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            screenshot=True,
            screenshot_wait_for=wait_time
        )
        
        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=run_config)
                
                if result.success and result.screenshot:
                    return result.screenshot
        except Exception as e:
            print(f"  ⚠️ Screenshot capture error: {e}")
        
        return None
    
    def _prepare_image(self, screenshot_data) -> Optional[str]:
        """Convert screenshot to JPEG base64 for API."""
        try:
            from PIL import Image
        except ImportError:
            print("  ⚠️ PIL not installed")
            return None
        
        # Decode if base64 string
        if isinstance(screenshot_data, str):
            img_bytes = base64.b64decode(screenshot_data)
        else:
            img_bytes = screenshot_data
        
        try:
            img = Image.open(io.BytesIO(img_bytes))
            
            # Resize for cost efficiency
            max_width = 1200
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # Convert to JPEG
            buffer = io.BytesIO()
            img.convert('RGB').save(buffer, format='JPEG', quality=65)
            return base64.b64encode(buffer.getvalue()).decode('utf-8')
        except Exception as e:
            print(f"  ⚠️ Image processing error: {e}")
            return None
    
    async def _call_vision_api(
        self, 
        image_b64: str, 
        prompt: str,
        max_tokens: int = 800
    ) -> Optional[Dict]:
        """Call vision API and parse JSON response."""
        try:
            response = completion(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                                "detail": "low"
                            }
                        }
                    ]
                }],
                temperature=0,
                max_tokens=max_tokens
            )
            
            content = response.choices[0].message.content
            
            # Extract JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                return json.loads(json_match.group())
                
        except Exception as e:
            print(f"  ⚠️ Vision API error: {e}")
        
        return None
    
    # =========================================================================
    # Feature 1 & 2: Comprehensive Analysis (Pagination + Schema)
    # =========================================================================
    
    async def analyze(self, url: str) -> VisualAnalysisResult:
        """
        Full comprehensive page analysis.
        
        Combines all features: pagination, classification, blocks, schema hints.
        """
        print(f"📸 Capturing screenshot of {url}...")
        screenshot = await self.capture_screenshot(url)
        
        if screenshot is None:
            return VisualAnalysisResult(
                block_type=BlockType.ERROR_PAGE,
                block_description="Failed to capture screenshot"
            )
        
        image_b64 = self._prepare_image(screenshot)
        if image_b64 is None:
            return VisualAnalysisResult()
        
        print(f"🔮 Analyzing with {self.model}...")
        data = await self._call_vision_api(image_b64, COMPREHENSIVE_VISION_PROMPT)
        
        if data is None:
            return VisualAnalysisResult()
        
        # Parse response into result object
        result = self._parse_comprehensive_result(data)
        
        # Auto-calculate pages if needed
        if result.total_items > 0 and result.max_pages_needed <= 1:
            result.max_pages_needed = min(
                (result.total_items + result.items_per_page - 1) // result.items_per_page,
                200  # Cap at 200 pages
            )
        
        self._print_analysis_result(result)
        return result
    
    def _parse_comprehensive_result(self, data: Dict) -> VisualAnalysisResult:
        """Parse API response into VisualAnalysisResult."""
        pagination = data.get("pagination", {})
        block = data.get("block", {})
        content = data.get("content", {})
        viewport = data.get("viewport", {})
        
        return VisualAnalysisResult(
            # Pagination
            pagination_type=pagination.get("type", "unknown"),
            total_items=int(pagination.get("total_items", 0)),
            items_per_page=int(pagination.get("items_per_page", 10)),
            max_pages_needed=int(pagination.get("max_pages", 10)),
            next_button_selector=pagination.get("next_button_hint"),
            
            # Classification
            page_type=PageType(data.get("page_type", "X")),
            page_type_confidence=float(data.get("page_type_confidence", 0.5)),
            page_type_reason=data.get("page_type_reason", ""),
            
            # Blocks
            block_type=BlockType(block.get("type", "none")),
            block_description=block.get("description", ""),
            
            # Content state
            content_loaded=content.get("loaded", True),
            has_loading_indicator=content.get("loading_indicator", False),
            has_infinite_scroll=content.get("infinite_scroll", False),
            scroll_end_detected=content.get("scroll_end_visible", False),
            
            # Viewport
            detected_viewport=ViewportType(viewport.get("detected", "desktop")),
            recommended_viewport=ViewportType(viewport.get("recommended", "desktop")),
            
            # Schema
            schema_hints=data.get("schema_hints", {}),
            
            # Meta
            language_detected=data.get("language", "en"),
            confidence=float(data.get("confidence", 0.5)),
            detected_patterns=data.get("patterns", []),
            sample_names=data.get("sample_names", [])
        )
    
    def _print_analysis_result(self, result: VisualAnalysisResult):
        """Print analysis results."""
        print(f"  ✅ Page Type: {result.page_type.value} ({result.page_type_confidence:.0%})")
        print(f"  📊 Pagination: {result.pagination_type}")
        if result.total_items > 0:
            print(f"  📈 Total: {result.total_items}, Pages: {result.max_pages_needed}")
        if result.is_blocked():
            print(f"  🚫 BLOCKED: {result.block_type.value} - {result.block_description}")
        if result.schema_hints:
            print(f"  📋 Schema hints: {list(result.schema_hints.keys())}")
    
    # =========================================================================
    # Feature 3: Pure Vision Classification
    # =========================================================================
    
    async def classify_page(self, url: str) -> Tuple[PageType, float, str]:
        """
        Classify page type using vision only.
        
        Returns:
            Tuple of (PageType, confidence, reason)
        """
        result = await self.analyze(url)
        return result.page_type, result.page_type_confidence, result.page_type_reason
    
    # =========================================================================
    # Feature 4: CAPTCHA/Block Detection
    # =========================================================================
    
    async def detect_blocks(self, url: str) -> Tuple[BlockType, str]:
        """
        Check if page access is blocked.
        
        Returns:
            Tuple of (BlockType, description)
        """
        result = await self.analyze(url)
        return result.block_type, result.block_description
    
    async def is_accessible(self, url: str) -> bool:
        """Quick check if page is accessible."""
        block_type, _ = await self.detect_blocks(url)
        return block_type == BlockType.NONE
    
    # =========================================================================
    # Feature 5: Dynamic Wait Detection
    # =========================================================================
    
    async def wait_for_stable_content(
        self, 
        url: str,
        max_wait: float = 10.0,
        check_interval: float = 1.0
    ) -> Tuple[bool, float]:
        """
        Wait until page content is stable (no loading indicators).
        
        Returns:
            Tuple of (is_stable, actual_wait_time)
        """
        import asyncio
        import time
        
        start_time = time.time()
        
        for wait_time in [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]:
            if wait_time > max_wait:
                break
            
            screenshot = await self.capture_screenshot(url, wait_time=wait_time)
            if screenshot is None:
                continue
            
            image_b64 = self._prepare_image(screenshot)
            if image_b64 is None:
                continue
            
            # Quick check for loading state
            result = await self._call_vision_api(
                image_b64,
                "Is this page still loading? Look for: spinners, skeleton loaders, 'Loading...' text, progress bars. Return JSON: {\"loading\": true/false, \"indicator\": \"description or null\"}",
                max_tokens=100
            )
            
            if result and not result.get("loading", True):
                return True, time.time() - start_time
            
            await asyncio.sleep(check_interval)
        
        return False, max_wait
    
    # =========================================================================
    # Feature 6: Infinite Scroll Depth Detection
    # =========================================================================
    
    async def detect_scroll_state(self, screenshot_data) -> Dict[str, Any]:
        """
        Detect infinite scroll state from screenshot.
        
        Returns:
            Dict with has_more, end_reached, loading_visible
        """
        image_b64 = self._prepare_image(screenshot_data)
        if image_b64 is None:
            return {"has_more": True, "end_reached": False, "loading_visible": False}
        
        result = await self._call_vision_api(
            image_b64,
            """Check this page's scroll state:
            1. Is there a loading spinner at the bottom?
            2. Is there an "End of list" or "No more results" message?
            3. Is there a "Load More" button?
            Return JSON: {"loading_visible": bool, "end_message": bool, "load_more_button": bool}""",
            max_tokens=100
        )
        
        if result:
            return {
                "has_more": not result.get("end_message", False),
                "end_reached": result.get("end_message", False),
                "loading_visible": result.get("loading_visible", False),
                "has_load_more": result.get("load_more_button", False)
            }
        
        return {"has_more": True, "end_reached": False, "loading_visible": False}
    
    # =========================================================================
    # Feature 7: Multi-Language Support (inherent in prompts)
    # =========================================================================
    
    async def detect_language(self, url: str) -> str:
        """Detect primary language of page content."""
        result = await self.analyze(url)
        return result.language_detected
    
    # =========================================================================
    # Feature 8: Error Recovery Guidance
    # =========================================================================
    
    async def diagnose_failure(
        self, 
        url: str, 
        error_message: str,
        expected_content: str = "faculty/people list"
    ) -> Dict[str, Any]:
        """
        Diagnose why scraping failed and suggest recovery.
        
        Returns:
            Dict with cause, recovery_actions, should_retry
        """
        screenshot = await self.capture_screenshot(url)
        if screenshot is None:
            return {
                "cause": "Page failed to load",
                "recovery_actions": ["Retry with longer timeout", "Check if URL is valid"],
                "should_retry": True
            }
        
        image_b64 = self._prepare_image(screenshot)
        if image_b64 is None:
            return {"cause": "Image processing failed", "recovery_actions": [], "should_retry": False}
        
        prompt = ERROR_DIAGNOSIS_PROMPT.format(
            error_message=error_message,
            expected_content=expected_content
        )
        
        result = await self._call_vision_api(image_b64, prompt)
        
        if result:
            actions = result.get("recovery_actions", [])
            return {
                "content_visible": result.get("content_visible", False),
                "cause": result.get("probable_cause", "Unknown"),
                "page_state": result.get("page_state", "unknown"),
                "recovery_actions": [a["action"] for a in sorted(actions, key=lambda x: x.get("priority", 99))],
                "should_retry": result.get("page_state") in ["loading", "blocked"]
            }
        
        return {"cause": "Analysis failed", "recovery_actions": [], "should_retry": False}
    
    # =========================================================================
    # Feature 9: Mobile/Desktop Detection
    # =========================================================================
    
    async def detect_optimal_viewport(self, url: str) -> ViewportType:
        """
        Detect the optimal viewport for scraping.
        
        Some sites have better mobile layouts for data extraction.
        """
        result = await self.analyze(url)
        return result.recommended_viewport
    
    async def analyze_with_optimal_viewport(self, url: str) -> VisualAnalysisResult:
        """
        Analyze page, automatically switching to optimal viewport.
        """
        # First pass with desktop
        result = await self.analyze(url)
        
        # If mobile recommended, re-analyze with mobile viewport
        if result.recommended_viewport == ViewportType.MOBILE:
            print("  📱 Switching to mobile viewport...")
            screenshot = await self.capture_screenshot(url, viewport=ViewportType.MOBILE)
            if screenshot:
                image_b64 = self._prepare_image(screenshot)
                if image_b64:
                    data = await self._call_vision_api(image_b64, COMPREHENSIVE_VISION_PROMPT)
                    if data:
                        result = self._parse_comprehensive_result(data)
        
        return result
    
    # =========================================================================
    # Feature 10: Domain Pre-Analysis & Caching
    # =========================================================================
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower()
    
    async def get_domain_profile(self, url: str) -> Optional[DomainProfile]:
        """
        Get or create domain profile.
        
        Caches analysis per domain to avoid repeated API calls.
        """
        domain = self._get_domain(url)
        
        # Check cache
        with sqlite3.connect(self.cache_path) as conn:
            cursor = conn.execute(
                "SELECT profile_json, created_at FROM domain_profiles WHERE domain = ?",
                (domain,)
            )
            row = cursor.fetchone()
            
            if row:
                profile_json, created_at = row
                created = datetime.fromisoformat(created_at)
                
                # Cache valid for 7 days
                if datetime.now() - created < timedelta(days=7):
                    try:
                        data = json.loads(profile_json)
                        return DomainProfile(**data)
                    except:
                        pass
        
        # Analyze domain
        print(f"🔍 Building domain profile for {domain}...")
        result = await self.analyze(url)
        
        profile = DomainProfile(
            domain=domain,
            pagination_type=result.pagination_type,
            typical_items_per_page=result.items_per_page,
            common_selectors=result.schema_hints,
            has_captcha=result.block_type == BlockType.CAPTCHA,
            preferred_viewport=result.recommended_viewport,
            language=result.language_detected,
            analyzed_at=datetime.now().isoformat(),
            sample_urls=[url]
        )
        
        # Save to cache
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO domain_profiles (domain, profile_json, created_at)
                VALUES (?, ?, ?)
            """, (domain, json.dumps(profile.__dict__), profile.analyzed_at))
            conn.commit()
        
        return profile
    
    def invalidate_domain_cache(self, url: str):
        """Invalidate cached domain profile."""
        domain = self._get_domain(url)
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute("DELETE FROM domain_profiles WHERE domain = ?", (domain,))
            conn.commit()
    
    # =========================================================================
    # Feature 1: CSS Selector Generation
    # =========================================================================
    
    async def generate_css_selector(
        self, 
        url: str, 
        target_description: str
    ) -> List[Dict[str, Any]]:
        """
        Generate CSS selectors for a described element.
        
        Args:
            url: Page URL
            target_description: What to select (e.g., "Next button", "Faculty name")
            
        Returns:
            List of {selector, confidence} dicts
        """
        screenshot = await self.capture_screenshot(url)
        if screenshot is None:
            return []
        
        image_b64 = self._prepare_image(screenshot)
        if image_b64 is None:
            return []
        
        prompt = CSS_SELECTOR_PROMPT.format(target_description=target_description)
        result = await self._call_vision_api(image_b64, prompt)
        
        if result and "selectors" in result:
            return result["selectors"]
        
        return []


# =============================================================================
# Convenience Functions
# =============================================================================

async def analyze_page_with_vision(
    url: str,
    model: str = "openai/gpt-4o-mini"
) -> VisualAnalysisResult:
    """Analyze a page with comprehensive vision analysis."""
    analyzer = VisionPageAnalyzer(model=model)
    return await analyzer.analyze(url)


async def is_page_accessible(url: str) -> bool:
    """Quick check if page is not blocked."""
    analyzer = VisionPageAnalyzer()
    return await analyzer.is_accessible(url)


async def get_optimal_scraping_config(url: str) -> Dict[str, Any]:
    """Get recommended scraping configuration for a URL."""
    analyzer = VisionPageAnalyzer()
    result = await analyzer.analyze(url)
    
    return {
        "max_pages": result.max_pages_needed,
        "items_per_page": result.items_per_page,
        "pagination_type": result.pagination_type,
        "next_selector": result.next_button_selector,
        "viewport": result.recommended_viewport.value,
        "page_type": result.page_type.value,
        "is_blocked": result.is_blocked(),
        "schema_hints": result.schema_hints,
        "language": result.language_detected
    }
