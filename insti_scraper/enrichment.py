"""
Google Scholar enrichment for faculty profiles.
"""

import re
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from .models import Professor

logger = logging.getLogger(__name__)


class ScholarEnricher:
    """Enriches professor profiles with Google Scholar data."""
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    async def enrich(self, professor: Professor) -> Professor:
        """
        Enrich a professor with Google Scholar metrics.
        
        Args:
            professor: Professor to enrich
        
        Returns:
            Professor with Scholar data (h-index, citations, papers)
        """
        if not professor.name:
            return professor
        
        dept_name = professor.department.name if professor.department else ""
        logger.info(f"🎓 Searching Scholar: {professor.name}")
        
        try:
            # Search for profile
            scholar_url = await self._find_profile(professor.name, dept_name)
            
            if not scholar_url:
                logger.info(f"   No Scholar profile found")
                return professor
            
            professor.google_scholar_id = self._extract_user_id(scholar_url)
            
            # Scrape metrics
            await self._scrape_metrics(professor, scholar_url)
            
            logger.info(f"   ✅ H-Index={professor.h_index}, Citations={professor.total_citations}")
            return professor
            
        except Exception as e:
            logger.warning(f"   Scholar enrichment failed: {e}")
            return professor
    
    async def _find_profile(self, name: str, department: str) -> Optional[str]:
        """Find Google Scholar profile URL."""
        try:
            from ddgs import DDGS
            
            query = f'{name} {department} "Google Scholar"'
            
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))
            
            for r in results:
                href = r.get('href', '')
                if "scholar.google" in href and "citations?user=" in href:
                    return href
            
            return None
            
        except ImportError:
            logger.debug("ddgs not available for Scholar search")
            return None
        except Exception as e:
            logger.debug(f"Scholar search failed: {e}")
            return None
    
    async def _scrape_metrics(self, professor: Professor, scholar_url: str):
        """Scrape metrics from Scholar profile page."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(scholar_url, headers=self.HEADERS, follow_redirects=True)
                
                if response.status_code != 200:
                    return
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Stats table: Citations, H-index
                stats = soup.find_all("td", class_="gsc_rsb_std")
                if stats and len(stats) >= 3:
                    try:
                        professor.total_citations = int(stats[0].text.replace(',', '').strip())
                        professor.h_index = int(stats[2].text.replace(',', '').strip())
                    except ValueError:
                        pass
                
                # Research interests
                interests = soup.find_all("a", class_="gsc_prf_inta")
                if interests:
                    new_interests = [a.text for a in interests]
                    current = set(professor.research_interests)
                    for interest in new_interests:
                        if interest not in current:
                            professor.research_interests.append(interest)
                
                # Top papers
                paper_rows = soup.find_all("tr", class_="gsc_a_tr")
                papers = []
                for row in paper_rows:
                    title_tag = row.find("a", class_="gsc_a_at")
                    if title_tag:
                        papers.append(title_tag.text)
                
                professor.top_papers = papers[:5]
                
        except Exception as e:
            logger.debug(f"Scholar scrape error: {e}")
    
    def _extract_user_id(self, url: str) -> Optional[str]:
        """Extract Scholar user ID from URL."""
        match = re.search(r'user=([\w-]+)', url)
        return match.group(1) if match else None


async def enrich_professor(professor: Professor) -> Professor:
    """Convenience function for enrichment."""
    enricher = ScholarEnricher()
    return await enricher.enrich(professor)
