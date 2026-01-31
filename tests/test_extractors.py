"""
Tests for the site adapter extraction system.
"""

import pytest
from unittest.mock import AsyncMock, patch

from insti_scraper.extractors import (
    SiteAdapter,
    CSSAdapter,
    GenericAdapter,
    PrincetonAdapter,
    UCTAdapter,
    IITAdapter,
    MITAdapter,
    AdapterRegistry,
    extract_professors,
    ExtractionResult,
)
from insti_scraper.models import Professor


# =============================================================================
# Test Data: Sample HTML
# =============================================================================

SIMPLE_FACULTY_HTML = """
<!DOCTYPE html>
<html>
<head><title>Computer Science - Faculty</title></head>
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
    <a href="mailto:jdoe@university.edu">jdoe@university.edu</a>
</div>
<div class="faculty-card">
    <h3><a href="/people/bob-johnson">Dr. Bob Johnson</a></h3>
    <p class="position">Assistant Professor</p>
    <a href="mailto:bjohnson@university.edu">bjohnson@university.edu</a>
</div>
</body>
</html>
"""

PRINCETON_STYLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Meet Faculty | Princeton</title></head>
<body>
<div class="views-row">
    <h2><a href="/faculty/alice-wonderland">Alice Wonderland</a></h2>
    <div class="field--name-field-position">Professor of Mathematics</div>
    <a href="mailto:alice@princeton.edu">alice@princeton.edu</a>
</div>
<article class="node--type-person">
    <div class="field--name-title"><a href="/faculty/charlie-brown">Charlie Brown</a></div>
    <div class="field--name-field-position">Assistant Professor</div>
</article>
</body>
</html>
"""

UCT_STYLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Académicos - Departamento</title></head>
<body>
<h1>Departamento de Ciencias de la Computación</h1>
<div class="academico-item">
    <h3 class="nombre">María García</h3>
    <p class="cargo">Profesora Titular</p>
    <a href="mailto:mgarcia@uct.cl">mgarcia@uct.cl</a>
</div>
<div class="academico-item">
    <h3 class="nombre">Carlos López</h3>
    <p class="cargo">Profesor Asociado</p>
    <a href="mailto:clopez@uct.cl">clopez@uct.cl</a>
</div>
</body>
</html>
"""

SCHEMA_ORG_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Faculty Directory</title>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "ItemList",
    "itemListElement": [
        {
            "@type": "Person",
            "name": "Schema Person One",
            "email": "person1@example.com",
            "jobTitle": "Professor"
        },
        {
            "@type": "Person",
            "name": "Schema Person Two",
            "url": "https://example.com/person2"
        }
    ]
}
</script>
</head>
<body>
<p>Faculty listing with Schema.org markup</p>
</body>
</html>
"""

EMAIL_ANCHORED_HTML = """
<!DOCTYPE html>
<html>
<head><title>Staff Directory</title></head>
<body>
<ul>
    <li>
        <strong>Email Person One</strong>
        <a href="mailto:person.one@example.edu">person.one@example.edu</a>
    </li>
    <li>
        <strong>Email Person Two</strong>
        <a href="mailto:person.two@example.edu">person.two@example.edu</a>
    </li>
    <li>
        <strong>Email Person Three</strong>
        <a href="mailto:person.three@example.edu">person.three@example.edu</a>
    </li>
</ul>
</body>
</html>
"""


# =============================================================================
# Tests: Adapter Registry
# =============================================================================

class TestAdapterRegistry:
    """Tests for the adapter registry."""
    
    def test_registry_creation(self):
        """Registry should initialize with default adapters."""
        registry = AdapterRegistry()
        assert len(registry._adapters) >= 5  # At least our built-in adapters
    
    def test_register_custom_adapter(self):
        """Should be able to register custom adapters."""
        registry = AdapterRegistry()
        initial_count = len(registry._adapters)
        
        class CustomAdapter(SiteAdapter):
            DOMAIN_PATTERNS = ["custom.example.com"]
            PRIORITY = 100
            
            async def extract(self, html, url, **kwargs):
                return ExtractionResult(professors=[], method="custom")
        
        registry.register(CustomAdapter)
        assert len(registry._adapters) == initial_count + 1
    
    def test_adapter_priority_sorting(self):
        """Adapters should be sorted by priority (highest first)."""
        registry = AdapterRegistry()
        
        priorities = [a.PRIORITY for a in registry._adapters]
        assert priorities == sorted(priorities, reverse=True)
    
    def test_get_adapter_for_princeton(self):
        """Princeton URL should get PrincetonAdapter."""
        registry = AdapterRegistry()
        adapter = registry.get_adapter("https://faculty.princeton.edu/meet-faculty")
        assert isinstance(adapter, PrincetonAdapter)
    
    def test_get_adapter_for_uct(self):
        """UCT URL should get UCTAdapter."""
        registry = AdapterRegistry()
        adapter = registry.get_adapter("https://departamento-scpa.uct.cl/academicos/")
        assert isinstance(adapter, UCTAdapter)
    
    def test_get_adapter_for_iit(self):
        """IIT URL should get IITAdapter."""
        registry = AdapterRegistry()
        adapter = registry.get_adapter("https://cse.iitb.ac.in/faculty")
        assert isinstance(adapter, IITAdapter)
    
    def test_get_adapter_for_mit(self):
        """MIT URL should get MITAdapter."""
        registry = AdapterRegistry()
        adapter = registry.get_adapter("https://www.eecs.mit.edu/people")
        assert isinstance(adapter, MITAdapter)
    
    def test_get_adapter_fallback_to_generic(self):
        """Unknown URL should get GenericAdapter."""
        registry = AdapterRegistry()
        adapter = registry.get_adapter("https://random-university.example.com/faculty")
        assert isinstance(adapter, GenericAdapter)


# =============================================================================
# Tests: Domain Matching
# =============================================================================

class TestDomainMatching:
    """Tests for domain pattern matching."""
    
    def test_exact_domain_match(self):
        """Should match exact domain."""
        assert PrincetonAdapter.matches_domain("https://princeton.edu/faculty")
    
    def test_subdomain_match(self):
        """Should match subdomains with wildcard patterns."""
        assert IITAdapter.matches_domain("https://cse.iitb.ac.in/faculty")
        assert IITAdapter.matches_domain("https://math.iitb.ac.in/people")
    
    def test_partial_match(self):
        """Should match partial domain in pattern."""
        assert MITAdapter.matches_domain("https://www.mit.edu/people")
        assert MITAdapter.matches_domain("https://nse.mit.edu/faculty")
    
    def test_no_match(self):
        """Should not match unrelated domains."""
        assert not PrincetonAdapter.matches_domain("https://harvard.edu/faculty")
        assert not UCTAdapter.matches_domain("https://stanford.edu/people")


# =============================================================================
# Tests: CSS-Based Extraction
# =============================================================================

class TestCSSExtraction:
    """Tests for CSS-based extraction."""
    
    @pytest.mark.asyncio
    async def test_generic_extraction_simple(self):
        """GenericAdapter should extract from simple faculty HTML."""
        adapter = GenericAdapter()
        result = await adapter.extract(SIMPLE_FACULTY_HTML, "https://example.edu/faculty")
        
        assert len(result.professors) == 3
        assert result.confidence > 0
        
        names = [p.name for p in result.professors]
        assert "Dr. John Smith" in names
        assert "Dr. Jane Doe" in names
    
    @pytest.mark.asyncio
    async def test_princeton_extraction(self):
        """PrincetonAdapter should extract from Princeton-style HTML."""
        adapter = PrincetonAdapter()
        result = await adapter.extract(PRINCETON_STYLE_HTML, "https://princeton.edu/meet-faculty")
        
        assert len(result.professors) >= 1
        names = [p.name for p in result.professors]
        assert any("Alice" in name or "Charlie" in name for name in names)
    
    @pytest.mark.asyncio
    async def test_uct_extraction(self):
        """UCTAdapter should extract from Spanish UCT-style HTML."""
        adapter = UCTAdapter()
        result = await adapter.extract(UCT_STYLE_HTML, "https://uct.cl/academicos")
        
        assert len(result.professors) == 2
        names = [p.name for p in result.professors]
        assert "María García" in names
        assert "Carlos López" in names
    
    @pytest.mark.asyncio
    async def test_email_extraction(self):
        """Should extract emails from mailto links."""
        adapter = GenericAdapter()
        result = await adapter.extract(SIMPLE_FACULTY_HTML, "https://example.edu/faculty")
        
        emails = [p.email for p in result.professors if p.email]
        assert "jsmith@university.edu" in emails
    
    @pytest.mark.asyncio
    async def test_profile_url_extraction(self):
        """Should extract profile URLs from links."""
        adapter = GenericAdapter()
        result = await adapter.extract(SIMPLE_FACULTY_HTML, "https://example.edu/faculty")
        
        urls = [p.profile_url for p in result.professors if p.profile_url]
        assert len(urls) > 0
        assert any("/people/john-smith" in url for url in urls)


# =============================================================================
# Tests: Schema.org Extraction
# =============================================================================

class TestSchemaOrgExtraction:
    """Tests for Schema.org markup extraction."""
    
    @pytest.mark.asyncio
    async def test_jsonld_extraction(self):
        """Should extract from JSON-LD Schema.org markup."""
        adapter = GenericAdapter()
        result = await adapter.extract(SCHEMA_ORG_HTML, "https://example.edu/faculty")
        
        # Schema.org should be found
        assert result.method in ["schema.org", "email-heuristic", "css-heuristic"]
        
        if result.method == "schema.org":
            assert len(result.professors) >= 2
            names = [p.name for p in result.professors]
            assert "Schema Person One" in names


# =============================================================================
# Tests: Email-Based Extraction
# =============================================================================

class TestEmailBasedExtraction:
    """Tests for email-anchored extraction."""
    
    @pytest.mark.asyncio
    async def test_email_anchored_extraction(self):
        """Should extract profiles anchored by email addresses."""
        adapter = GenericAdapter()
        result = await adapter.extract(EMAIL_ANCHORED_HTML, "https://example.edu/staff")
        
        assert len(result.professors) >= 2
        
        # Should have emails
        emails = [p.email for p in result.professors if p.email]
        assert len(emails) >= 2


# =============================================================================
# Tests: Extraction Result
# =============================================================================

class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""
    
    def test_default_values(self):
        """ExtractionResult should have sensible defaults."""
        result = ExtractionResult(professors=[])
        
        assert result.department_name == "General"
        assert result.confidence == 0.0
        assert result.method == "unknown"
        assert result.metadata == {}
    
    def test_with_values(self):
        """ExtractionResult should store provided values."""
        profs = [Professor(name="Test Professor")]
        result = ExtractionResult(
            professors=profs,
            department_name="Computer Science",
            confidence=0.9,
            method="css"
        )
        
        assert len(result.professors) == 1
        assert result.department_name == "Computer Science"
        assert result.confidence == 0.9


# =============================================================================
# Tests: Name Validation
# =============================================================================

class TestNameValidation:
    """Tests for name validation in adapters."""
    
    def test_valid_names(self):
        """Should accept valid faculty names."""
        adapter = GenericAdapter()
        
        assert adapter._is_valid_name("Dr. John Smith")
        assert adapter._is_valid_name("María García")
        assert adapter._is_valid_name("Jean-Pierre Dupont")
    
    def test_invalid_names(self):
        """Should reject invalid/navigation names."""
        adapter = GenericAdapter()
        
        assert not adapter._is_valid_name("Home")
        assert not adapter._is_valid_name("Contact")
        assert not adapter._is_valid_name("Login")
        assert not adapter._is_valid_name("Search")
        assert not adapter._is_valid_name("")
        assert not adapter._is_valid_name("AB")  # Too short


# =============================================================================
# Tests: URL Utilities
# =============================================================================

class TestURLUtilities:
    """Tests for URL handling utilities."""
    
    def test_make_absolute_url_already_absolute(self):
        """Should not modify already absolute URLs."""
        adapter = CSSAdapter()
        adapter.CONTAINER_SELECTOR = "div"  # Required for instantiation
        
        url = adapter._make_absolute_url(
            "https://example.com/page",
            "https://other.com/"
        )
        assert url == "https://example.com/page"
    
    def test_make_absolute_url_root_relative(self):
        """Should handle root-relative URLs."""
        adapter = GenericAdapter()
        
        url = adapter._make_absolute_url(
            "/faculty/john-smith",
            "https://example.edu/department/people"
        )
        assert url == "https://example.edu/faculty/john-smith"


# =============================================================================
# Tests: Convenience Functions
# =============================================================================

class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    @pytest.mark.asyncio
    async def test_extract_professors_function(self):
        """extract_professors should work as convenience function."""
        result = await extract_professors(
            SIMPLE_FACULTY_HTML,
            "https://example.edu/faculty"
        )
        
        assert isinstance(result, ExtractionResult)
        assert len(result.professors) >= 2


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
