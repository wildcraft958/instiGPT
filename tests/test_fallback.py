import asyncio
import os
import sys
# Add parent dir to path so we can import insti_scraper
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch, AsyncMock
from insti_scraper.services.extraction_service import ExtractionService
from insti_scraper.core.schema_cache import get_schema_cache, SelectorSchema


async def test_extraction_with_sample_html():
    """
    Test extraction service with sample HTML.
    This validates that the LLM-based extraction works as a fallback.
    """
    print("🚀 Testing ExtractionService fallback extraction...")
    
    service = ExtractionService()
    
    # Sample HTML with faculty-like content
    sample_html = """
    <html>
    <head><title>Faculty - Computer Science</title></head>
    <body>
        <h1>Computer Science Faculty</h1>
        <div class="faculty-card">
            <h3>Dr. Jane Smith</h3>
            <p class="title">Professor</p>
            <a href="mailto:jane@example.edu">jane@example.edu</a>
        </div>
        <div class="faculty-card">
            <h3>Dr. John Doe</h3>
            <p class="title">Associate Professor</p>
            <a href="mailto:john@example.edu">john@example.edu</a>
        </div>
    </body>
    </html>
    """
    
    try:
        # Test extraction - this will use LLM fallback
        professors, dept_name = await service.extract_with_fallback(
            url="https://example.edu/faculty/",
            html_content=sample_html
        )
        
        print(f"✅ Extracted {len(professors)} professors from '{dept_name}'")
        for p in professors:
            print(f"   - {p.name} ({p.title})")
        
        if len(professors) >= 1:
            print("✅ Test PASSED: Extraction service working!")
        else:
            print("⚠️ Test WARNING: No professors extracted")
            
    except Exception as e:
        print(f"❌ Test FAILED: {e}")
        raise


if __name__ == "__main__":
    print("=" * 60)
    print("INSTI-SCRAPER: Fallback Extraction Test")
    print("=" * 60)
    asyncio.run(test_extraction_with_sample_html())
