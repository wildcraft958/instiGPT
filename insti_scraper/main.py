import asyncio
import argparse
import sys
import logging
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from sqlmodel import select, Session

from insti_scraper.core.config import settings
from insti_scraper.core.database import create_db_and_tables, engine, get_session
from insti_scraper.core.cost_tracker import cost_tracker
from insti_scraper.domain.models import University, Department, Professor
from insti_scraper.services.discovery_service import DiscoveryService
from insti_scraper.services.extraction_service import ExtractionService
from insti_scraper.services.enrichment_service import EnrichmentService

# Initialize rich console
console = Console()
logger = logging.getLogger(__name__)

def setup_app():
    settings.setup_logging()
    create_db_and_tables()

async def run_scrape_flow(url: str, enrich: bool = True):
    """
    Main orchestration flow for scraping a university.
    """
    console.print(Panel(f"[bold blue]🚀 Insti-Scraper Professional[/bold blue]\nTarget: {url}", border_style="blue"))
    
    discovery_service = DiscoveryService()
    extraction_service = ExtractionService()
    enrichment_service = EnrichmentService()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True
    ) as progress:
        
        # 1. Discovery Phase
        task_id = progress.add_task("[cyan]🔍 Phase 1: Discovery - Auto-detecting faculty pages...", total=None)
        discovered_pages = await discovery_service.discover_faculty_pages(url, max_depth=2, max_pages=30)
        
        if not discovered_pages:
            progress.stop()
            console.print("[bold red]❌ No faculty pages found.[/bold red]")
            return

        progress.update(task_id, completed=True)
        console.print(f"   ✅ Found [green]{len(discovered_pages)}[/green] potential directories.")
        
        # 2. Extraction Phase
        task_id = progress.add_task(f"[cyan]⛏️ Phase 2: Extraction - Processing {len(discovered_pages)} pages...", total=len(discovered_pages))
        
        total_extracted = 0
        new_professors = []
        
        for i, page in enumerate(discovered_pages):
            progress.update(task_id, description=f"[cyan]Processing {page.url}...")
            
            # TODO: Fetch content properly (ExtractionService should handle fetching or take content)
            # For now, let's assume ExtractionService handles fetching implicitly or we need a fetcher here.
            # Using crawl4ai locally here to fetch content for extraction service
            from crawl4ai import AsyncWebCrawler
            
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(page.url)
                if result.success:
                    professors = await extraction_service.extract_with_fallback(page.url, result.html)
                    
                    if professors:
                        console.print(f"      📄 {page.url}: Found [bold green]{len(professors)}[/bold green] profiles")
                        for prof in professors:
                            prof.website_url = url # Hacky link to 'university' context
                            new_professors.append(prof)
                        total_extracted += len(professors)
                    else:
                        console.print(f"      ⚪ {page.url}: No profiles found (filtered/empty)")
            
            progress.advance(task_id)

        # 3. Persistence Phase
        task_id = progress.add_task("[cyan]💾 Phase 3: Persistence - Saving to database...", total=None)
        
        with Session(engine) as session:
            # Create University if not exists
            uni_name = discovery_service._extract_university_name(url) # Accessing internal helper
            uni = session.exec(select(University).where(University.name == uni_name)).first()
            if not uni:
                uni = University(name=uni_name, website=url)
                session.add(uni)
                session.commit()
                session.refresh(uni)
            
            # Create Default Department
            dept = session.exec(select(Department).where(Department.name == "General", Department.university_id == uni.id)).first()
            if not dept:
                dept = Department(name="General", university_id=uni.id)
                session.add(dept)
                session.commit()
                session.refresh(dept)
                
            count_new = 0
            for prof in new_professors:
                # Check duplication
                existing = session.exec(select(Professor).where(Professor.profile_url == prof.profile_url)).first()
                if not existing:
                    prof.department_id = dept.id
                    session.add(prof)
                    count_new += 1
            
            session.commit()
        
        progress.update(task_id, completed=True)
        console.print(f"   ✅ Saved [green]{count_new}[/green] new profiles to Database.")
        
        # 4. Enrichment Phase
        if enrich and count_new > 0 and new_professors:
            task_id = progress.add_task(f"[cyan]🧠 Phase 4: Enrichment - Querying Google Scholar for {min(5, len(new_professors))} profiles...", total=None)
            
            # Only enrich a few for demo to save time/rate limits
            to_enrich = new_professors[:5] 
            
            with Session(engine) as session:
                for prof in to_enrich:
                    # Reload from DB to get ID
                    db_prof = session.exec(select(Professor).where(Professor.profile_url == prof.profile_url)).first()
                    if db_prof:
                        db_prof = await enrichment_service.enrich_professor(db_prof)
                        session.add(db_prof)
                session.commit()
                
            progress.update(task_id, completed=True)
            console.print("   ✅ Enrichment complete.")

    # Cost Summary
    cost_tracker.print_summary()

def list_professors_command():
    with Session(engine) as session:
        professors = session.exec(select(Professor)).all()
        
        table = Table(title="🎓 Professor Database")
        table.add_column("Name", style="cyan")
        table.add_column("Title")
        table.add_column("Department")
        table.add_column("Scholar", justify="center")
        
        for p in professors:
            scholar_mark = "✅" if p.google_scholar_id else "❌"
            dept_name = p.department.name if p.department else "General"
            table.add_row(p.name, p.title or "-", dept_name, scholar_mark)
            
        console.print(table)
        console.print(f"\nTotal Professors: [bold]{len(professors)}[/bold]")

def main():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    parser = argparse.ArgumentParser(description="Insti-Scraper Professional")
    subparsers = parser.add_subparsers(dest="command")
    
    # Scrape Command
    scrape_parser = subparsers.add_parser("scrape", help="Scrape a university")
    scrape_parser.add_argument("url", help="University URL")
    scrape_parser.add_argument("--no-enrich", action="store_true", help="Skip Google Scholar enrichment")
    
    # List Command
    list_parser = subparsers.add_parser("list", help="List scraped professors")
    
    args = parser.parse_args()
    
    setup_app()
    
    if args.command == "scrape":
        asyncio.run(run_scrape_flow(args.url, enrich=not args.no_enrich))
    elif args.command == "list":
        list_professors_command()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
