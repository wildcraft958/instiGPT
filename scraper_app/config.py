"""
Configuration management using pydantic-settings.
"""
import os
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    # API Keys
    GOOGLE_API_KEY: str = ""
    
    # Ollama Configuration
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_VISION_MODEL: str = "qwen3-vl"
    OLLAMA_TEXT_MODEL: str = "llama3.2:latest"
    
    # Browser Configuration
    HEADLESS_MODE: bool = False
    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    VIEWPORT_WIDTH: int = 1920
    VIEWPORT_HEIGHT: int = 1080
    PAGE_TIMEOUT_MS: int = 60000
    
    # Crawling Configuration
    REQUEST_DELAY_MS: int = 1000
    MAX_STEPS: int = 50
    MAX_RETRIES: int = 3
    
    # Output Configuration
    OUTPUT_DIR: str = "scraped_data"
    HTML_LOGS_DIR: str = "html_logs"
    SCREENSHOTS_DIR: str = "screenshots"
    DEBUG_MODE: bool = False
    
    # Backend Selection
    DEFAULT_BACKEND: Literal["auto", "gemini", "local"] = "auto"
    
    def is_colab_or_headless_env(self) -> bool:
        """Detect if running in Colab or headless Linux environment."""
        return (
            "COLAB_GPU" in os.environ or
            "COLAB_RELEASE_TAG" in os.environ or
            (os.name == "posix" and not os.environ.get("DISPLAY"))
        )


# Global settings instance
settings = Settings()
