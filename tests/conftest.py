"""
Pytest configuration and shared fixtures.
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def sample_faculty_html():
    """Sample HTML with faculty listing."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Faculty Directory</title></head>
    <body>
    <h1>Department of Computer Science</h1>
    <div class="faculty-card">
        <h3><a href="/people/john-smith">Dr. John Smith</a></h3>
        <p class="position">Professor</p>
        <a href="mailto:jsmith@university.edu">jsmith@university.edu</a>
    </div>
    <div class="faculty-card">
        <h3><a href="/people/jane-doe">Dr. Jane Doe</a></h3>
        <p class="position">Associate Professor</p>
    </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_sitemap_xml():
    """Sample sitemap XML."""
    return """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://example.edu/faculty</loc></url>
        <url><loc>https://example.edu/people</loc></url>
        <url><loc>https://example.edu/about</loc></url>
    </urlset>
    """


@pytest.fixture
def mock_crawler_result():
    """Mock crawler fetch result."""
    class MockResult:
        success = True
        html = "<html><body>Test content</body></html>"
        error = None
    
    return MockResult()
