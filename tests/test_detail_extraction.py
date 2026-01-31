"""
Test detailed extraction with sample HTML.
Tests the ExtractionService's ability to extract rich faculty profiles.
"""
import asyncio
import os
import sys

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from insti_scraper.services.extraction_service import ExtractionService

# Mock HTML content representing a rich faculty profile page
MOCK_HTML = """
<html>
<head><title>Faculty Directory - Computer Science</title></head>
<body>
    <h1>Computer Science Department Faculty</h1>
    
    <div class="profile-container">
        <h2>Dr. Apollo Creed</h2>
        <p class="designation">Distinguished Professor</p>
        <img src="https://univ.edu/apollo.jpg" alt="Apollo Creed">
        
        <div class="contact">
            <p>Email: <a href="mailto:apollo@univ.edu">apollo@univ.edu</a></p>
            <p>Phone: +1 (555) 123-4567</p>
            <p>Office: Room 402, Building A</p>
        </div>
        
        <div class="research">
            <h3>Research Interests</h3>
            <ul>
                <li>Artificial Intelligence</li>
                <li>Deep Learning</li>
                <li>Neural Networks</li>
            </ul>
        </div>
        
        <div class="publications">
            <h3>Recent Publications</h3>
            <ol>
                <li>"The Eye of the Tiger: A Study in Resilience" (2024)</li>
                <li>"Rocky Road: Path Finding Algorithms" (2023)</li>
            </ol>
        </div>
    </div>
    
    <div class="profile-container">
        <h2>Dr. Rocky Balboa</h2>
        <p class="designation">Associate Professor</p>
        <a href="mailto:rocky@univ.edu">rocky@univ.edu</a>
        <div class="research">
            <ul>
                <li>Machine Learning</li>
                <li>Computer Vision</li>
            </ul>
        </div>
    </div>
</body>
</html>
"""


async def test_detail_extraction():
    """Test detailed extraction from faculty profile HTML."""
    print("🧪 Testing Detailed Extraction with ExtractionService...")
    print("=" * 60)
    
    service = ExtractionService()
    
    try:
        professors, dept_name = await service.extract_with_fallback(
            url="https://example.edu/cs/faculty/",
            html_content=MOCK_HTML
        )
        
        print(f"\n✅ Extracted {len(professors)} professors from '{dept_name}'")
        print("-" * 40)
        
        for i, prof in enumerate(professors, 1):
            print(f"\nProfessor {i}:")
            print(f"  Name: {prof.name}")
            print(f"  Title: {prof.title}")
            print(f"  Email: {prof.email}")
            if prof.research_interests:
                print(f"  Research: {', '.join(prof.research_interests[:3])}")
        
        # Basic assertions
        if len(professors) >= 1:
            print("\n✅ Test PASSED: At least 1 professor extracted")
            
            # Check if we got Apollo Creed
            names = [p.name for p in professors]
            if any("Apollo" in name or "Creed" in name for name in names):
                print("✅ Found Dr. Apollo Creed in results")
            else:
                print("⚠️ Warning: Dr. Apollo Creed not found by name")
        else:
            print("\n❌ Test FAILED: No professors extracted")
            
    except Exception as e:
        print(f"\n❌ Test FAILED with error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(test_detail_extraction())
