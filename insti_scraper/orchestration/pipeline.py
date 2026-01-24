import asyncio
import json
import os
from typing import List, Dict, Any
from datetime import datetime

from insti_scraper.scrapers.list_scraper import ListScraper
from insti_scraper.scrapers.detail_scraper import DetailScraper
from insti_scraper.scrapers.google_scholar_scraper import GoogleScholarScraper
from insti_scraper.core.config import settings

class ScrapingPipeline:
    """
    Orchestrates the full scraping workflow:
    Phase 1 (Discovery) -> Phase 2 (Detail Extraction)
    """
    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.list_scraper = ListScraper()
        self.detail_scraper = DetailScraper()
        self.scholar_scraper = GoogleScholarScraper()

    async def run(self, start_url: str, discovery_only: bool = False, resume_file: str = None, max_depth: int = 20) -> List[Dict]:
        """
        Run the end-to-end pipeline.
        
        Args:
            start_url: URL to start discovery from
            discovery_only: Stop after discovery
            resume_file: Path to existing JSON to skip Phase 1 and go to Phase 2
            max_depth: Maximum number of directory pages to visit
        """
        print(f"🚀 Starting Scraping Pipeline")
        print(f"   URL: {start_url}")
        print(f"   Output Dir: {self.output_dir}")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        profiles = []
        
        # --- PHASE 1: DISCOVERY ---
        if resume_file and os.path.exists(resume_file):
             print(f"📂 Resuming from {resume_file} (Skipping Phase 1)")
             with open(resume_file, 'r') as f:
                 profiles = json.load(f)
        else:
            # Recursive Discovery Loop
            queue = [start_url]
            visited = set()
            queue = [start_url]
            visited = set()
            max_discovery_depth = max_depth  # Use configured limit
            pages_visited = 0
            pages_visited = 0

            print(f"🕷️ Starting Recursive Discovery Loop...")
            
            while queue and pages_visited < max_discovery_depth:
                current_url = queue.pop(0)
                if current_url in visited:
                    continue
                
                visited.add(current_url)
                pages_visited += 1
                
                print(f"\n🔗 Processing URL [{pages_visited}/{max_discovery_depth}]: {current_url}")
                print(f"   Queue size: {len(queue)}")
                
                try:
                    # Scrape the page (returns either profiles OR discovery links)
                    results = await self.list_scraper.scrape_list_pages(current_url)
                    
                    found_links = 0
                    found_profiles = 0
                    
                    for item in results:
                        if item.get("type") == "discovery_link":
                            new_url = item.get("url")
                            if new_url and new_url not in visited and new_url not in queue:
                                queue.append(new_url)
                                found_links += 1
                        else:
                            # It's a profile
                            profiles.append(item)
                            found_profiles += 1
                    
                    print(f"   -> Found {found_links} new sub-directories and {found_profiles} profiles.")
                    
                except Exception as e:
                    print(f"   ❌ Error processing {current_url}: {e}")

            # Save Phase 1 results
            p1_file = os.path.join(self.output_dir, f"profiles_list_{timestamp}.json")
            self._save_json(profiles, p1_file)
            print(f"💾 Phase 1 complete. Found {len(profiles)} profiles. Saved to {p1_file}")
            
        if not profiles:
            print("❌ No profiles found. Aborting.")
            return []

        if discovery_only:
            return profiles

        # --- PHASE 2: DETAILS ---
        print(f"\n🚀 Phase 2: Enrichment (Target: {len(profiles)} profiles)")
        
        # Setup incremental saving callback
        p2_file = os.path.join(self.output_dir, f"profiles_detailed_{timestamp}.json")
        
        async def save_progress(current_data: List[Dict]):
            self._save_json(current_data, p2_file)
            print(f"  💾 Saved progress ({len(current_data)}/{len(profiles)})")

        final_data = await self.detail_scraper.process_batch(profiles, progress_callback=save_progress)
        
        # --- PHASE 3: GOOGLE SCHOLAR LINKING ---
        print(f"\n🚀 Phase 3: Google Scholar Linking")
        enriched_data = []
        
        # Use asyncio.gather for concurrent processing (semaphored)
        # We start small to avoid rate limiting
        semaphore = asyncio.Semaphore(5)
        
        async def enrich_with_limit(p):
            async with semaphore:
                try:
                    return await self.scholar_scraper.enrich_profile(p)
                except Exception as e:
                   # logger.error(f"Error enriching {p.get('name')}: {e}")
                   return p

        tasks = [enrich_with_limit(p) for p in final_data]
        enriched_data = await asyncio.gather(*tasks)
        
        final_data = enriched_data

        # Final Save
        self._save_json(final_data, p2_file)
        print(f"🎉 Pipeline Complete! Final data saved to {p2_file}")
        
        self._print_stats(final_data)
        return final_data

    def _save_json(self, data: Any, filepath: str):
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    def _print_stats(self, data: List[Dict]):
        emails = len([p for p in data if p.get('email')])
        interests = len([p for p in data if p.get('research_interests')])
        scholar = len([p for p in data if p.get('google_scholar_url')])
        print("-" * 50)
        print(f"Final Stats:")
        print(f"  Total Profiles: {len(data)}")
        print(f"  📧 Emails: {emails} ({emails/len(data) if data else 0:.1%})")
        print(f"  🔬 Interests: {interests} ({interests/len(data) if data else 0:.1%})")
        print(f"  🎓 Scholar: {scholar} ({scholar/len(data) if data else 0:.1%})")
