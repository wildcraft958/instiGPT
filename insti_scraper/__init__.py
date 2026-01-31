"""
Insti-Scraper: AI-powered faculty data scraper.

Architecture:
- models.py              - Data models (Professor, University, etc.)
- config.py              - Settings, logging, cost tracking
- crawler.py             - Web fetching (HTTP + browser)
- discovery.py           - Faculty page discovery (sitemap, deep crawl)
- duckduckgo_discovery.py - Advanced DuckDuckGo search discovery
- extractors.py          - Data extraction (CSS + LLM)
- enrichment.py          - Google Scholar enrichment
- database.py            - Advanced database operations
- analyzers/             - Vision-based analysis (Gemini/GPT-4V)
- pipelines/             - Batch processing pipelines
- main.py                - CLI entry point
"""

from .models import Professor, University, Department, ExtractionResult, DiscoveredPage
from .config import settings, cost_tracker, console
from .crawler import CrawlerManager, FetchMode, FetchResult
from .discovery import FacultyPageDiscoverer, discover_faculty_pages
from .duckduckgo_discovery import DuckDuckGoDiscovery, discover_with_duckduckgo
from .extractors import extract_professors, extract_with_fallback, AdapterRegistry
from .enrichment import enrich_professor
from .database import DatabaseManager, get_db_manager
from .analyzers import VisionAnalyzer, analyze_page_with_vision
from .pipelines import UniversityProcessor, process_universities_batch

__all__ = [
    # Models
    "Professor",
    "University", 
    "Department",
    "ExtractionResult",
    "DiscoveredPage",
    
    # Config
    "settings",
    "cost_tracker",
    "console",
    
    # Crawler
    "CrawlerManager",
    "FetchMode",
    "FetchResult",
    
    # Discovery
    "FacultyPageDiscoverer",
    "discover_faculty_pages",
    "DuckDuckGoDiscovery",
    "discover_with_duckduckgo",
    
    # Extraction
    "extract_professors",
    "extract_with_fallback",
    "AdapterRegistry",
    
    # Enrichment
    "enrich_professor",
    
    # Database
    "DatabaseManager",
    "get_db_manager",
    
    # Analyzers
    "VisionAnalyzer",
    "analyze_page_with_vision",
    
    # Pipelines
    "UniversityProcessor",
    "process_universities_batch",
]
