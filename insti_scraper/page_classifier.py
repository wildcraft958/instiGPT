"""
Hybrid page classification using rule-based + LLM approach.

Classifies faculty pages into types A-Z to determine extraction strategy.
Based on segmentcodenew_rule+LLM.py logic.
"""

import os
import re
from dataclasses import dataclass
from typing import Optional
from bs4 import BeautifulSoup

from litellm import completion
from .config import settings


@dataclass
class ClassificationResult:
    """Result of page classification."""
    page_type: str  # A, B, C, D, E, F, or Z
    confidence: float  # 0.0 to 1.0
    reason: str
    used_llm: bool = False
    
    def to_dict(self) -> dict:
        return {
            "page_type": self.page_type,
            "confidence": self.confidence,
            "reason": self.reason,
            "used_llm": self.used_llm
        }


# Page type descriptions for reference
PAGE_TYPES = {
    "A": "Profile Links - List of names with 'View Profile' buttons to click",
    "B": "Full Info - Emails and research interests visible directly on page",
    "C": "Department Gateway - List of departments/schools to navigate",
    "D": "Paginated Directory - A-Z listing or paginated results",
    "E": "Search/Interactive - Requires search/filter to show results",
    "F": "Lab/Personal Site - Research group or PI's personal page",
    "Z": "Junk/Blocked - Login, 404, Access Denied, or irrelevant content",
}


def extract_features(html: str, url: str = "") -> Optional[dict]:
    """
    Extract features from HTML for classification.
    
    Based on segmentcodenew_rule+LLM.py extract_features().
    """
    if not html:
        return None
    
    soup = BeautifulSoup(html, "html.parser")
    
    # Strip noise
    for tag in soup(["script", "style", "header", "footer", "nav", "aside", "noscript"]):
        tag.decompose()
    
    # Find main content
    main_content = (
        soup.find("main") or 
        soup.find("div", {"id": re.compile(r"content|main", re.I)}) or 
        soup.find("div", {"role": "main"})
    )
    content_root = main_content if main_content else soup.body
    
    # Text analysis
    text_content = content_root.get_text(separator=' ', strip=True) if content_root else ""
    text_lower = text_content.lower()
    page_title = soup.title.string.strip() if soup.title and soup.title.string else "No Title"
    
    # Link analysis
    all_links = soup.find_all("a", href=True)
    
    # Profile links (View Profile, Bio, People/xyz)
    profile_links = [
        a for a in all_links 
        if any(x in a.get('href', '').lower() for x in ['profile', 'bio', 'people/', 'person/', 'faculty/'])
    ]
    
    # Department links (School of X, Dept of Y)
    dept_links = [
        a for a in all_links 
        if any(x in a.text.lower() for x in ['department', 'school', 'faculty of', 'college of'])
    ]
    
    # Search inputs
    inputs = soup.find_all("input")
    search_inputs = [
        i for i in inputs 
        if "search" in str(i).lower() or i.get("type") == "search"
    ]
    
    # Pagination indicators
    has_pagination = bool(
        "next >" in text_lower or 
        "page 1 of" in text_lower or 
        "« previous" in text_lower or
        soup.find("a", {"rel": "next"}) or
        soup.find("a", class_=re.compile(r"next|pagination"))
    )
    
    # Keyword counts
    role_terms = [
        "professor", "lecturer", "instructor", "adjunct", "faculty",
        "reader", "fellow", "chair", "associate", "assistant",
        "academic staff", "investigator", "scientist"
    ]
    contact_terms = ["email", "@", "phone", "tel:", "contact", "office", "room"]
    research_terms = ["research", "publication", "interest", "expertise", "biography", "bio"]
    
    block_terms = [
        "access denied", "security check", "cloudflare", "captcha",
        "403 forbidden", "incapsula", "imperva", "human verification",
        "robot", "automated request", "please enable javascript"
    ]
    
    features = {
        "page_title": page_title,
        "text_preview": text_content[:5000],
        "text_length": len(text_content),
        "img_count": len(soup.find_all("img")),
        "profile_link_count": len(profile_links),
        "dept_link_count": len(dept_links),
        "link_count": len(all_links),
        "has_search_bar": len(search_inputs) > 0,
        "has_pagination": has_pagination,
        "keywords": {
            "professor": sum(text_lower.count(t) for t in role_terms),
            "email": sum(text_lower.count(t) for t in contact_terms),
            "research": sum(text_lower.count(t) for t in research_terms),
            "blocked": any(t in text_lower or t in page_title.lower() for t in block_terms)
        }
    }
    
    return features


def rule_classify(features: dict) -> tuple[str, float]:
    """
    Rule-based classification without LLM.
    
    Returns (page_type, confidence).
    Confidence > 0.75 means we trust the rule and can skip LLM.
    """
    if not features:
        return "Z", 0.0
    
    # RULE 1: Blocked/Junk Detection (Z)
    if features["keywords"]["blocked"]:
        return "Z", 0.95
    
    if features["text_length"] < 200:
        return "Z", 0.6  # Too short, probably junk, but let LLM confirm
    
    # RULE 2: Department Gateway (C)
    # Many links to "School of..." or "Dept of..." and few actual profiles
    if features["dept_link_count"] > 8 and features["profile_link_count"] < 5:
        return "C", 0.9
    
    # RULE 3: Search/Interactive (E)
    # Search bar exists, very few links, low text content
    if features["has_search_bar"] and features["link_count"] < 15 and features["keywords"]["professor"] < 3:
        return "E", 0.85
    
    # RULE 4: Paginated Directory (D)
    if features["has_pagination"]:
        return "D", 0.85
    
    # RULE 5: Profile Links Directory (A)
    # Lots of "Profile" links
    if features["profile_link_count"] > 10:
        return "A", 0.8
    
    # RULE 6: Full Info Page (B)
    # Lots of professor mentions AND email/contact info visible
    if features["keywords"]["professor"] > 5 and features["keywords"]["email"] > 5:
        return "B", 0.75
    
    # RULE 7: Research/Lab Page (F)
    if features["keywords"]["research"] > 10 and features["keywords"]["professor"] < 3:
        return "F", 0.7
    
    # DEFAULT: Low confidence, need LLM
    return "Z", 0.3


async def llm_classify(
    url: str, 
    features: dict, 
    model: str = None
) -> str:
    """
    LLM-based classification fallback.
    """
    model = model or settings.MODEL_NAME
    
    prompt = f"""Classify this university webpage based on the text preview.

URL: {url}
Title: {features['page_title']}
Text Preview (first 3000 chars): "{features['text_preview'][:3000]}..."

**CLASSIFICATION RULES:**
1. **Type C (Department List)**: List of "Departments", "Schools", "Faculties".
2. **Type E (Search/Filters)**: Search bar, "Filter by", empty list needing interaction.
3. **Type D (A-Z/Directory)**: "A-Z Listing", "Page 1 of...", pagination.
4. **Type F (Lab/Personal Site)**: "Welcome to [Name] Lab", "Principal Investigator", "Our Team".
5. **Type A (Profile Links)**: List of names where you MUST click "View Profile" to see details.
6. **Type B (Full Info)**: Emails and Research Interests are visible RIGHT HERE on this page.
7. **Type Z (Junk)**: Login, 404, Access Denied, News, General Home.

Return ONLY the single letter (A, B, C, D, E, F, or Z).
"""
    
    try:
        response = completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=5,
            api_base=os.getenv("OLLAMA_BASE_URL") if "ollama" in model.lower() else None
        )
        
        result = response.choices[0].message.content.strip().upper()
        
        # Validate result
        if result in ["A", "B", "C", "D", "E", "F", "Z"]:
            return result
        
        # Try to extract first valid letter
        for char in result:
            if char in ["A", "B", "C", "D", "E", "F", "Z"]:
                return char
        
        return "Z"
        
    except Exception as e:
        print(f"   LLM classification error: {e}")
        return "Z"


async def classify_page(
    url: str, 
    html: str, 
    model: str = None,
    confidence_threshold: float = 0.75
) -> ClassificationResult:
    """
    Main entry point: Classify a faculty page.
    
    Uses hybrid approach:
    1. Rule-based classification (fast, no API calls)
    2. LLM fallback if confidence < threshold
    
    Args:
        url: Page URL
        html: Page HTML content
        model: LLM model for fallback
        confidence_threshold: Threshold to use LLM (default 0.75)
        
    Returns:
        ClassificationResult with page_type, confidence, and reason
    """
    # Extract features
    features = extract_features(html, url)
    
    if not features:
        return ClassificationResult(
            page_type="Z",
            confidence=0.0,
            reason="Failed to extract features from HTML"
        )
    
    # Rule-based classification
    rule_type, confidence = rule_classify(features)
    used_llm = False
    final_type = rule_type
    
    # LLM fallback for low confidence
    if confidence < confidence_threshold and features is not None:
        llm_type = await llm_classify(url, features, model)
        if llm_type in ["A", "B", "C", "D", "E", "F", "Z"]:
            final_type = llm_type
            used_llm = True
    
    # Generate reason
    reason = PAGE_TYPES.get(final_type, "Unknown page type")
    if used_llm:
        reason = f"[LLM] {reason}"
    else:
        reason = f"[Rule] {reason} (confidence: {confidence:.0%})"
    
    return ClassificationResult(
        page_type=final_type,
        confidence=confidence,
        reason=reason,
        used_llm=used_llm
    )


# Backward compatibility wrapper
async def classify_page_type(url: str, html_content: str, model_name: str) -> dict:
    """Wrapper for backward compatibility with existing code."""
    result = await classify_page(url, html_content, model_name)
    
    # Map new types to old format for compatibility
    type_mapping = {
        "A": "faculty_directory",
        "B": "faculty_directory",
        "C": "department_list",
        "D": "faculty_directory",
        "E": "search_interface",
        "F": "other",
        "Z": "other"
    }
    
    return {
        "page_type": type_mapping.get(result.page_type, "other"),
        "detailed_type": result.page_type,
        "confidence": result.confidence,
        "reason": result.reason
    }
