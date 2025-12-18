from crawl4ai import CrawlerRunConfig, CacheMode

class Settings:
    MODEL_NAME = "openai/gpt-4o"
    MAX_PAGES = 5
    CHUNK_SIZE_PHASE_2 = 5
    
    @staticmethod
    def get_run_config(magic: bool = True, scan_full_page: bool = False, headless: bool = True) -> CrawlerRunConfig:
        return CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            scan_full_page=scan_full_page,
            scroll_delay=0.5,
            word_count_threshold=5,
            magic=magic
        )

settings = Settings()
