import logging
import re
from typing import Optional
from ddgs import DDGS
import httpx
from bs4 import BeautifulSoup

from insti_scraper.domain.models import Professor
from insti_scraper.core.cost_tracker import cost_tracker
from insti_scraper.core.config import settings

logger = logging.getLogger(__name__)

class EnrichmentService:
    def __init__(self):
        self.ddgs = DDGS()

    async def enrich_professor(self, professor: Professor, crawler=None) -> Professor: # crawler unused but kept for compatibility
        """
        Enrich a professor with Google Scholar metrics using lightweight HTTP scraping.
        Adopts the robust approach from google_scholar_scraper.ipynb
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
            
            # 2. Extract metrics using lightweight HTTP (Adopted from notebook)
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                
                async with httpx.AsyncClient() as client:
                    response = await client.get(scholar_url, headers=headers, follow_redirects=True)
                    
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        
                        # A. Stats (Citations, H-index) in 'td.gsc_rsb_std'
                        # Indices: 0=Citations (All), 1=Citations (Since), 2=H-index (All), ...
                        stats_table = soup.find_all("td", class_="gsc_rsb_std")
                        
                        if stats_table and len(stats_table) >= 3:
                            # Note: The table has 2 columns values per row (All, Since). 
                            # But findAll returns the td cells linearly.
                            # Row 1 (Citations): td[0], td[1]
                            # Row 2 (h-index): td[2], td[3]
                            professor.total_citations = int(stats_table[0].text)
                            professor.h_index = int(stats_table[2].text)
                            
                            logger.info(f"   [Scholar] Extracted: H-Index={professor.h_index}, Citations={professor.total_citations}")
                        else:
                            logger.warning(f"   [Scholar] Stats table not found or incomplete.")

                        # B. Research Interests (fields) in 'a.gsc_prf_inta'
                        interests_tags = soup.find_all("a", class_="gsc_prf_inta")
                        if interests_tags:
                            new_interests = [a.text for a in interests_tags]
                            # Append unique ones
                            current_set = set(professor.research_interests)
                            for interest in new_interests:
                                if interest not in current_set:
                                    professor.research_interests.append(interest)

                        # C. Top Papers from 'tr.gsc_a_tr' -> 'a.gsc_a_at'
                        paper_rows = soup.find_all("tr", class_="gsc_a_tr")
                        papers = []
                        for row in paper_rows:
                            title_tag = row.find("a", class_="gsc_a_at")
                            if title_tag:
                                papers.append(title_tag.text)
                        
                        professor.top_papers = papers[:5] # Store top 5 papers

                    else:
                         logger.warning(f"   [Scholar] Failed to fetch page, status code: {response.status_code}")

            except Exception as scrape_err:
                logger.warning(f"   [Scholar] Failed to scrape metrics: {scrape_err}")
                
            return professor
            
        except Exception as e:
            logger.error(f"Error enriching {professor.name}: {e}")
            return professor

    def _extract_user_id(self, url: str) -> Optional[str]:
        match = re.search(r'user=([\w-]+)', url)
        return match.group(1) if match else None
