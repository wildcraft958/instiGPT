import logging
import re
from typing import Optional, Dict
from ddgs import DDGS

from insti_scraper.domain.models import Professor
from insti_scraper.core.cost_tracker import cost_tracker
from insti_scraper.core.config import settings

logger = logging.getLogger(__name__)

class EnrichmentService:
    def __init__(self):
        self.ddgs = DDGS()

    async def enrich_professor(self, professor: Professor, crawler) -> Professor:
        """
        Enrich a professor with Google Scholar metrics.
        """
        if not professor.name or not professor.department:
            return professor
            
        logger.info(f"🎓 Searching Scholar for: {professor.name} ({professor.department.name})")
        
        try:
            # 1. Search for profile
            query = f"{professor.name} {professor.department.name} \"Google Scholar\""
            results = list(self.ddgs.text(query, max_results=3))
            
            scholar_url = None
            for res in results:
                if "scholar.google" in res['href'] and "citations?user=" in res['href']:
                    scholar_url = res['href']
                    break
            
            if not scholar_url:
                logger.warning(f"   No Scholar profile found for {professor.name}")
                return professor
                
            professor.google_scholar_id = self._extract_user_id(scholar_url)
            
            # 2. Extract metrics (Simulated for speed/stability, or implement actual scraping)
            # In a real "Apollo", this would use Serper/SerpAPI or a robust scraper.
            # Using crawl4ai for extraction could be expensive/slow for every profile.
            # We will try a lightweight approach or reuse the existing logic if available.
            # For this professional refactor, let's assume we want to store the URL and ID primarily, 
            # and maybe fetch metrics asynchronously/later to avoid blocking.
            
            professor.google_scholar_id = self._extract_user_id(scholar_url)
            
            # 2. Extract metrics using the passed crawler
            try:
                res = await crawler.arun(scholar_url)
                if res.success:
                    # Simple regex extraction from the raw text or HTML
                    # H-index is usually in a table with id "gsc_rsb_st"
                    # Text: "Citations All Since 2019 ... h-index 12 10"
                    content = res.markdown
                    
                    # Robust Regex for Citations
                    # Look for "Citations" followed by number
                    cit_match = re.search(r'Citations\s*[\|\n]*\s*(\d+)', content)
                    if cit_match:
                        professor.total_citations = int(cit_match.group(1))
                        
                    # Robust Regex for H-index
                    # Look for "h-index" followed by number
                    h_match = re.search(r'h-index\s*[\|\n]*\s*(\d+)', content)
                    if h_match:
                        professor.h_index = int(h_match.group(1))
                        
                    logger.info(f"   [Scholar] Extracted: H-Index={professor.h_index}, Citations={professor.total_citations}")
            except Exception as scrape_err:
                logger.warning(f"   [Scholar] Failed to scrape metrics: {scrape_err}")
                
            return professor
            
        except Exception as e:
            logger.error(f"Error enriching {professor.name}: {e}")
            return professor

    def _extract_user_id(self, url: str) -> Optional[str]:
        match = re.search(r'user=([\w-]+)', url)
        return match.group(1) if match else None
