"""
Insti-Scraper: AI-powered faculty data scraper.

Usage:
    python -m insti_scraper scrape "https://university.edu/faculty"
    python -m insti_scraper list
"""

import asyncio
import argparse
import sys
import logging

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from sqlmodel import select

from .config import settings, cost_tracker, console
from .models import (
    Professor, University, Department,
    init_database, get_session
)
from .crawler import CrawlerManager, FetchMode
from .discovery import FacultyPageDiscoverer
from .extractors import extract_with_fallback
from .enrichment import enrich_professor

logger = logging.getLogger(__name__)


def save_professors(professors, university_url: str, department_name: str) -> dict:
    """Save professors to database."""
    from urllib.parse import urlparse
    
    stats = {"new": 0, "updated": 0, "skipped": 0}
    
    with get_session() as session:
        # Get or create university
        parsed = urlparse(university_url)
        domain = parsed.netloc.replace("www.", "")
        uni_name = " ".join(p.title() for p in domain.replace(".edu", "").replace(".ac.in", "").split("."))
        
        university = session.exec(
            select(University).where(University.name == uni_name)
        ).first()
        
        if not university:
            university = University(name=uni_name, website=f"{parsed.scheme}://{parsed.netloc}")
            session.add(university)
            session.commit()
            session.refresh(university)
        
        # Get or create department
        department = session.exec(
            select(Department).where(
                Department.name == department_name,
                Department.university_id == university.id
            )
        ).first()
        
        if not department:
            department = Department(name=department_name, university_id=university.id)
            session.add(department)
            session.commit()
            session.refresh(department)
        
        # Save professors
        for prof in professors:
            existing = session.exec(
                select(Professor).where(
                    Professor.name == prof.name,
                    Professor.department_id == department.id
                )
            ).first()
            
            if existing:
                # Update if we have new info
                if prof.email and not existing.email:
                    existing.email = prof.email
                if prof.profile_url and not existing.profile_url:
                    existing.profile_url = prof.profile_url
                stats["updated"] += 1
            else:
                prof.department_id = department.id
                session.add(prof)
                stats["new"] += 1
        
        session.commit()
    
    return stats


async def run_scrape(url: str, enrich: bool = True):
    """Main scraping flow."""
    console.print(Panel(f"[bold blue]🚀 Insti-Scraper[/bold blue]\nTarget: {url}", border_style="blue"))
    
    discoverer = FacultyPageDiscoverer()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True
    ) as progress:
        
        # Phase 1: Discovery
        task = progress.add_task("[cyan]🔍 Discovering faculty pages...", total=None)
        result = await discoverer.discover(url)
        discovered = result.faculty_pages
        
        if not discovered:
            progress.stop()
            console.print("[bold red]❌ No faculty pages found.[/bold red]")
            return
        
        progress.update(task, completed=True)
        console.print(f"   ✅ Found [green]{len(discovered)}[/green] pages via {result.method}")
        
        # Phase 2: Extraction
        task = progress.add_task(f"[cyan]⛏️ Extracting from {len(discovered)} pages...", total=len(discovered))
        
        total_new = 0
        
        async with CrawlerManager() as crawler:
            for page in discovered:
                progress.update(task, description=f"[cyan]Processing {page.url[:50]}...")
                
                try:
                    fetch_result = await crawler.fetch(page.url, FetchMode.HTML)
                    
                    if not fetch_result.ok:
                        progress.advance(task)
                        continue
                    
                    extraction = await extract_with_fallback(fetch_result.html, page.url)
                    professors = extraction.professors
                    
                    if professors:
                        console.print(f"      📄 Found [green]{len(professors)}[/green] in '{extraction.department_name}' ({extraction.method})")
                        
                        stats = save_professors(professors, url, extraction.department_name)
                        total_new += stats["new"]
                    
                except Exception as e:
                    logger.error(f"Error processing {page.url}: {e}")
                
                progress.advance(task)
        
        console.print(f"   ✅ Saved [green]{total_new}[/green] new professors")
        
        # Phase 3: Enrichment
        if enrich and total_new > 0:
            task = progress.add_task("[cyan]🎓 Enriching with Scholar data...", total=None)
            
            with get_session() as session:
                to_enrich = session.exec(
                    select(Professor).where(Professor.google_scholar_id == None).limit(5)
                ).all()
                
                enriched = 0
                for prof in to_enrich:
                    try:
                        updated = await enrich_professor(prof)
                        if updated.google_scholar_id:
                            session.add(updated)
                            enriched += 1
                    except Exception as e:
                        logger.warning(f"Enrichment failed for {prof.name}: {e}")
                
                session.commit()
            
            progress.update(task, completed=True)
            console.print(f"   ✅ Enriched {enriched} profiles")
    
    cost_tracker.print_summary()


def list_professors():
    """List all professors in database."""
    with get_session() as session:
        professors = session.exec(select(Professor)).all()
        
        table = Table(title="🎓 Professor Database", show_lines=True)
        table.add_column("University", style="magenta")
        table.add_column("Department", style="cyan")
        table.add_column("Name", style="bold white")
        table.add_column("Email", max_width=25)
        table.add_column("H-Index", justify="right", style="green")
        
        for p in professors:
            uni = p.department.university.name if p.department and p.department.university else "?"
            dept = p.department.name if p.department else "General"
            
            table.add_row(uni, dept, p.name, p.email or "-", str(p.h_index))
        
        console.print(table)
        console.print(f"\nTotal: [bold]{len(professors)}[/bold] professors")


async def run_batch(input_file: str, output_file: str = None, max_concurrent: int = 3, enrich: bool = True):
    """Batch process universities from Excel."""
    from .pipelines import process_universities_batch
    
    console.print(f"[bold blue]📦 Batch Processing[/bold blue]\n")
    
    try:
        stats = await process_universities_batch(
            input_file=input_file,
            output_file=output_file,
            max_concurrent=max_concurrent,
            enable_enrichment=enrich
        )
        
        console.print(f"\n[bold green]✅ Batch processing complete![/bold green]")
        console.print(f"   Successful: {stats['successful']}/{stats['total']}")
        console.print(f"   Professors: {stats['professors_found']}")
        
    except Exception as e:
        console.print(f"[bold red]❌ Batch processing failed: {e}[/bold red]")
        logger.error(f"Batch error: {e}", exc_info=True)


def show_stats():
    """Show database statistics."""
    from .database import get_db_manager
    
    db = get_db_manager()
    stats = db.get_statistics()
    
    table = Table(title="📊 Database Statistics", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="bold")
    
    table.add_row("Universities", f"{stats['total_universities']:,}")
    table.add_row("Departments", f"{stats['total_departments']:,}")
    table.add_row("Professors", f"{stats['total_professors']:,}")
    table.add_row("With Email", f"{stats['professors_with_email']:,}")
    table.add_row("With Scholar", f"{stats['professors_with_scholar']:,}")
    table.add_row("Avg H-Index", f"{stats['avg_h_index']:.1f}")
    
    console.print("\n")
    console.print(table)
    console.print("\n")


def main():
    """CLI entry point."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    parser = argparse.ArgumentParser(
        description="Insti-Scraper: AI-powered faculty data scraper",
        epilog="Examples:\n"
               "  insti-scraper scrape https://cse.iitb.ac.in/faculty\n"
               "  insti-scraper batch universities.xlsx\n"
               "  insti-scraper stats\n",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command")
    
    # Scrape command
    scrape = subparsers.add_parser("scrape", help="Scrape a single university")
    scrape.add_argument("url", help="University faculty URL or homepage")
    scrape.add_argument("--no-enrich", action="store_true", help="Skip Scholar enrichment")
    scrape.add_argument("--use-vision", action="store_true", help="Enable vision-based extraction")
    
    # Batch command
    batch = subparsers.add_parser("batch", help="Batch process from Excel")
    batch.add_argument("input", help="Input Excel file path")
    batch.add_argument("-o", "--output", help="Output file path (optional)")
    batch.add_argument("-c", "--concurrent", type=int, default=3, help="Max concurrent requests (default: 3)")
    batch.add_argument("--no-enrich", action="store_true", help="Skip Scholar enrichment")
    
    # List command
    subparsers.add_parser("list", help="List scraped professors")
    
    # Stats command
    subparsers.add_parser("stats", help="Show database statistics")
    
    args = parser.parse_args()
    
    settings.setup_logging()
    init_database()
    
    if args.command == "scrape":
        asyncio.run(run_scrape(args.url, enrich=not args.no_enrich))
    elif args.command == "batch":
        asyncio.run(run_batch(
            args.input,
            args.output,
            args.concurrent,
            enrich=not args.no_enrich
        ))
    elif args.command == "list":
        list_professors()
    elif args.command == "stats":
        show_stats()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
