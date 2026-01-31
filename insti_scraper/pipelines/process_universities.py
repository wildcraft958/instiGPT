"""
Batch processing pipeline for processing multiple universities.

Handles Excel input, parallel processing, progress tracking,
and comprehensive error handling.
"""

import asyncio
import logging
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime

import pandas as pd
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn
from rich.table import Table

from insti_scraper.config import console, cost_tracker
from insti_scraper.models import init_database
from insti_scraper.crawler import CrawlerManager, FetchMode
from insti_scraper.discovery import FacultyPageDiscoverer
from insti_scraper.duckduckgo_discovery import DuckDuckGoDiscovery
from insti_scraper.extractors import extract_with_fallback
from insti_scraper.enrichment import enrich_professor
from insti_scraper.database import get_db_manager

logger = logging.getLogger(__name__)


class UniversityProcessor:
    """
    Processes multiple universities in batch.
    
    Features:
    - Excel input/output
    - Parallel processing with rate limiting
    - Progress tracking and checkpoints
    - Comprehensive error handling
    - Statistics reporting
    """
    
    def __init__(
        self,
        max_concurrent: int = 3,
        enable_enrichment: bool = True,
        enable_vision: bool = False,
        checkpoint_interval: int = 10
    ):
        """
        Initialize batch processor.
        
        Args:
            max_concurrent: Max concurrent universities to process
            enable_enrichment: Enable Google Scholar enrichment
            enable_vision: Enable vision-based extraction for failures
            checkpoint_interval: Save progress every N universities
        """
        self.max_concurrent = max_concurrent
        self.enable_enrichment = enable_enrichment
        self.enable_vision = enable_vision
        self.checkpoint_interval = checkpoint_interval
        self.db = get_db_manager()
        
        # Statistics
        self.stats = {
            "total": 0,
            "successful": 0,
            "failed": 0,
            "professors_found": 0,
            "enriched": 0,
            "errors": []
        }
    
    async def process_from_excel(
        self,
        input_file: str,
        output_file: str = None,
        resume: bool = True
    ) -> Dict:
        """
        Process universities from Excel file.
        
        Args:
            input_file: Input Excel file path
            output_file: Output file path (optional, auto-generated if None)
            resume: Resume from last checkpoint if True
        
        Returns:
            Statistics dictionary
        """
        console.print(f"\n[bold blue]📊 Batch Processing: {input_file}[/bold blue]\n")
        
        # Load data
        df = pd.read_excel(input_file)
        self.stats["total"] = len(df)
        
        # Check for required columns
        required_cols = ['Name']
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        # Add processing columns if they don't exist
        for col in ['Status', 'Professors_Count', 'Error_Message', 'Processed_At']:
            if col not in df.columns:
                df[col] = None
        
        # Generate output filename
        if not output_file:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"batch_results_{timestamp}.xlsx"
        
        # Filter unprocessed rows if resuming
        if resume:
            unprocessed = df[df['Status'].isna() | (df['Status'] == 'Failed')]
            start_index = len(df) - len(unprocessed)
            console.print(f"[yellow]Resuming from row {start_index}[/yellow]")
        else:
            unprocessed = df
            start_index = 0
        
        # Initialize database
        init_database()
        
        # Process with progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            
            task = progress.add_task(
                "[cyan]Processing universities...",
                total=len(unprocessed)
            )
            
            # Process in batches with concurrency control
            semaphore = asyncio.Semaphore(self.max_concurrent)
            
            async def process_row(idx, row):
                async with semaphore:
                    result = await self._process_university(row)
                    
                    # Update dataframe
                    actual_idx = idx + start_index
                    df.at[actual_idx, 'Status'] = result['status']
                    df.at[actual_idx, 'Professors_Count'] = result.get('count', 0)
                    df.at[actual_idx, 'Error_Message'] = result.get('error', '')
                    df.at[actual_idx, 'Processed_At'] = datetime.now().isoformat()
                    
                    # Update stats
                    if result['status'] == 'Success':
                        self.stats['successful'] += 1
                        self.stats['professors_found'] += result.get('count', 0)
                    else:
                        self.stats['failed'] += 1
                        self.stats['errors'].append({
                            'university': row['Name'],
                            'error': result.get('error', 'Unknown')
                        })
                    
                    progress.advance(task)
                    
                    # Checkpoint
                    if (idx + 1) % self.checkpoint_interval == 0:
                        df.to_excel(output_file, index=False)
                        progress.console.print(f"   💾 Checkpoint saved at {idx + 1}")
            
            # Process all rows
            tasks = [
                process_row(idx, row)
                for idx, row in unprocessed.iterrows()
            ]
            
            await asyncio.gather(*tasks)
        
        # Final save
        df.to_excel(output_file, index=False)
        
        # Print summary
        self._print_summary(output_file)
        
        return self.stats
    
    async def _process_university(self, row: pd.Series) -> Dict:
        """
        Process a single university.
        
        Args:
            row: DataFrame row with university data
        
        Returns:
            Result dictionary
        """
        university_name = row.get('Name', '').strip()
        homepage_url = row.get('University Link', row.get('Uinversity Link', '')).strip()
        
        if not university_name:
            return {"status": "Skipped", "error": "No university name"}
        
        logger.info(f"📚 Processing: {university_name}")
        
        try:
            # Step 1: Discover faculty pages
            if homepage_url and homepage_url.startswith('http'):
                discoverer = FacultyPageDiscoverer()
                discovery_result = await discoverer.discover(homepage_url)
                pages = discovery_result.faculty_pages[:5]  # Top 5 pages
            else:
                # Fallback to DuckDuckGo search
                ddg = DuckDuckGoDiscovery()
                pages = await ddg.discover(university_name, homepage_url)
                pages = pages[:5]
            
            if not pages:
                return {"status": "Failed", "error": "No faculty pages found"}
            
            # Step 2: Extract professors
            total_professors = []
            
            async with CrawlerManager() as crawler:
                for page in pages:
                    try:
                        # Fetch page
                        fetch_result = await crawler.fetch(page.url, FetchMode.HTML)
                        
                        if not fetch_result.ok:
                            continue
                        
                        # Extract
                        extraction = await extract_with_fallback(
                            fetch_result.html,
                            page.url,
                            min_results=3
                        )
                        
                        if extraction.professors:
                            total_professors.extend(extraction.professors)
                            
                            # Save to database
                            self.db.bulk_insert_professors(
                                extraction.professors,
                                university_name,
                                extraction.department_name
                            )
                    
                    except Exception as e:
                        logger.warning(f"   Failed to process {page.url}: {e}")
                        continue
            
            if not total_professors:
                return {"status": "Failed", "error": "No professors extracted"}
            
            # Step 3: Enrichment (optional)
            if self.enable_enrichment:
                enriched_count = 0
                for prof in total_professors[:10]:  # Limit enrichment
                    try:
                        enriched = await enrich_professor(prof)
                        if enriched.google_scholar_id:
                            enriched_count += 1
                    except Exception:
                        pass
                
                self.stats['enriched'] += enriched_count
            
            return {
                "status": "Success",
                "count": len(total_professors),
                "pages_processed": len(pages)
            }
        
        except Exception as e:
            logger.error(f"Error processing {university_name}: {e}")
            return {"status": "Failed", "error": str(e)}
    
    def _print_summary(self, output_file: str):
        """Print processing summary."""
        console.print("\n")
        
        # Summary table
        table = Table(title="📊 Processing Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right", style="bold")
        
        table.add_row("Total Universities", str(self.stats['total']))
        table.add_row("Successful", str(self.stats['successful']), style="green")
        table.add_row("Failed", str(self.stats['failed']), style="red")
        table.add_row("Professors Found", str(self.stats['professors_found']), style="magenta")
        
        if self.enable_enrichment:
            table.add_row("Enriched Profiles", str(self.stats['enriched']), style="yellow")
        
        console.print(table)
        
        # Error summary
        if self.stats['errors']:
            console.print(f"\n[bold red]❌ Errors ({len(self.stats['errors'])}):[/bold red]")
            for err in self.stats['errors'][:10]:  # Show first 10
                console.print(f"   • {err['university']}: {err['error']}")
            
            if len(self.stats['errors']) > 10:
                console.print(f"   ... and {len(self.stats['errors']) - 10} more")
        
        # Cost tracking
        cost_tracker.print_summary()
        
        console.print(f"\n[bold green]✅ Results saved to: {output_file}[/bold green]\n")


async def process_universities_batch(
    input_file: str,
    output_file: str = None,
    max_concurrent: int = 3,
    enable_enrichment: bool = True,
    resume: bool = True
) -> Dict:
    """
    Convenience function for batch processing.
    
    Args:
        input_file: Input Excel file path
        output_file: Output file path (optional)
        max_concurrent: Max concurrent processing
        enable_enrichment: Enable Scholar enrichment
        resume: Resume from checkpoint
    
    Returns:
        Statistics dictionary
    """
    processor = UniversityProcessor(
        max_concurrent=max_concurrent,
        enable_enrichment=enable_enrichment
    )
    
    return await processor.process_from_excel(
        input_file,
        output_file,
        resume
    )
