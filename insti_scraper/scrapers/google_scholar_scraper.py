import json
import os
import asyncio
import httpx
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from ddgs import DDGS
from litellm import completion
from insti_scraper.core.config import settings
from insti_scraper.core.logger import logger

class GoogleScholarScraper:
    """
    Handles Phase 3: Linking faculty profiles to Google Scholar.
    Fetches H-index, Citations, and recent papers asynchronously.
    """
    def __init__(self, model_name: str = None):
        self.model_name = model_name or settings.get_model_for_task("scholar_linking")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    async def enrich_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enriches a profile with Google Scholar data.
        """
        prof_name = profile.get("name")
        university = profile.get("university") or profile.get("affiliation") or "Institute"
        department = profile.get("department") or profile.get("title") or ""

        if not prof_name:
            return profile

        logger.info(f"  🔍 Searching Scholar for: {prof_name}...")
        
        # 1. Search for candidates using DuckDuckGo
        # DDGS is synchronous, so we run it in a thread to avoid blocking the loop
        query = f"google scholar {prof_name} {university} {department}"
        candidates = await asyncio.to_thread(self._search_ddg, query)

        if not candidates:
            logger.debug(f"    ⚠️ No candidates found for {prof_name}.")
            return profile

        # 2. Use LLM to pick the best match
        # Litellm completion is sync (web request), run in thread if needed, 
        # but usually fast enough. For strict async, wrapping it is better.
        scholar_url = await asyncio.to_thread(
            self._select_best_candidate, 
            prof_name, university, department, candidates
        )
        
        if not scholar_url:
            return profile

        logger.info(f"    ✅ Match: {scholar_url}")

        # 3. Scrape the profile page asynchronously
        scholar_data = await self._scrape_scholar_page(scholar_url)
        if scholar_data:
            profile.update(scholar_data)
            profile['google_scholar_url'] = scholar_url
            logger.info(f"    📊 Citations: {scholar_data.get('total_citations')}, H-index: {scholar_data.get('h_index')}")
        
        return profile

    def _search_ddg(self, query: str) -> List[str]:
        """Sync wrapper for DDGS search."""
        candidates = []
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
                for r in results:
                    url = r.get('href', '')
                    if "scholar.google" in url and "user=" in url:
                        candidates.append(url)
        except Exception as e:
            logger.warning(f"    ⚠️ DDGS Search failed: {e}")
        return candidates

    def _select_best_candidate(self, name: str, uni: str, dept: str, candidates: List[str]) -> Optional[str]:
        """Use LLM to select the correct URL from candidates."""
        if not candidates:
            return None
            
        if len(candidates) == 1:
            return candidates[0]

        candidates_str = "\n".join(candidates)
        prompt = f"""
        Pick the official Google Scholar profile for:
        Name: {name}
        University: {uni}
        Department: {dept}

        Candidates:
        {candidates_str}

        Return ONLY the raw URL of the best match. If none look correct, return 'None'.
        """
        
        try:
            response = completion(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                api_base=os.getenv("OLLAMA_BASE_URL") if "ollama" in self.model_name else None
            )
            result = response.choices[0].message.content.strip()
            if "http" in result:
                import re
                urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', result)
                if urls:
                    return urls[0]
            return None if "None" in result else result
        except Exception as e:
            logger.error(f"    ❌ LLM Selection failed: {e}")
            return candidates[0]

    async def _scrape_scholar_page(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape metrics from the Google Scholar profile page using httpx."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                response = await client.get(url, headers=self.headers)
            
            if response.status_code != 200:
                logger.warning(f"    ❌ Failed to fetch page: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            interests = [a.text for a in soup.find_all("a", class_="gsc_prf_inta")]
            
            stats_table = soup.find_all("td", class_="gsc_rsb_std")
            citations_all = stats_table[0].text if stats_table and len(stats_table) > 0 else "N/A"
            h_index_all = stats_table[2].text if stats_table and len(stats_table) > 2 else "N/A"
            
            papers = []
            paper_rows = soup.find_all("tr", class_="gsc_a_tr")
            for row in paper_rows[:5]:
                title_elem = row.find("a", class_="gsc_a_at")
                if title_elem:
                    papers.append(title_elem.text)
            
            return {
                "research_fields": interests,
                "total_citations": citations_all,
                "h_index": h_index_all,
                "paper_titles": papers
            }
            
        except Exception as e:
            logger.error(f"    ❌ Scrape failed: {e}")
            return None
