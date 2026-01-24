from duckduckgo_search import DDGS
from typing import Optional, List
import asyncio
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class SearchNavigator:
    """
    Navigates to faculty directories using external search engines (DuckDuckGo)
    when internal site navigation fails or is ambiguous.
    """
    def __init__(self):
        self.ddgs = DDGS()

    async def find_faculty_directory(self, domain: str, context_keyword: str) -> Optional[str]:
        """
        Searches for a faculty directory for a specific context (e.g. "Aerospace Engineering")
        within a specific university domain.
        
        Args:
            domain: University domain (e.g., "iitkgp.ac.in")
            context_keyword: Department or Unit name (e.g., "Aerospace Engineering")
            
        Returns:
            Best matching URL or None
        """
        queries = [
            f"site:{domain} {context_keyword} faculty list directory",
            f"site:{domain} {context_keyword} faculty list",
            f"site:{domain} {context_keyword} faculty",
            f"{domain} {context_keyword} faculty" # Relaxed site search
        ]
        
        for query in queries:
            print(f"  🔍 Teleport Search: '{query}'")
            try:
                # Run in executor to avoid blocking async loop since DDGS might be sync or slow
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(None, lambda: list(self.ddgs.text(query, max_results=5)))
                
                if not results:
                    continue
                    
                # Filter results to strictly match domain (sanity check)
                best_url = None
                best_score = -1
                
                for res in results:
                    url = res['href']
                    # Relaxed domain check for the broader query
                    if domain in urlParse(url).netloc: 
                        # Prioritize URLs that look like directories
                        url_lower = url.lower()
                        score = 0
                        if "faculty" in url_lower: score += 2
                        if "people" in url_lower: score += 2
                        if "directory" in url_lower: score += 2
                        if "staff" in url_lower: score += 1
                        
                        if score > best_score:
                            best_score = score
                            best_url = url
                
                if best_url:
                    print(f"    - Found candidate: {best_url} (Score: {best_score})")
                    return best_url
            except Exception as e:
                logger.error(f"Search query '{query}' failed: {e}")
                print(f"    Warning: Search attempt failed: {e}")
                
        print("  ❌ All search attempts exhausted.")
        return None

def urlParse(url):
    return urlparse(url)
