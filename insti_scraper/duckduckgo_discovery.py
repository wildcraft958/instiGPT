"""
DuckDuckGo-based faculty URL discovery.

Uses DuckDuckGo search + LLM-powered URL selection to find faculty pages
when sitemap-based discovery fails.
"""

import os
import re
import time
from typing import List, Optional
from urllib.parse import urlparse
import requests

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

from litellm import completion
from .config import settings


# URL patterns that indicate faculty-related content
ACCEPT_TOKENS = [
    "/faculty", "/people", "/staff", "/directory", "/departments", "/profiles",
    "/our-people", "/faculty-directory", "/people-list", "/academic-staff",
    "/teaching-staff", "/staff-list", "/researchers", "/academics"
]

# URL patterns that should be rejected
REJECT_TOKENS = [
    "about-us", "governance", "contact", "alumni", "news", "events", "calendar",
    "jobs", "careers", "press", "store", "admissions", "prospectus", "apply",
    "course", "courses", "faq", "help", "privacy", "policy", "facebook",
    "linkedin", "twitter", "instagram", "youtube", "researchgate", "pdf"
]


def is_ddgs_available() -> bool:
    """Check if DuckDuckGo Search is available."""
    return DDGS is not None


def validate_faculty_url(url: str) -> bool:
    """
    Quick validation of URL based on URL patterns.
    Returns True if URL looks like a faculty directory.
    """
    if not url or not isinstance(url, str):
        return False
    
    u = url.lower()
    
    # Quick reject: Generic/social pages
    for t in REJECT_TOKENS:
        if t in u:
            return False
    
    # Quick accept: Faculty-related URL patterns
    for t in ACCEPT_TOKENS:
        if t in u:
            return True
    
    # Reject individual profiles (we want the list, not the person)
    path = urlparse(u).path
    if re.search(r"/(people|profile|person|staff|faculty)/[^/]+$", path):
        return False
    
    return False  # Default to reject if no patterns match


def deep_validate_url(url: str, timeout: float = 5.0) -> bool:
    """
    Deep validation - fetches page content to check for faculty indicators.
    More expensive but more accurate.
    """
    try:
        resp = requests.get(
            url, 
            timeout=timeout, 
            allow_redirects=True, 
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if resp.status_code != 200:
            return False
        
        text = resp.text.lower()[:100000]  # Analyze first 100KB
        
        # Check for directory phrases
        directory_phrases = [
            "staff directory", "faculty directory", "directory of staff", 
            "find a person", "search people", "search staff", "browse people", 
            "our people", "faculty members", "our staff", "academic staff",
            "list of faculty", "faculty & staff"
        ]
        
        # Count profile-like links
        hrefs = re.findall(r'href=["\'"]([^"\']+)["\']', resp.text, flags=re.IGNORECASE)
        profile_tokens = ["/people", "/profile", "/staff", "/person", "/academic"]
        profile_count = sum(1 for h in hrefs if any(pt in h.lower() for pt in profile_tokens))
        
        # Accept if many profile links or directory phrases found
        if profile_count >= 5:
            return True
        if any(phrase in text for phrase in directory_phrases):
            return True
        
        return False
    except Exception:
        return False


def search_faculty_urls(
    university_name: str, 
    homepage_url: str = "",
    max_results: int = 5,
    max_retries: int = 3
) -> List[str]:
    """
    Search for faculty directory URLs using DuckDuckGo.
    
    Args:
        university_name: Name of the university
        homepage_url: University homepage (used for site-specific search)
        max_results: Max results per query
        max_retries: Number of retries on failure
        
    Returns:
        List of candidate faculty URLs
    """
    if not is_ddgs_available():
        print("⚠️ ddgs not installed. Run: uv add ddgs")
        return []
    
    # Extract domain for site-specific search
    domain = urlparse(homepage_url).netloc if homepage_url else ""
    
    # Build queries - prioritize site-specific if we have domain
    queries = []
    
    if domain:
        # Site-specific queries (most reliable)
        queries.extend([
            f"site:{domain} faculty list department",
            f"site:{domain} academic staff",
            f"site:{domain} faculty directory",
            f"site:{domain} people",
            f"{domain} faclistbydepartment",  # Common IIT pattern
        ])
    
    # Fallback general queries
    queries.extend([
        f"{university_name} faculty directory site",
        f"{university_name} academic staff list",
        f"{university_name} departments faculty",
    ])
    
    candidates = []
    seen_urls = set()
    
    for attempt in range(max_retries):
        try:
            with DDGS() as ddgs:
                for query in queries:
                    results = list(ddgs.text(query, max_results=max_results))
                    
                    for r in results:
                        url = r.get('href', '')
                        
                        # Skip if already seen or is PDF
                        if url in seen_urls or url.endswith('.pdf'):
                            continue
                        if homepage_url and url.rstrip('/') == homepage_url.rstrip('/'):
                            continue
                        
                        # Prefer URLs from same domain
                        url_domain = urlparse(url).netloc
                        is_same_domain = domain and domain in url_domain
                        
                        # Accept if same domain OR passes URL validation
                        if is_same_domain or validate_faculty_url(url):
                            candidates.append(url)
                            seen_urls.add(url)
                    
                    time.sleep(0.2)  # Rate limiting
            
            if candidates:
                print(f"   Found {len(candidates)} candidates")
                break
            else:
                print(f"   Retry {attempt + 1}/{max_retries}...")
                time.sleep(1)
                
        except Exception as e:
            print(f"   Search error: {e}")
            time.sleep(1)
    
    return list(set(candidates))


async def select_best_url(
    university_name: str,
    candidates: List[str],
    model: str = None
) -> Optional[str]:
    """
    Use LLM to select the best faculty directory URL from candidates.
    
    Args:
        university_name: Name of the university
        candidates: List of candidate URLs
        model: LLM model to use (defaults to settings.MODEL_NAME)
        
    Returns:
        Best URL or None if no good candidate found
    """
    if not candidates:
        return None
    
    model = model or settings.MODEL_NAME
    links_text = "\n".join(candidates[:30])  # Limit to 30 candidates
    
    prompt = f"""I need the best URL for finding {university_name} professors/staff.
I need a page with a **list of faculty members**, **departments**, or **academic staff**.

Candidate URLs:
{links_text}

### INSTRUCTIONS:
1. **Target:** Look for "Faculty Directory", "Departments", "Schools", "People", or "Academic Staff".
2. **Prefer:** Pages that list MULTIPLE people, not individual profiles.
3. **Avoid:** News, events, contact, about-us, social media links.

Return ONLY the single best URL (just the URL, nothing else).
If none are suitable, return "NONE".
"""
    
    try:
        response = completion(
            model=model,
            messages=[
                {"role": "system", "content": "Output only the raw URL string or 'NONE'."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=150,
            api_base=os.getenv("OLLAMA_BASE_URL") if "ollama" in model.lower() else None
        )
        
        result = response.choices[0].message.content.strip()
        
        if result.upper() == "NONE":
            return None
        
        # Extract URL if embedded in text
        if "http" in result:
            match = re.search(r'(https?://\S+)', result)
            return match.group(1) if match else result
        
        return None
        
    except Exception as e:
        print(f"   LLM selection error: {e}")
        # Fallback: return first candidate
        return candidates[0] if candidates else None


async def discover_faculty_url(
    university_name: str,
    homepage_url: str = "",
    model: str = None,
    deep_validate: bool = False
) -> Optional[str]:
    """
    Main entry point: Discover faculty URL for a university.
    
    Args:
        university_name: Name of the university (e.g., "MIT")
        homepage_url: University homepage URL
        model: LLM model for selection
        deep_validate: Whether to fetch pages for deeper validation
        
    Returns:
        Best faculty URL or None
    """
    print(f"🔎 Searching for {university_name} faculty pages...")
    
    # Step 1: Search using DuckDuckGo
    candidates = search_faculty_urls(university_name, homepage_url)
    
    if not candidates:
        print(f"   ❌ No candidates found via search")
        return None
    
    print(f"   Found {len(candidates)} candidates")
    
    # Step 2: Deep validation (optional)
    if deep_validate:
        validated = [url for url in candidates if deep_validate_url(url)]
        if validated:
            candidates = validated
            print(f"   {len(candidates)} passed deep validation")
    
    # Step 3: LLM selection
    best_url = await select_best_url(university_name, candidates, model)
    
    if best_url:
        print(f"   ✅ Selected: {best_url}")
    else:
        print(f"   ❌ No suitable URL found")
    
    return best_url
