"""
Vision-based page analysis using multimodal AI.

Uses Gemini or GPT-4 Vision to understand complex page layouts
by analyzing screenshots when traditional parsing fails.
"""

import base64
import logging
from typing import Optional, Dict, List
from io import BytesIO

from PIL import Image

from insti_scraper.config import settings
from insti_scraper.models import Professor, ExtractionResult

logger = logging.getLogger(__name__)


class VisionAnalyzer:
    """
    Analyzes webpage screenshots using multimodal AI vision models.
    
    Use cases:
    - Complex JavaScript-heavy pages with dynamic content
    - Pages with unusual layouts that CSS selectors can't handle
    - Visual directory structures (image grids, cards)
    - Fallback when text-based extraction fails
    """
    
    def __init__(self, model: str = None):
        """
        Initialize vision analyzer.
        
        Args:
            model: Model to use. Supports:
                - "gpt-4-vision-preview" (OpenAI)
                - "gpt-4o" (OpenAI, has vision)
                - "gemini-1.5-pro-vision" (Google)
        """
        self.model = model or self._detect_best_model()
    
    def _detect_best_model(self) -> str:
        """Auto-detect best available vision model."""
        import os
        
        if os.getenv("OPENAI_API_KEY"):
            return "gpt-4o"  # GPT-4o has native vision support
        elif os.getenv("GOOGLE_API_KEY"):
            return "gemini-1.5-pro-vision"
        else:
            logger.warning("No vision model API keys found. Vision analysis will fail.")
            return "gpt-4o"
    
    async def analyze_faculty_page(
        self,
        screenshot_data: bytes,
        url: str,
        format: str = "png"
    ) -> ExtractionResult:
        """
        Analyze a faculty page screenshot to extract professor information.
        
        Args:
            screenshot_data: Raw screenshot bytes
            url: URL of the page (for context)
            format: Image format (png, jpg, webp)
        
        Returns:
            ExtractionResult with extracted professors
        """
        logger.info(f"🔍 Analyzing screenshot with vision AI: {url}")
        
        try:
            # Encode image
            base64_image = base64.b64encode(screenshot_data).decode('utf-8')
            
            # Call appropriate vision model
            if "gemini" in self.model.lower():
                result = await self._analyze_with_gemini(base64_image, url)
            else:
                result = await self._analyze_with_openai(base64_image, url)
            
            logger.info(f"   ✅ Vision extracted {len(result.professors)} professors")
            return result
            
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            return ExtractionResult(professors=[], method="vision-failed")
    
    async def _analyze_with_openai(
        self,
        base64_image: str,
        url: str
    ) -> ExtractionResult:
        """Analyze with OpenAI GPT-4 Vision."""
        import litellm
        from ..config import cost_tracker
        
        prompt = """Analyze this faculty directory webpage screenshot.

Extract ALL visible professors/faculty members. For each person, identify:
- name (required)
- title/position (Professor, Associate Professor, etc.)
- email (if visible)
- profile_url (if there's a clickable link - look for "View Profile", "More Info" buttons)

Return a JSON array:
[
    {
        "name": "Dr. John Smith",
        "title": "Professor",
        "email": "jsmith@university.edu",
        "profile_url": null
    },
    ...
]

IMPORTANT:
- Extract ALL visible faculty members on this page
- If email/title is not visible, use null
- For profile_url, only include if there's an obvious link/button
- Return ONLY valid JSON, no markdown
"""
        
        try:
            response = await litellm.acompletion(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                temperature=0.1,
            )
            
            # Track costs
            if hasattr(response, 'usage') and response.usage:
                cost_tracker.track_usage(
                    self.model,
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens
                )
            
            # Parse response
            import json
            import re
            
            content = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            if content.startswith("```"):
                content = re.sub(r'^```\w*\n?', '', content)
                content = re.sub(r'\n?```$', '', content)
            
            data = json.loads(content)
            
            professors = []
            for item in data:
                if isinstance(item, dict) and item.get('name'):
                    prof = Professor(
                        name=item.get('name'),
                        title=item.get('title'),
                        email=item.get('email'),
                        profile_url=item.get('profile_url')
                    )
                    professors.append(prof)
            
            return ExtractionResult(
                professors=professors,
                confidence=0.85,
                method="vision-openai"
            )
            
        except Exception as e:
            logger.error(f"OpenAI vision error: {e}")
            return ExtractionResult(professors=[], method="vision-openai-failed")
    
    async def _analyze_with_gemini(
        self,
        base64_image: str,
        url: str
    ) -> ExtractionResult:
        """Analyze with Google Gemini Vision."""
        try:
            import google.generativeai as genai
            import os
            import json
            
            genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
            model = genai.GenerativeModel('gemini-1.5-pro-vision')
            
            # Decode base64 to PIL Image
            image_data = base64.b64decode(base64_image)
            image = Image.open(BytesIO(image_data))
            
            prompt = """Analyze this faculty directory webpage screenshot and extract all visible faculty members.

For each person, provide:
- name (required)
- title (Professor, Associate Professor, etc.)
- email (if visible)

Return as JSON array:
[{"name": "...", "title": "...", "email": "..."}]

Extract ALL faculty visible on this page. Return ONLY valid JSON."""
            
            response = model.generate_content([prompt, image])
            
            # Parse JSON from response
            data = json.loads(response.text)
            
            professors = []
            for item in data:
                if item.get('name'):
                    professors.append(Professor(
                        name=item['name'],
                        title=item.get('title'),
                        email=item.get('email')
                    ))
            
            return ExtractionResult(
                professors=professors,
                confidence=0.85,
                method="vision-gemini"
            )
            
        except ImportError:
            logger.error("google-generativeai not installed. Run: pip install google-generativeai")
            return ExtractionResult(professors=[], method="vision-gemini-missing")
        except Exception as e:
            logger.error(f"Gemini vision error: {e}")
            return ExtractionResult(professors=[], method="vision-gemini-failed")
    
    def classify_page_type(
        self,
        screenshot_data: bytes
    ) -> str:
        """
        Classify page type from screenshot.
        
        Returns: 'directory', 'profile', 'search', 'department_list', 'unknown'
        """
        # This could be implemented with a simpler vision prompt
        # For now, return 'unknown' as a placeholder
        return 'unknown'


async def analyze_page_with_vision(
    screenshot_data: bytes,
    url: str,
    model: str = None
) -> ExtractionResult:
    """
    Convenience function for vision-based extraction.
    
    Args:
        screenshot_data: Screenshot bytes
        url: Page URL
        model: Vision model to use (optional)
    
    Returns:
        ExtractionResult with extracted professors
    """
    analyzer = VisionAnalyzer(model=model)
    return await analyzer.analyze_faculty_page(screenshot_data, url)
