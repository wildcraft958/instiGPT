import asyncio
import os
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from insti_scraper.strategies.extraction_strategies import create_detail_strategy
from insti_scraper.core.config import settings

# Mock HTML content representing a rich faculty profile
MOCK_HTML = """
<html>
<body>
    <div class="profile-container">
        <h1>Dr. Apollo Creed</h1>
        <p class="designation">Distinguished Professor</p>
        <img src="https://univ.edu/apollo.jpg" alt="Apollo Creed">
        
        <div class="contact">
            <p>Email: <a href="mailto:apollo@univ.edu">apollo@univ.edu</a></p>
            <p>Phone: +1 (555) 123-4567</p>
            <p>Office: Room 402, Building A</p>
        </div>
        
        <div class="socials">
            <a href="https://linkedin.com/in/apollo">LinkedIn</a>
            <a href="https://twitter.com/apollo_ai">Twitter</a>
            <a href="https://scholar.google.com/citations?user=1234">Google Scholar</a>
        </div>
        
        <div class="research">
            <h2>Research Interests</h2>
            <ul>
                <li>Artificial Intelligence</li>
                <li>Deep Learning</li>
                <li>Boxing Implementations</li>
            </ul>
        </div>
        
        <div class="publications">
            <h2>Recent Publications</h2>
            <ol>
                <li>"The Eye of the Tiger: A Study in Resilience" (2024)</li>
                <li>"Rocky Road: Path Finding Algorithms" (2023)</li>
            </ol>
        </div>
    </div>
</body>
</html>
"""

async def test_extraction():
    print("🧪 Testing Detailed Extraction Strategy (Apollo-Mode)...")
    
    # Create the strategy with the new instruction
    strategy = create_detail_strategy(model_name=settings.MODEL_NAME)
    
    # We use raw HTML input simulation (crawl4ai supports this via simulated response or just feeding html if supported, 
    # but simplest is to just run the strategy's extraction logic if accessible, 
    # OR simpler: Spin up a local server? No, crawl4ai accepts 'data:text/html' uri or we can mock request)
    
    # Use 'raw:' scheme supported by crawl4ai for direct HTML content
    # Note: raw: scheme assumes the content is the URL string itself after 'raw:'
    # Ideally we should just pass the HTML content, but let's try the library's specific way
    
    # Actually, recent crawl4ai versions support 'raw:' prefix followed by HTML
    data_uri = f"raw:{MOCK_HTML}"
    
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url=data_uri,
            config=CrawlerRunConfig(
                extraction_strategy=strategy,
                cache_mode="BYPASS"
            )
        )
        
        if result.success:
            data = result.extracted_content
            import json
            parsed = json.loads(data)
            # data could be list or dict depending on strategy config. Schema extraction usually returns list of items found.
            if isinstance(parsed, list):
                parsed = parsed[0]
                
            print("\n✅ Extraction Success!")
            print(json.dumps(parsed, indent=2))
            
            # Assertions
            assert parsed.get('name') == "Dr. Apollo Creed"
            assert "Professor" in parsed.get('designation', "")
            assert "+1 (555) 123-4567" in parsed.get('phone', "")
            assert "Room 402" in parsed.get('office_address', "")
            assert parsed.get('social_links', {}).get('linkedin') == "https://linkedin.com/in/apollo"
            
            print("\n🎉 Validation Passed: All Apollo fields extracted correctly.")
        else:
            print(f"❌ Extraction failed: {result.error_message}")

if __name__ == "__main__":
    asyncio.run(test_extraction())
