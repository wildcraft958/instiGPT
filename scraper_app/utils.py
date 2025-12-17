"""
Utility functions for the web scraper.
"""
import logging
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

try:
    from markdownify import markdownify as md
except ImportError:
    md = None

from .config import settings

logger = logging.getLogger(__name__)


def setup_logging(debug: bool = False, log_file: Optional[str] = None) -> logging.Logger:
    """
    Configure logging for the application.
    
    Args:
        debug: Enable debug level logging
        log_file: Optional path to log file
    
    Returns:
        Configured logger
    """
    level = logging.DEBUG if debug else logging.INFO
    
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    
    return logging.getLogger(__name__)


def html_to_markdown(html: str, strip_tags: Optional[list] = None) -> str:
    """
    Convert HTML to clean Markdown for LLM consumption.
    Reduces token usage and improves structural understanding.
    
    Args:
        html: Raw HTML content
        strip_tags: List of tag names to remove (default: script, style, nav, footer)
    
    Returns:
        Clean markdown string
    """
    if strip_tags is None:
        strip_tags = ['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']
    
    # Parse HTML
    soup = BeautifulSoup(html, 'html.parser')
    
    # Remove unwanted tags
    for tag in strip_tags:
        for element in soup.find_all(tag):
            element.decompose()
    
    # Try using markdownify if available
    if md is not None:
        try:
            markdown = md(str(soup), heading_style="ATX", strip=['img'])
            # Clean up excessive whitespace
            markdown = re.sub(r'\n{3,}', '\n\n', markdown)
            markdown = re.sub(r' {2,}', ' ', markdown)
            return markdown.strip()
        except Exception as e:
            logger.warning(f"Markdownify failed, falling back to text: {e}")
    
    # Fallback: extract main content as plain text
    main_content = soup.find('main') or soup.find('article') or soup.find('body') or soup
    return main_content.get_text(separator='\n', strip=True)


def ensure_absolute_url(base_url: str, relative_url: str) -> str:
    """
    Ensure a URL is absolute by joining with base if necessary.
    
    Args:
        base_url: The base URL (current page)
        relative_url: The URL to resolve (may be relative or absolute)
    
    Returns:
        Absolute URL
    """
    if not relative_url:
        return base_url
    
    parsed = urlparse(relative_url)
    if parsed.scheme:
        # Already absolute
        return relative_url
    
    return urljoin(base_url, relative_url)


def check_robots_txt(url: str, user_agent: str = "*") -> bool:
    """
    Check if crawling is allowed for the given URL per robots.txt.
    
    Args:
        url: URL to check
        user_agent: User agent string to check against
    
    Returns:
        True if crawling is allowed, False otherwise
    """
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        
        return rp.can_fetch(user_agent, url)
    except Exception as e:
        logger.warning(f"Could not check robots.txt: {e}. Assuming allowed.")
        return True


def sanitize_filename(name: str, max_length: int = 100) -> str:
    """
    Sanitize a string for use as a filename.
    
    Args:
        name: Original string
        max_length: Maximum length for filename
    
    Returns:
        Sanitized filename
    """
    # Remove or replace problematic characters
    safe_name = re.sub(r'[^\w\s-]', '', name)
    safe_name = re.sub(r'[\s]+', '_', safe_name)
    return safe_name[:max_length].strip('_')


def extract_json_from_response(text: str) -> Optional[dict]:
    """
    Extract a JSON object from a text response (handles LLM chatter around JSON).
    
    Args:
        text: Text response that may contain JSON
    
    Returns:
        Parsed JSON dict or None if not found
    """
    import json
    
    # Remove markdown code blocks
    text = text.replace("```json", "").replace("```", "")
    
    # Find JSON object bounds
    json_start = text.find('{')
    json_end = text.rfind('}') + 1
    
    if json_start == -1 or json_end == 0:
        # Try finding JSON array
        json_start = text.find('[')
        json_end = text.rfind(']') + 1
    
    if json_start == -1 or json_end == 0:
        logger.error("No JSON object found in response")
        return None
    
    json_str = text[json_start:json_end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        logger.debug(f"Content: {json_str[:500]}")
        return None


def create_output_dirs() -> dict:
    """
    Create output directories for scraped data.
    
    Returns:
        Dict with paths to created directories
    """
    dirs = {
        'output': Path(settings.OUTPUT_DIR),
        'html_logs': Path(settings.HTML_LOGS_DIR),
        'screenshots': Path(settings.SCREENSHOTS_DIR),
    }
    
    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)
    
    return {k: str(v) for k, v in dirs.items()}
