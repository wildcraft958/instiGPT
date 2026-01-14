import os
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
    MODEL_NAME = "openai/gpt-4o-mini"  # Default to cheaper model
    
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
        
        Prefers Ollama models when OLLAMA_BASE_URL is set to save API costs.
        
        Args:
            task: One of 'schema_discovery', 'page_classification', 'detail_extraction'
            prefer_local: Override for PREFER_LOCAL_MODELS setting
        
        Returns:
            Model string in litellm format (e.g., 'ollama/llama3.1:8b')
        """
        use_local = prefer_local if prefer_local is not None else Settings.PREFER_LOCAL_MODELS
        
        if use_local and os.getenv("OLLAMA_BASE_URL"):
            ollama_models = {
                "schema_discovery": "ollama/llama3.1:8b",
                "page_classification": "ollama/qwen2.5:7b",
                "detail_extraction": "ollama/llama3.1:8b",
                "fallback": "ollama/llama3.1:8b",
            }
            return ollama_models.get(task, "ollama/llama3.1:8b")
        
        # Cloud models (cheaper options)
        cloud_models = {
            "schema_discovery": "openai/gpt-4o-mini",
            "page_classification": "openai/gpt-4o-mini",
            "detail_extraction": "openai/gpt-4o-mini",
            "fallback": "openai/gpt-4o-mini",
        }
        return cloud_models.get(task, "openai/gpt-4o-mini")
    
    @staticmethod
    def is_ollama_available() -> bool:
        """Check if Ollama is configured and should be used."""
        return bool(os.getenv("OLLAMA_BASE_URL"))


settings = Settings()

