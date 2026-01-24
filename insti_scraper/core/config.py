import os
import logging
from rich.logging import RichHandler
from crawl4ai import CrawlerRunConfig, CacheMode

# Keywords that indicate faculty-related content
FACULTY_KEYWORDS = [
    "faculty", "people", "staff", "professor", "directory",
    "profiles", "team", "members", "academic", "researchers",
    "instructor", "lecturer", "scholar", "expert", "scientist"
]

# URL patterns that likely lead to faculty pages
FACULTY_URL_PATTERNS = [
    "*faculty*", "*people*", "*staff*", "*professor*",
    "*directory*", "*profiles*", "*our-team*", "*researchers*"
]

class Settings:
    # Model settings
    MODEL_NAME = "openai/gpt-4o-mini"
    
    # Scraping settings
    MAX_PAGES = 5
    CHUNK_SIZE_PHASE_2 = 5
    
    # Discovery settings
    DISCOVER_MAX_DEPTH = 3
    DISCOVER_MAX_PAGES = 50
    DISCOVER_MIN_SITEMAP_RESULTS = 10
    
    # Cost-saving defaults
    CACHE_ENABLED = True
    PREFER_LOCAL_MODELS = True
    
    @staticmethod
    def setup_logging():
        """Configures Rich logging and File logging."""
        os.makedirs("logs", exist_ok=True)
        import datetime
        log_file = f"logs/scraper_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        logging.basicConfig(
            level="INFO",
            format="%(asctime)s | %(levelname)s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[
                RichHandler(rich_tracebacks=True, show_time=False),
                logging.FileHandler(log_file)
            ]
        )
        # Suppress noisy libraries
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("crawl4ai").setLevel(logging.WARNING)

    @staticmethod
    def get_run_config(
        magic: bool = True, 
        scan_full_page: bool = False,
        headless: bool = True,
        use_cache: bool = None
    ) -> CrawlerRunConfig:
        """Get crawler run configuration."""
        cache = use_cache if use_cache is not None else Settings.CACHE_ENABLED
        return CrawlerRunConfig(
            cache_mode=CacheMode.ENABLED if cache else CacheMode.BYPASS,
            scan_full_page=scan_full_page,
            scroll_delay=0.5,
            word_count_threshold=5,
            magic=magic
        )
    
    @staticmethod
    def get_model_for_task(task: str, prefer_local: bool = None) -> str:
        """
        Get appropriate model for a specific task.
        """
        use_local = prefer_local if prefer_local is not None else Settings.PREFER_LOCAL_MODELS
        
        if use_local and os.getenv("OLLAMA_BASE_URL"):
            # Local models (free)
            return "ollama/llama3.1:8b"
        
        # Cloud models with Smart Routing
        # Use stronger models for difficult extraction
        strong_models = {
            "detail_extraction": "openai/gpt-4o",
            "scholar_linking": "openai/gpt-4o",
        }
        return strong_models.get(task, "openai/gpt-4o-mini")
    
    @staticmethod
    def is_ollama_available() -> bool:
        return bool(os.getenv("OLLAMA_BASE_URL"))

settings = Settings()

