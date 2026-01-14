"""
Rate limiting wrapper for Crawl4AI using MemoryAdaptiveDispatcher.

Provides configurable request throttling to avoid overwhelming target servers.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional, Tuple, List
from crawl4ai import MemoryAdaptiveDispatcher, RateLimiter


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    base_delay: Tuple[float, float] = (1.0, 2.0)  # Random delay between requests (min, max)
    max_delay: Tuple[float, float] = (30.0, 60.0)  # Maximum backoff delay
    max_retries: int = 3
    memory_threshold_percent: float = 70.0  # Pause if memory exceeds this
    max_concurrent_sessions: int = 10  # Maximum parallel browser sessions
    rate_limit_codes: List[int] = None  # HTTP codes that trigger backoff
    
    def __post_init__(self):
        if self.rate_limit_codes is None:
            self.rate_limit_codes = [429, 503, 502, 504]


class AdaptiveRateLimiter:
    """
    Wrapper around Crawl4AI's MemoryAdaptiveDispatcher.
    
    Features:
    - Memory-aware throttling (pauses when memory high)
    - Configurable delays between requests
    - Automatic backoff on rate limit responses
    """
    
    def __init__(self, config: RateLimitConfig = None):
        """
        Initialize the rate limiter.
        
        Args:
            config: Rate limit configuration. Uses defaults if not provided.
        """
        self.config = config or RateLimitConfig()
        self._dispatcher: Optional[MemoryAdaptiveDispatcher] = None
        self._rate_limiter: Optional[RateLimiter] = None
    
    def get_dispatcher(self) -> MemoryAdaptiveDispatcher:
        """Get or create the MemoryAdaptiveDispatcher instance."""
        if self._dispatcher is None:
            self._rate_limiter = RateLimiter(
                base_delay=self.config.base_delay,
                max_delay=self.config.max_delay,
                max_retries=self.config.max_retries,
                rate_limit_codes=self.config.rate_limit_codes
            )
            
            self._dispatcher = MemoryAdaptiveDispatcher(
                memory_threshold_percent=self.config.memory_threshold_percent,
                max_session_permit=self.config.max_concurrent_sessions,
                rate_limiter=self._rate_limiter
            )
        
        return self._dispatcher
    
    async def wait_if_needed(self, url: str = None):
        """
        Wait before making a request if rate limiting is needed.
        
        This can be used for manual rate limiting outside of arun_many.
        """
        delay = asyncio.uniform(*self.config.base_delay)
        await asyncio.sleep(delay)
    
    def get_stats(self) -> dict:
        """Get rate limiting statistics."""
        return {
            "config": {
                "base_delay": self.config.base_delay,
                "max_delay": self.config.max_delay,
                "memory_threshold": f"{self.config.memory_threshold_percent}%",
                "max_sessions": self.config.max_concurrent_sessions
            }
        }


# Singleton instance
_rate_limiter_instance: Optional[AdaptiveRateLimiter] = None


def get_rate_limiter(config: RateLimitConfig = None) -> AdaptiveRateLimiter:
    """Get or create the global rate limiter instance."""
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        _rate_limiter_instance = AdaptiveRateLimiter(config)
    return _rate_limiter_instance
