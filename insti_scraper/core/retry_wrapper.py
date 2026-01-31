"""
Retry logic with exponential backoff using tenacity.

Provides decorators and utilities for automatic retry on transient failures.
"""

import asyncio
import functools
from typing import Type, Tuple, Callable, Any
from dataclasses import dataclass


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    base_delay: float = 2.0  # Initial delay in seconds
    max_delay: float = 30.0  # Maximum delay
    exponential_factor: float = 2.0  # Multiply delay by this each retry
    retry_exceptions: Tuple[Type[Exception], ...] = None
    
    def __post_init__(self):
        if self.retry_exceptions is None:
            self.retry_exceptions = (
                TimeoutError,
                ConnectionError,
                asyncio.TimeoutError,
            )


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate the delay for a given attempt using exponential backoff."""
    delay = config.base_delay * (config.exponential_factor ** attempt)
    return min(delay, config.max_delay)


def retry_async(config: RetryConfig = None):
    """
    Decorator for async functions that should be retried on failure.
    
    Usage:
        @retry_async(RetryConfig(max_attempts=5))
        async def fetch_data(url: str):
            ...
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return await func(*args, **kwargs)
                except config.retry_exceptions as e:
                    last_exception = e
                    
                    if attempt < config.max_attempts - 1:
                        delay = calculate_delay(attempt, config)
                        print(f"  ⚠️ Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                        await asyncio.sleep(delay)
                    else:
                        print(f"  ❌ All {config.max_attempts} attempts failed")
            
            raise last_exception
        
        return wrapper
    return decorator


def retry_sync(config: RetryConfig = None):
    """
    Decorator for sync functions that should be retried on failure.
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            import time
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except config.retry_exceptions as e:
                    last_exception = e
                    
                    if attempt < config.max_attempts - 1:
                        delay = calculate_delay(attempt, config)
                        print(f"  ⚠️ Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                        time.sleep(delay)
                    else:
                        print(f"  ❌ All {config.max_attempts} attempts failed")
            
            raise last_exception
        
        return wrapper
    return decorator


class RetryContext:
    """
    Context manager for retry logic when decorators aren't convenient.
    
    Usage:
        async with RetryContext(config) as retry:
            result = await retry.execute(async_func, arg1, arg2)
    """
    
    def __init__(self, config: RetryConfig = None):
        self.config = config or RetryConfig()
        self.attempt = 0
        self.last_exception = None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute a function with retry logic."""
        for attempt in range(self.config.max_attempts):
            self.attempt = attempt
            try:
                return await func(*args, **kwargs)
            except self.config.retry_exceptions as e:
                self.last_exception = e
                
                if attempt < self.config.max_attempts - 1:
                    delay = calculate_delay(attempt, self.config)
                    await asyncio.sleep(delay)
        
        raise self.last_exception


# Default config for common use cases
DEFAULT_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    base_delay=2.0,
    max_delay=30.0,
    exponential_factor=2.0
)

AGGRESSIVE_RETRY_CONFIG = RetryConfig(
    max_attempts=5,
    base_delay=1.0,
    max_delay=60.0,
    exponential_factor=2.0
)
