"""
Configuration, logging, and cost tracking.

Consolidated from core/config.py, core/logger.py, core/cost_tracker.py
"""

import os
import logging
import threading
from typing import Dict
from datetime import datetime

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from crawl4ai import CrawlerRunConfig, CacheMode

console = Console()

# =============================================================================
# Keywords for Faculty Detection
# =============================================================================

FACULTY_KEYWORDS = [
    "faculty", "people", "staff", "professor", "directory",
    "profiles", "team", "members", "academic", "researchers",
    "instructor", "lecturer", "scholar", "expert", "scientist"
]

EXCLUDE_PATTERNS = [
    r"/login", r"/search\?", r"/calendar", r"/events/",
    r"/contact$", r"/apply$", r"/admission",
    r"\.pdf$", r"\.jpg$", r"\.png$", r"\.xml$",
]


# =============================================================================
# Settings
# =============================================================================

class Settings:
    """Application settings."""
    
    MODEL_NAME = "openai/gpt-4o-mini"
    CACHE_ENABLED = True
    PREFER_LOCAL_MODELS = True
    
    # Discovery
    MAX_DEPTH = 3
    MAX_PAGES = 50
    
    @staticmethod
    def setup_logging():
        """Configure logging with Rich."""
        os.makedirs("logs", exist_ok=True)
        log_file = f"logs/scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        logging.basicConfig(
            level="INFO",
            format="%(message)s",
            datefmt="[%X]",
            handlers=[
                RichHandler(rich_tracebacks=True, show_time=True, show_path=False),
                logging.FileHandler(log_file)
            ]
        )
        # Suppress noisy libraries
        for lib in ["httpx", "crawl4ai", "sqlalchemy.engine", "httpcore"]:
            logging.getLogger(lib).setLevel(logging.WARNING)
    
    @staticmethod
    def get_run_config(use_cache: bool = None) -> CrawlerRunConfig:
        """Get crawler configuration."""
        cache = use_cache if use_cache is not None else Settings.CACHE_ENABLED
        return CrawlerRunConfig(
            cache_mode=CacheMode.ENABLED if cache else CacheMode.BYPASS,
            scroll_delay=0.5,
            word_count_threshold=5,
        )
    
    @staticmethod
    def get_model(task: str = None) -> str:
        """Get model for task."""
        if Settings.PREFER_LOCAL_MODELS:
            return "ollama/llama3.1:8b"
        return Settings.MODEL_NAME


settings = Settings()
logger = logging.getLogger(__name__)


# =============================================================================
# Cost Tracker (Singleton)
# =============================================================================

class CostTracker:
    """Track LLM API usage and costs."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.reset()
        return cls._instance
    
    def reset(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.model_usage: Dict[str, dict] = {}
    
    def track_usage(self, model: str, input_tokens: int, output_tokens: int, cost: float = 0.0):
        with self._lock:
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_cost += cost
            
            if model not in self.model_usage:
                self.model_usage[model] = {"input": 0, "output": 0, "cost": 0.0}
            
            self.model_usage[model]["input"] += input_tokens
            self.model_usage[model]["output"] += output_tokens
            self.model_usage[model]["cost"] += cost
    
    def print_summary(self):
        if not self.model_usage:
            return
            
        table = Table(title="💰 LLM Usage Summary", show_header=True)
        table.add_column("Model", style="cyan")
        table.add_column("Input Tokens", justify="right")
        table.add_column("Output Tokens", justify="right")
        table.add_column("Cost ($)", justify="right", style="green")
        
        for model, stats in self.model_usage.items():
            table.add_row(
                model,
                f"{stats['input']:,}",
                f"{stats['output']:,}",
                f"${stats['cost']:.4f}"
            )
        
        console.print("\n")
        console.print(table)
        console.print(f"\n[bold]Total: [green]${self.total_cost:.4f}[/green][/bold]\n")


cost_tracker = CostTracker()
