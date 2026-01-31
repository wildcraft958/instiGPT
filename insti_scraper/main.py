import asyncio
import argparse
import sys
import logging
import json
import os
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from sqlmodel import select, Session

from insti_scraper.core.config import settings
from insti_scraper.data.database import create_db_and_tables, engine, get_session
from insti_scraper.core.cost_tracker import cost_tracker
from insti_scraper.core.rate_limiter import get_rate_limiter
from insti_scraper.core.auto_config import AutoConfig
from insti_scraper.data.models import University, Department, Professor
from insti_scraper.engine.discovery import FacultyPageDiscoverer, DiscoveredPage
from insti_scraper.services.extraction_service import ExtractionService
from insti_scraper.services.enrichment_service import EnrichmentService
from insti_scraper.engine.pagination import extract_with_pagination

# Initialize rich console
console = Console()
logger = logging.getLogger(__name__)

def setup_app():
    settings.setup_logging()
    create_db_and_tables()

async def run_scrape_flow(url: str, enrich: bool = True, direct: bool = False):
    """
    Main orchestration flow for scraping a university.
    
    Args:
        url: University URL (or direct faculty page URL if direct=True)
        enrich: Whether to enrich with Google Scholar
        direct: If True, treat URL as faculty directory (skip discovery)
    """
    mode_label = "Direct Mode" if direct else "Auto-Discovery"
    console.print(Panel(f"[bold blue]🚀 Insti-Scraper Professional[/bold blue]\nTarget: {url}\nMode: {mode_label}", border_style="blue"))
    
    discoverer = FacultyPageDiscoverer()
    extraction_service = ExtractionService()
    enrichment_service = EnrichmentService()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True
    ) as progress:
        
        # 1. Discovery Phase (skip if direct mode)
        if direct:
            # Direct mode: treat URL as a faculty directory
            console.print("   [bold green]📌 Direct Mode[/bold green] - Treating URL as faculty directory")
            discovered_pages = [DiscoveredPage(url=url, score=100, source="direct")]
        else:
            task_id = progress.add_task("[cyan]🔍 Phase 1: Discovery - Auto-detecting faculty pages...", total=None)
            result = await discoverer.discover(url, mode="auto")
            discovered_pages = result.faculty_pages
            progress.update(task_id, completed=True)
        
        if not discovered_pages:
            progress.stop()
            console.print("[bold red]❌ No faculty pages found.[/bold red]")
            return

        console.print(f"   ✅ Found [green]{len(discovered_pages)}[/green] potential directories.")
        
        # 2. Extraction Phase
        task_id = progress.add_task(f"[cyan]⛏️ Phase 2: Extraction - Processing {len(discovered_pages)} pages...", total=len(discovered_pages))
        
        total_extracted = 0
        new_professor_ids = []
        count_new = 0
        gateway_pages = []  # Pages that need deeper crawling
        
        # Optimized: Reuse crawler session for all pages
        from crawl4ai import AsyncWebCrawler
        
        async with AsyncWebCrawler() as crawler:
            rate_limiter = get_rate_limiter()
            
            for i, page in enumerate(discovered_pages):
                await rate_limiter.wait_if_needed(page.url)
                progress.update(task_id, description=f"[cyan]Processing {page.url}...")
                
                # Fetch content using the shared crawler session
                try:
                    result = await crawler.arun(page.url)
                except Exception as e:
                    logger.error(f"      ❌ Crawler error for {page.url}: {e}")
                    continue

                
                if result.success:
                    try:
                        # Extraction Service now handles the content parsing + vision analysis
                        professors, extracted_dept_name = await extraction_service.extract_with_fallback(page.url, result.html)
                        
                        # Handle Null case
                        if extracted_dept_name is None:
                            extracted_dept_name = "General"
                        
                        # Handle special status codes from vision analysis
                        if extracted_dept_name.startswith("BLOCKED:"):
                            block_type = extracted_dept_name.split(":")[1]
                            console.print(f"      🚫 {page.url}: [bold red]BLOCKED[/bold red] ({block_type})")
                            continue
                        
                        if extracted_dept_name == "GATEWAY":
                            console.print(f"      📂 {page.url}: [bold yellow]Department Gateway[/bold yellow] - will crawl links later")
                            gateway_pages.append(page.url)
                            continue
                        
                        if extracted_dept_name == "PROFILE":
                            console.print(f"      👤 {page.url}: Individual profile page, skipping")
                            continue
                        
                        if extracted_dept_name == "PAGINATED":
                            console.print(f"      📄 {page.url}: [bold cyan]Paginated page[/bold cyan] - extracting all pages...")
                            # Use pagination handler for multi-page extraction
                            professors, extracted_dept_name = await extract_with_pagination(
                                page.url, 
                                extraction_service,
                                max_pages=50
                            )
                            console.print(f"      📊 Total from all pages: [bold green]{len(professors)}[/bold green] profiles")
                        
                        if professors:
                            console.print(f"      📄 {page.url}: Found [bold green]{len(professors)}[/bold green] profiles in '{extracted_dept_name}'")
                            
                            # Store context for persistence step
                            for prof in professors:
                                prof.website_url = url
                                
                            # IMMEDIATE PERSISTENCE (Moved from Phase 3 to here to keep Dept context)
                            with Session(engine) as session:
                                uni_name = discoverer._extract_university_name(url)
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
                            
                    except Exception as e:
                        logger.error(f"      ❌ Extraction error for {page.url}: {e}")
                        console.print(f"      ❌ Extraction failed: {e}")
                        continue
                
                progress.advance(task_id)

        # 2.5 Process Gateway Pages (if any were detected)
        if gateway_pages:
            task_id = progress.add_task(f"[yellow]📂 Phase 2.5: Processing {len(gateway_pages)} gateway pages...", total=len(gateway_pages))
            
            for gateway_url in gateway_pages:
                progress.update(task_id, description=f"[yellow]Crawling gateway: {gateway_url}...")
                
                try:
                    # Fetch gateway page and extract department links
                    result = await crawler.arun(gateway_url)
                    if not result.success:
                        continue
                    
                    # Use GatewayPageHandler to extract department links
                    from insti_scraper.engine.page_handlers import GatewayPageHandler
                    handler = GatewayPageHandler()
                    gateway_result = await handler.extract(gateway_url, result.html)
                    
                    # Process each department link found
                    for dept_url in gateway_result.next_pages[:10]:  # Limit to 10 depts
                        if dept_url.startswith('/'):
                            from urllib.parse import urljoin
                            dept_url = urljoin(gateway_url, dept_url)
                        
                        if dept_url in self._seen_urls if hasattr(self, '_seen_urls') else False:
                            continue
                        
                        console.print(f"      🔗 Processing department: {dept_url}")
                        
                        dept_result = await crawler.arun(dept_url)
                        if dept_result.success:
                            professors, dept_name = await extraction_service.extract_with_fallback(
                                dept_url, dept_result.html, skip_vision=True
                            )
                            
                            if professors:
                                console.print(f"         📄 Found {len(professors)} in {dept_name}")
                                
                                # Persist to DB
                                with Session(engine) as session:
                                    uni_name = discoverer._extract_university_name(url)
                                    uni = session.exec(select(University).where(University.name == uni_name)).first()
                                    if uni:
                                        dept = session.exec(select(Department).where(
                                            Department.name == dept_name, 
                                            Department.university_id == uni.id
                                        )).first()
                                        if not dept:
                                            dept = Department(name=dept_name, university_id=uni.id, url=dept_url)
                                            session.add(dept)
                                            session.commit()
                                            session.refresh(dept)
                                        
                                        for prof in professors:
                                            existing = session.exec(
                                                select(Professor).where(Professor.name == prof.name, Professor.department_id == dept.id)
                                            ).first()
                                            if not existing:
                                                prof.department_id = dept.id
                                                session.add(prof)
                                                count_new += 1
                                        session.commit()
                        
                        await rate_limiter.wait_if_needed(dept_url)
                    
                except Exception as e:
                    logger.error(f"   ❌ Gateway processing error: {e}")
                
                progress.advance(task_id)
            
            console.print(f"   ✅ Gateway processing complete - added {count_new} more profiles")

        # 3. Persistence Phase (NOW HANDLED INCREMENTALLY ABOVE)
        # We keep this block just for the final log message
        console.print(f"   ✅ Saved [green]{count_new}[/green] new/updated profiles to Database.")
        
        # 4. Enrichment Phase
        if enrich and new_professor_ids:
            task_id = progress.add_task(f"[cyan]🧠 Phase 4: Enrichment - Querying Google Scholar for {min(5, len(new_professor_ids))} profiles...", total=None)
            
            # Enrich up to 50 profiles (increased from 5)
            to_enrich_ids = new_professor_ids[:50] 
            
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


async def run_discover_flow(url: str, mode: str = "auto"):
    """
    Standalone discovery flow - find faculty pages from any URL.
    """
    console.print(Panel(f"[bold cyan]🔍 Faculty Page Discovery[/bold cyan]\nTarget: {url}\nMode: {mode}", border_style="cyan"))
    
    discoverer = FacultyPageDiscoverer(max_depth=3, max_pages=50)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True
    ) as progress:
        task_id = progress.add_task(f"[cyan]Discovering faculty pages ({mode} mode)...", total=None)
        result = await discoverer.discover(url, mode=mode)
        progress.update(task_id, completed=True)
    
    if not result.pages:
        console.print("[bold yellow]⚠️ No faculty pages discovered.[/bold yellow]")
        return
    
    console.print(f"\n✅ Found [bold green]{len(result.pages)}[/bold green] pages via {result.discovery_method}")
    
    table = Table(title="Discovered Pages", show_lines=True)
    table.add_column("Score", style="green", width=8)
    table.add_column("Type", style="cyan", width=12)
    table.add_column("URL", style="white", max_width=80)
    
    for page in result.faculty_pages[:20]:  # Show top 20
        table.add_row(
            f"{page.score:.2f}",
            page.page_type,
            page.url[:80] + "..." if len(page.url) > 80 else page.url
        )
    
    console.print(table)
    
    # Save results to JSON
    output_dir = "output_data"
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"discovery_{timestamp}.json")
    
    discovery_data = {
        "source_url": url,
        "mode": mode,
        "discovery_method": result.discovery_method,
        "sitemap_found": result.sitemap_found,
        "pages_crawled": result.pages_crawled,
        "pages": [
            {"url": p.url, "score": p.score, "type": p.page_type, "source": p.source}
            for p in result.pages
        ]
    }
    
    with open(output_file, "w") as f:
        json.dump(discovery_data, f, indent=2)
    
    console.print(f"\n📁 Results saved to: [bold]{output_file}[/bold]")


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
    scrape_parser.add_argument("--direct", "-d", action="store_true", 
                               help="Treat URL as faculty directory (skip discovery)")
    
    # Discover Command (NEW)
    discover_parser = subparsers.add_parser("discover", help="Discover faculty pages from a URL")
    discover_parser.add_argument("url", help="University URL")
    discover_parser.add_argument("--mode", choices=["auto", "sitemap", "deep", "search"], 
                                 default="auto", help="Discovery mode (default: auto)")
    
    # Batch Command (NEW)
    batch_parser = subparsers.add_parser("batch", help="Process multiple universities from Excel")
    batch_parser.add_argument("excel", help="Path to Excel file with university URLs")
    batch_parser.add_argument("--output", default="output_data", help="Output directory")
    batch_parser.add_argument("--limit", type=int, help="Limit number of universities")
    batch_parser.add_argument("--discover", action="store_true", help="Auto-discover faculty pages")
    
    # List Command
    list_parser = subparsers.add_parser("list", help="List scraped professors")

    # CSV Export Command
    csv_parser = subparsers.add_parser("csv", help="Export database to CSV")
    csv_parser.add_argument("--output", "-o", default="output_data/professors.csv", help="Output CSV file path")
    
    args = parser.parse_args()
    
    setup_app()
    
    if args.command == "scrape":
        asyncio.run(run_scrape_flow(args.url, enrich=not args.no_enrich, direct=args.direct))
    elif args.command == "discover":
        asyncio.run(run_discover_flow(args.url, mode=args.mode))
    elif args.command == "batch":
        # For batch processing, use the pipelines module directly
        console.print(Panel("[bold yellow]Batch Processing[/bold yellow]\nUse the standalone batch script:", border_style="yellow"))
        console.print(f"  python -m insti_scraper.pipelines.process_universities --input {args.excel} --output-dir {args.output}")
        console.print("\n[dim]This will be integrated in a future update.[/dim]")
    elif args.command == "list":
        list_professors_command()
    elif args.command == "csv":
        export_csv_command(args.output)
    else:
        parser.print_help()

def export_csv_command(output_file: str):
    import csv
    
    # ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(output_file)) or ".", exist_ok=True)
    
    with Session(engine) as session:
        professors = session.exec(select(Professor)).all()
        
        if not professors:
            console.print("[bold yellow]⚠️ No professors found in database.[/bold yellow]")
            return

        with open(output_file, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            # Write Header
            writer.writerow(["University", "Department", "Name", "Title", "Email", "Profile URL", "Research Interests", "H-Index", "Citations"])
            
            count = 0
            for p in professors:
                uni_name = p.department.university.name if p.department and p.department.university else "Unknown"
                dept_name = p.department.name if p.department else "General"
                interests = ", ".join(p.research_interests) if p.research_interests else ""
                
                writer.writerow([
                    uni_name,
                    dept_name,
                    p.name,
                    p.title,
                    p.email,
                    p.profile_url,
                    interests,
                    p.h_index,
                    p.total_citations
                ])
                count += 1
                
        console.print(f"✅ Exported [bold green]{count}[/bold green] professors to [bold]{output_file}[/bold]")

if __name__ == "__main__":
    main()

