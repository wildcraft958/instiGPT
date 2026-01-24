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
from insti_scraper.database.database import create_db_and_tables, engine, get_session
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
        new_professor_ids = []
        count_new = 0
        
        # Optimized: Reuse crawler session for all pages
        from crawl4ai import AsyncWebCrawler
        
        async with AsyncWebCrawler() as crawler:
            for i, page in enumerate(discovered_pages):
                progress.update(task_id, description=f"[cyan]Processing {page.url}...")
                
                # Fetch content using the shared crawler session
                result = await crawler.arun(page.url)
                
                if result.success:
                    # Extraction Service now handles the content parsing
                    professors, extracted_dept_name = await extraction_service.extract_with_fallback(page.url, result.html)
                    
                    if professors:
                        console.print(f"      📄 {page.url}: Found [bold green]{len(professors)}[/bold green] profiles in '{extracted_dept_name}'")
                        
                        # Store context for persistence step
                        for prof in professors:
                            prof.website_url = url
                            
                        # IMMEDIATE PERSISTENCE (Moved from Phase 3 to here to keep Dept context)
                        with Session(engine) as session:
                            uni_name = discovery_service._extract_university_name(url)
                            uni = session.exec(select(University).where(University.name == uni_name)).first()
                            if not uni:
                                uni = University(name=uni_name, website=url)
                                session.add(uni)
                                session.commit()
                                session.refresh(uni)
                            
                            dept_target_name = extracted_dept_name if extracted_dept_name and extracted_dept_name != "General" else "General"
                            
                            dept = session.exec(select(Department).where(Department.name == dept_target_name, Department.university_id == uni.id)).first()
                            if not dept:
                                dept = Department(name=dept_target_name, university_id=uni.id, url=page.url)
                                session.add(dept)
                                session.commit()
                                session.refresh(dept)
                                
                            for prof in professors:
                                statement = select(Professor).where(
                                    Professor.name == prof.name,
                                    Professor.department_id == dept.id
                                )
                                existing = session.exec(statement).first()
                                
                                if not existing:
                                    prof.department_id = dept.id
                                    session.add(prof)
                                    session.flush() # Force ID generation
                                    count_new += 1
                                    new_professor_ids.append(prof.id)
                                    logger.info(f"   [DB] Added: {prof.name} ({dept_target_name})")
                                else:
                                    # Update existing with rich data if available
                                    if prof.research_interests: existing.research_interests = prof.research_interests
                                    if prof.publication_summary: existing.publication_summary = prof.publication_summary
                                    if prof.education: existing.education = prof.education
                                    session.add(existing)
                                    
                            session.commit()
                            
                    else:
                        console.print(f"      ⚪ {page.url}: No profiles found (filtered/empty)")
                
                progress.advance(task_id)

        # 3. Persistence Phase (NOW HANDLED INCREMENTALLY ABOVE)
        # We keep this block just for the final log message
        console.print(f"   ✅ Saved [green]{count_new}[/green] new/updated profiles to Database.")
        
        # 4. Enrichment Phase
        if enrich and new_professor_ids:
            task_id = progress.add_task(f"[cyan]🧠 Phase 4: Enrichment - Querying Google Scholar for {min(5, len(new_professor_ids))} profiles...", total=None)
            
            # Only enrich a few for demo to save time/rate limits
            to_enrich_ids = new_professor_ids[:5] 
            
            # Use shared crawler session for enrichment too
            async with AsyncWebCrawler() as crawler:
                with Session(engine, expire_on_commit=False) as session:
                    for p_id in to_enrich_ids:
                        # Reload from DB within active session
                        db_prof = session.get(Professor, p_id)
                        if db_prof:
                             # Eager load department name for logging/search query
                            dept_name = db_prof.department.name if db_prof.department else "General"
                            
                            logger.info(f"   [Enrich] Enriching {db_prof.name}...")
                            db_prof = await enrichment_service.enrich_professor(db_prof, crawler)
                            session.add(db_prof)
                            session.commit() # Commit after each to save progress
                
            progress.update(task_id, completed=True)
            console.print("   ✅ Enrichment complete.")

    # Cost Summary
    cost_tracker.print_summary()

def list_professors_command():
    with Session(engine) as session:
        professors = session.exec(select(Professor)).all()
        
        table = Table(title="🎓 Professor Database", show_lines=True)
        table.add_column("University", style="magenta")
        table.add_column("Department", style="cyan")
        table.add_column("Name", style="bold white")
        table.add_column("Interests", max_width=30, style="dim")
        table.add_column("H-Index", justify="right", style="green")
        table.add_column("Citations", justify="right", style="green")
        
        for p in professors:
            # Join interests if list
            interests = ", ".join(p.research_interests[:3]) if p.research_interests else "-"
            uni_name = p.department.university.name if p.department and p.department.university else "?"
            dept_name = p.department.name if p.department else "General"
            
            table.add_row(
                uni_name, 
                dept_name, 
                p.name, 
                interests, 
                str(p.h_index), 
                str(p.total_citations)
            )
            
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
