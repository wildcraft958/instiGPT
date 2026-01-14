import asyncio
import json
import os
from typing import List, Dict, Any
from datetime import datetime

from insti_scraper.scrapers.list_scraper import ListScraper
from insti_scraper.scrapers.detail_scraper import DetailScraper
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

    async def run(self, start_url: str, discovery_only: bool = False, resume_file: str = None) -> List[Dict]:
        """
        Run the end-to-end pipeline.
        
        Args:
            start_url: URL to start discovery from
            discovery_only: Stop after discovery
            resume_file: Path to existing JSON to skip Phase 1 and go to Phase 2
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
            profiles = await self.list_scraper.scrape_list_pages(start_url)
            
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
        print("-" * 50)
        print(f"Final Stats:")
        print(f"  Total Profiles: {len(data)}")
        print(f"  📧 Emails: {emails} ({emails/len(data) if data else 0:.1%})")
        print(f"  🔬 Interests: {interests} ({interests/len(data) if data else 0:.1%})")
