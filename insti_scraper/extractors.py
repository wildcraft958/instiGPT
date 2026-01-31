"""
Faculty data extraction from HTML.

Provides site adapters for different university websites and
LLM-based fallback extraction.
"""

import re
import json
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Type
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

from .models import Professor, ExtractionResult

logger = logging.getLogger(__name__)


# =============================================================================
# Base Adapter
# =============================================================================

class SiteAdapter(ABC):
    """Base class for site-specific extraction."""
    
    DOMAIN_PATTERNS: List[str] = []
    PRIORITY: int = 0
    
    @classmethod
    def matches_domain(cls, url: str) -> bool:
        """Check if adapter handles this URL."""
        domain = urlparse(url).netloc.lower()
        for pattern in cls.DOMAIN_PATTERNS:
            if "*" in pattern:
                regex = pattern.replace(".", r"\.").replace("*", ".*")
                if re.match(regex, domain):
                    return True
            elif pattern in domain:
                return True
        return False
    
    @abstractmethod
    async def extract(self, html: str, url: str, **kwargs) -> ExtractionResult:
        """Extract faculty data from HTML."""
        pass
    
    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        return re.sub(r'\s+', ' ', text).strip()
    
    def _extract_email(self, text: str) -> Optional[str]:
        match = re.search(r'[\w.+-]+@[\w.-]+\.\w+', text)
        return match.group(0) if match else None
    
    def _is_valid_name(self, name: str) -> bool:
        if not name or len(name) < 3:
            return False
        
        skip = ['home', 'about', 'contact', 'login', 'search', 'menu', 'read more', 'view']
        if name.lower() in skip:
            return False
        
        return bool(re.search(r'[a-zA-Z]', name))
    
    def _make_absolute_url(self, href: str, base_url: str) -> str:
        if not href or href.startswith(('http://', 'https://')):
            return href or ""
        return urljoin(base_url, href)


# =============================================================================
# CSS-Based Adapter (for sites with consistent HTML structure)
# =============================================================================

class CSSAdapter(SiteAdapter):
    """Base for CSS selector-based extraction."""
    
    CONTAINER_SELECTOR: str = ""
    NAME_SELECTOR: str = ""
    TITLE_SELECTOR: str = ""
    EMAIL_SELECTOR: str = ""
    LINK_SELECTOR: str = ""
    
    async def extract(self, html: str, url: str, **kwargs) -> ExtractionResult:
        soup = BeautifulSoup(html, 'html.parser')
        department = self._get_department(soup)
        
        containers = soup.select(self.CONTAINER_SELECTOR)
        if not containers:
            return ExtractionResult(professors=[], department_name=department)
        
        professors = []
        for container in containers:
            prof = self._extract_from_container(container, url)
            if prof and self._is_valid_name(prof.name):
                professors.append(prof)
        
        return ExtractionResult(
            professors=professors,
            department_name=department,
            confidence=0.8 if professors else 0.0,
            method="css"
        )
    
    def _extract_from_container(self, container, base_url: str) -> Optional[Professor]:
        # Name
        name = ""
        if self.NAME_SELECTOR:
            elem = container.select_one(self.NAME_SELECTOR)
            if elem:
                name = self._clean_text(elem.get_text())
        
        if not name:
            for tag in ['h2', 'h3', 'h4', '.name', 'a']:
                elem = container.select_one(tag)
                if elem:
                    name = self._clean_text(elem.get_text())
                    if self._is_valid_name(name):
                        break
        
        if not name:
            return None
        
        # Title
        title = None
        if self.TITLE_SELECTOR:
            elem = container.select_one(self.TITLE_SELECTOR)
            if elem:
                title = self._clean_text(elem.get_text())
        
        # Email
        email = None
        if self.EMAIL_SELECTOR:
            elem = container.select_one(self.EMAIL_SELECTOR)
            if elem:
                email = elem.get('href', '').replace('mailto:', '') or self._extract_email(elem.get_text())
        if not email:
            email = self._extract_email(container.get_text())
        
        # Profile URL
        profile_url = None
        if self.LINK_SELECTOR:
            elem = container.select_one(self.LINK_SELECTOR)
            if elem and elem.get('href'):
                href = elem['href']
                if not href.startswith(('javascript:', '#', 'mailto:')):
                    profile_url = self._make_absolute_url(href, base_url)
        
        return Professor(name=name, title=title, email=email, profile_url=profile_url)
    
    def _get_department(self, soup) -> str:
        for sel in ['h1', '.page-title', '.department-name', 'title']:
            elem = soup.select_one(sel)
            if elem:
                text = self._clean_text(elem.get_text())
                if any(kw in text.lower() for kw in ['department', 'school', 'faculty']):
                    return text[:100]
        return "General"


# =============================================================================
# Site-Specific Adapters
# =============================================================================

class PrincetonAdapter(CSSAdapter):
    """Princeton University."""
    DOMAIN_PATTERNS = ["princeton.edu", "*.princeton.edu"]
    PRIORITY = 10
    CONTAINER_SELECTOR = ".views-row, .faculty-card, article.node--type-person"
    NAME_SELECTOR = "h2 a, h3 a, .field--name-title a"
    TITLE_SELECTOR = ".field--name-field-position, .position"
    EMAIL_SELECTOR = "a[href^='mailto:']"
    LINK_SELECTOR = "h2 a, h3 a"


class UCTAdapter(CSSAdapter):
    """Universidad Católica de Temuco (Chile)."""
    DOMAIN_PATTERNS = ["uct.cl", "*.uct.cl"]
    PRIORITY = 10
    CONTAINER_SELECTOR = ".academico-item, .profesor-card, .docente, article.academico"
    NAME_SELECTOR = "h2, h3, .nombre"
    TITLE_SELECTOR = ".cargo, .titulo-academico"
    EMAIL_SELECTOR = "a[href^='mailto:'], .correo"
    LINK_SELECTOR = "a.ver-mas, h2 a"


class IITAdapter(CSSAdapter):
    """Indian Institutes of Technology."""
    DOMAIN_PATTERNS = ["*.iitb.ac.in", "*.iitkgp.ac.in", "*.iitd.ac.in", "*.iitm.ac.in", "*.iitk.ac.in"]
    PRIORITY = 10
    CONTAINER_SELECTOR = ".faculty-card, .people-card, tr.faculty-row"
    NAME_SELECTOR = ".faculty-name, .name, td:first-child a"
    TITLE_SELECTOR = ".designation, .position"
    EMAIL_SELECTOR = "a[href^='mailto:']"
    LINK_SELECTOR = ".faculty-name a, td:first-child a"


class MITAdapter(CSSAdapter):
    """MIT."""
    DOMAIN_PATTERNS = ["mit.edu", "*.mit.edu"]
    PRIORITY = 10
    CONTAINER_SELECTOR = ".person-card, .directory-listing article"
    NAME_SELECTOR = "h3 a, h2 a, .person-name"
    TITLE_SELECTOR = ".person-title, .role"
    EMAIL_SELECTOR = "a[href^='mailto:']"
    LINK_SELECTOR = "h3 a, h2 a"


# =============================================================================
# Generic Adapter (Heuristic Fallback)
# =============================================================================

class GenericAdapter(SiteAdapter):
    """
    Generic fallback using heuristics.
    
    Tries: Schema.org → CSS patterns → Email anchoring
    """
    
    DOMAIN_PATTERNS = ["*"]
    PRIORITY = -1
    
    SELECTOR_PATTERNS = [
        (".faculty-card, .people-card, .staff-card", "h3, h4, .name"),
        (".faculty-list li, .people-list li", "a, .name"),
        ("table.faculty tr, table.people tr", "td:first-child"),
        (".faculty-grid > div", "h3, h4, .name"),
        ("article.person", "h2, h3"),
        (".views-row", ".views-field-title, h3"),
        ("[class*='faculty'] [class*='card']", "[class*='name'], h3"),
    ]
    
    async def extract(self, html: str, url: str, **kwargs) -> ExtractionResult:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Try Schema.org
        result = self._try_schema_org(soup)
        if result.professors:
            return result
        
        # Try CSS patterns
        for container_sel, name_sel in self.SELECTOR_PATTERNS:
            professors = self._try_selectors(soup, container_sel, name_sel, url)
            if len(professors) >= 3:
                return ExtractionResult(
                    professors=professors,
                    department_name=self._guess_department(soup),
                    confidence=0.6,
                    method="css-heuristic"
                )
        
        # Try email anchoring
        email_based = self._extract_by_emails(soup, url)
        if email_based:
            return ExtractionResult(
                professors=email_based,
                department_name=self._guess_department(soup),
                confidence=0.4,
                method="email-heuristic"
            )
        
        return ExtractionResult(professors=[], method="generic-failed")
    
    def _try_schema_org(self, soup) -> ExtractionResult:
        """Extract from Schema.org markup."""
        professors = []
        
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                
                if isinstance(data, dict):
                    if '@graph' in data:
                        items = data['@graph']
                    elif 'itemListElement' in data:
                        items = data['itemListElement']
                
                for item in items:
                    if item.get('@type') in ['Person', 'Faculty', 'Professor']:
                        prof = Professor(
                            name=item.get('name', ''),
                            email=item.get('email'),
                            profile_url=item.get('url'),
                            title=item.get('jobTitle'),
                        )
                        if self._is_valid_name(prof.name):
                            professors.append(prof)
            except:
                continue
        
        return ExtractionResult(
            professors=professors,
            confidence=0.9 if professors else 0.0,
            method="schema.org"
        )
    
    def _try_selectors(self, soup, container_sel: str, name_sel: str, base_url: str) -> List[Professor]:
        professors = []
        
        for container in soup.select(container_sel):
            name_elem = container.select_one(name_sel)
            if not name_elem:
                continue
            
            name = self._clean_text(name_elem.get_text())
            if not self._is_valid_name(name):
                continue
            
            email = self._extract_email(container.get_text())
            
            profile_url = None
            link = name_elem if name_elem.name == 'a' else name_elem.find('a')
            if link and link.get('href'):
                href = link['href']
                if not href.startswith(('javascript:', '#', 'mailto:')):
                    profile_url = self._make_absolute_url(href, base_url)
            
            professors.append(Professor(name=name, email=email, profile_url=profile_url))
        
        return professors
    
    def _extract_by_emails(self, soup, base_url: str) -> List[Professor]:
        """Extract using email as anchor."""
        professors = []
        seen = set()
        
        for mailto in soup.select('a[href^="mailto:"]'):
            email = mailto['href'].replace('mailto:', '').split('?')[0]
            if email in seen:
                continue
            seen.add(email)
            
            parent = mailto.find_parent(['div', 'li', 'tr', 'article']) or mailto.parent
            
            name = None
            for tag in ['h2', 'h3', 'h4', 'strong', 'b']:
                elem = parent.select_one(tag) if hasattr(parent, 'select_one') else None
                if elem:
                    name = self._clean_text(elem.get_text())
                    if self._is_valid_name(name):
                        break
            
            if not name:
                # Derive from email
                local = email.split('@')[0]
                parts = re.split(r'[._-]', local)
                name = ' '.join(p.title() for p in parts if p)
            
            if self._is_valid_name(name):
                professors.append(Professor(name=name, email=email))
        
        return professors
    
    def _guess_department(self, soup) -> str:
        for sel in ['h1', '.page-title', 'title']:
            elem = soup.select_one(sel)
            if elem:
                text = self._clean_text(elem.get_text())
                if len(text) < 100:
                    return text
        return "General"


# =============================================================================
# Adapter Registry
# =============================================================================

class AdapterRegistry:
    """Registry of site adapters."""
    
    def __init__(self):
        self._adapters: List[Type[SiteAdapter]] = []
        self._register_defaults()
    
    def _register_defaults(self):
        for adapter in [PrincetonAdapter, UCTAdapter, IITAdapter, MITAdapter, GenericAdapter]:
            self.register(adapter)
    
    def register(self, adapter_class: Type[SiteAdapter]):
        self._adapters.append(adapter_class)
        self._adapters.sort(key=lambda a: a.PRIORITY, reverse=True)
    
    def get_adapter(self, url: str) -> SiteAdapter:
        for adapter_class in self._adapters:
            if adapter_class.matches_domain(url):
                return adapter_class()
        return GenericAdapter()


_registry: Optional[AdapterRegistry] = None


def get_adapter_registry() -> AdapterRegistry:
    global _registry
    if _registry is None:
        _registry = AdapterRegistry()
    return _registry


async def extract_professors(html: str, url: str, **kwargs) -> ExtractionResult:
    """
    Extract professors from HTML.
    
    Automatically selects the best adapter for the URL.
    """
    adapter = get_adapter_registry().get_adapter(url)
    return await adapter.extract(html, url, **kwargs)


# =============================================================================
# LLM-Based Extraction (for complex pages)
# =============================================================================

async def extract_with_llm(html: str, url: str, model: str = None) -> ExtractionResult:
    """
    Extract using LLM for complex pages.
    
    Falls back to this when CSS-based extraction fails.
    """
    try:
        import litellm
        from .config import settings, cost_tracker
        
        model = model or settings.get_model()
        
        # Truncate HTML for LLM
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove scripts/styles
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        
        text = soup.get_text(separator='\n', strip=True)[:8000]
        
        prompt = f"""Extract faculty/professor information from this webpage.
Return a JSON array of objects with: name, title, email, profile_url

Only include actual faculty members (professors, researchers, lecturers).
Skip navigation links, administrative staff, etc.

Content:
{text}

Return ONLY valid JSON array, no markdown:"""
        
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        
        # Track usage
        if hasattr(response, 'usage') and response.usage:
            cost_tracker.track_usage(
                model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens
            )
        
        # Parse response
        content = response.choices[0].message.content
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
        
        data = json.loads(content)
        
        professors = []
        for item in data:
            if isinstance(item, dict) and item.get('name'):
                professors.append(Professor(
                    name=item.get('name'),
                    title=item.get('title'),
                    email=item.get('email'),
                    profile_url=item.get('profile_url')
                ))
        
        return ExtractionResult(
            professors=professors,
            confidence=0.7,
            method="llm"
        )
        
    except Exception as e:
        logger.error(f"LLM extraction failed: {e}")
        return ExtractionResult(professors=[], method="llm-failed")


async def extract_with_fallback(
    html: str,
    url: str,
    min_results: int = 3,
    screenshot: bytes = None,
    enable_vision: bool = False
) -> ExtractionResult:
    """
    Extract with fallback chain: CSS → LLM → Vision.
    
    Args:
        html: HTML content
        url: Page URL
        min_results: Minimum acceptable results
        screenshot: Optional screenshot bytes for vision analysis
        enable_vision: Enable vision-based extraction
    
    Returns:
        ExtractionResult with best available extraction
    """
    # Try CSS-based first
    result = await extract_professors(html, url)
    
    if len(result.professors) >= min_results:
        return result
    
    # Fallback to LLM
    logger.info(f"CSS extraction found {len(result.professors)}, trying LLM...")
    llm_result = await extract_with_llm(html, url)
    
    if len(llm_result.professors) >= min_results:
        return llm_result
    
    # Ultimate fallback: Vision (if enabled and screenshot available)
    if enable_vision and screenshot:
        logger.info("LLM extraction insufficient, trying vision analysis...")
        try:
            from .analyzers import analyze_page_with_vision
            
            vision_result = await analyze_page_with_vision(screenshot, url)
            
            if len(vision_result.professors) > len(llm_result.professors):
                return vision_result
        except Exception as e:
            logger.warning(f"Vision analysis failed: {e}")
    
    # Return best available result
    return llm_result if len(llm_result.professors) > len(result.professors) else result

