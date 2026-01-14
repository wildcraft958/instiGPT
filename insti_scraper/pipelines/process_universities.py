"""
Batch processing script for scraping multiple universities from an Excel file.

Supports auto-discovery mode to find faculty pages from any university URL.
"""
import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from typing import Tuple, List
from urllib.parse import urlparse

import pandas as pd

from insti_scraper.orchestration.pipeline import ScrapingPipeline
from insti_scraper.discovery.discovery import FacultyPageDiscoverer, DiscoveredPage
from insti_scraper.core.config import settings
from insti_scraper.core.logger import logger


def analyze_url_quality(url: str) -> Tuple[str, str]:
    """
    Basic URL validation (Universal mode).
    We no longer block based on keywords like 'about' or 'department',
    as these pages might contain links to faculty directories.
    """
    if not url or not isinstance(url, str):
        return ("bad", "Invalid or empty URL")
        
    url_lower = url.lower()
    parsed = urlparse(url_lower)
    
    if not parsed.scheme or not parsed.netloc:
        return ("bad", "Invalid URL format (missing scheme/netloc)")
        
    # Check if path is too short (likely homepage)
    path = parsed.path
    if len(path.strip("/")) < 2 and not parsed.query:
        return ("warning", "URL path appears to be a homepage - Auto-Discovery recommended")
    
    return ("good", "Valid URL format")


def load_universities(excel_path: str) -> pd.DataFrame:
    """Load and filter universities from Excel file."""
    logger.info(f"Loading Excel file: {excel_path}")
    universities_df = pd.read_excel(excel_path)
    
    # Filter rows with valid faculty URLs
    url_column = "Uni faculty link"
    if url_column not in universities_df.columns:
        logger.error(f"Column '{url_column}' not found. Available: {universities_df.columns.tolist()}")
        raise ValueError(f"Missing column: {url_column}")
    
    # Filter valid URLs
    valid_universities_df = universities_df[universities_df[url_column].notna() & universities_df[url_column].str.startswith("http", na=False)].copy()
    logger.info(f"Found {len(valid_universities_df)} universities with valid faculty URLs")
    
    return valid_universities_df


def assess_result_quality(data: list, university_name: str) -> Tuple[str, str]:
    """
    Assess if scrape results look like faculty profiles or department pages.
    
    Returns:
        Tuple of (quality: 'good'|'warning'|'bad', reason: str)
    """
    if not data:
        return ("bad", "No profiles extracted")
    
    if len(data) < 3:
        # Check if names look like departments/faculties
        names = [p.get("name", "") for p in data]
        dept_keywords = ["faculty", "department", "school", "college", "institute", "center", "centre"]
        
        for name in names:
            name_lower = name.lower()
            if any(kw in name_lower for kw in dept_keywords):
                return ("bad", f"Extracted departments/faculties instead of people: {names}")
        
        return ("warning", f"Only {len(data)} profiles extracted - might be incomplete")
    
    # Check if we have emails (good sign of real profiles)
    emails_found = sum(1 for p in data if p.get("email"))
    if emails_found == 0 and len(data) > 5:
        return ("warning", "No emails found in profiles - might be department pages")
    
    return ("good", f"Extracted {len(data)} profiles successfully")


async def scrape_with_discovery(
    pipeline: ScrapingPipeline,
    university_name: str,
    url: str,
    discover_mode: str = "auto"
) -> List[dict]:
    """
    Scrape with auto-discovery: find faculty pages first, then scrape them.
    """
    discoverer = FacultyPageDiscoverer(
        max_depth=settings.DISCOVER_MAX_DEPTH,
        max_pages=settings.DISCOVER_MAX_PAGES
    )
    
    logger.info(f"🔍 Discovering faculty pages for {university_name}...")
    result = await discoverer.discover(url, mode=discover_mode)
    
    if not result.pages:
        logger.warning(f"No faculty pages discovered for {university_name}")
        return []
    
    logger.info(f"   Found {len(result.pages)} potential pages via {result.discovery_method}")
    
    # Get directory pages or top scoring pages
    directory_pages = [p for p in result.pages if p.page_type == "directory"]
    if not directory_pages:
        directory_pages = result.faculty_pages[:3]  # Top 3 by score
    
    all_profiles = []
    for page in directory_pages:
        logger.info(f"   Scraping: {page.url}")
        try:
            # Run the pipeline on each discovered page
            profiles = await pipeline.run(page.url)
            all_profiles.extend(profiles)
        except Exception as e:
            logger.error(f"   Error scraping {page.url}: {e}")
    
    # Deduplicate by profile URL
    seen = set()
    unique = []
    for p in all_profiles:
        profile_url = p.get("profile_url", "")
        if profile_url and profile_url not in seen:
            seen.add(profile_url)
            unique.append(p)
    
    return unique


async def scrape_single(
    pipeline: ScrapingPipeline,
    university_name: str,
    url: str,
    output_dir: str,
    rank: str,
    discover: bool = False,
    discover_mode: str = "auto"
) -> dict:
    """Scrape a single university and save results."""
    logger.info(f"Starting scrape: {university_name}")
    logger.debug(f"URL: {url}")
    
    # Pre-check URL quality
    url_quality, url_reason = analyze_url_quality(url)
    if url_quality == "bad" and not discover:
        logger.warning(f"⚠️ {university_name}: {url_reason}")
    
    result = {
        "name": university_name,
        "url": url,
        "rank": rank,
        "profiles": 0,
        "status": "pending",
        "url_quality": url_quality,
        "url_quality_reason": url_reason,
        "discovery_used": discover,
    }
    
    try:
        # Use discovery if enabled OR if URL quality is bad
        if discover or url_quality == "bad":
            logger.info(f"🔍 Using auto-discovery for {university_name}")
            data = await scrape_with_discovery(pipeline, university_name, url, discover_mode)
        else:
            data = await pipeline.run(url)
        
        # Assess result quality
        result_quality, result_reason = assess_result_quality(data, university_name)
        result["result_quality"] = result_quality
        result["result_quality_reason"] = result_reason
        result["profiles"] = len(data)
        
        # Determine overall status
        if result_quality == "bad" or (url_quality == "bad" and len(data) < 5 and not discover):
            result["status"] = "bad_link"
        elif result_quality == "warning" or url_quality == "warning":
            result["status"] = "warning"
        else:
            result["status"] = "success"
        
        # Save individual result with unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in university_name)[:40]
        output_file = os.path.join(output_dir, f"{safe_name}_{timestamp}.json")
        
        uni_data = {
            "university": university_name,
            "rank": rank,
            "source_url": url,
            "scraped_at": datetime.now().isoformat(),
            "url_quality": url_quality,
            "result_quality": result_quality,
            "discovery_used": discover,
            "profiles_count": len(data),
            "profiles": data
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(uni_data, f, indent=2)
        
        result["file"] = output_file
        logger.info(f"{'✅' if result['status'] == 'success' else '⚠️'} {university_name}: {result_reason} -> {output_file}")
        
    except Exception as e:
        logger.error(f"❌ {university_name}: Failed - {e}", exc_info=True)
        result["status"] = "failed"
        result["error"] = str(e)
    
    return result


async def run_batch(
    excel_path: str,
    output_dir: str,
    model: str,
    limit: int = None,
    skip_bad: bool = False,
    discover: bool = False,
    discover_mode: str = "auto"
):
    """Run batch scraping on all universities in the Excel file."""
    os.makedirs(output_dir, exist_ok=True)
    
    universities_df = load_universities(excel_path)
    
    if limit:
        universities_df = universities_df.head(limit)
        logger.info(f"Limited to first {limit} universities")
    
    if discover:
        logger.info(f"🔍 Discovery mode enabled: {discover_mode}")
    
    pipeline = ScrapingPipeline(output_dir=output_dir)
    results = []
    bad_links = []
    warnings = []
    skipped = []
    
    total = len(universities_df)
    for count, (idx, row) in enumerate(universities_df.iterrows(), 1):
        university_name = row.get("Name", f"University_{idx}")
        url = row["Uni faculty link"]
        rank = str(row.get("Rank", "N/A"))
        
        # Pre-check URL quality if skip_bad is enabled
        if skip_bad:
            url_quality, url_reason = analyze_url_quality(url)
            if url_quality == "bad":
                logger.warning(f"⏭️ SKIPPING [{rank}] {university_name}: {url_reason}")
                skipped.append({
                    "name": university_name,
                    "url": url,
                    "rank": rank,
                    "reason": url_reason
                })
                continue
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[{count}/{total}] Rank #{rank}: {university_name}")
        logger.info(f"{'='*60}")
        
        result = await scrape_single(
            pipeline, university_name, url, output_dir, rank,
            discover=discover, discover_mode=discover_mode
        )
        results.append(result)
        
        # Track bad links and warnings separately
        if result["status"] == "bad_link":
            bad_links.append(result)
        elif result["status"] == "warning":
            warnings.append(result)
        
        # Save progress incrementally (overwrites each time)
        progress_file = os.path.join(output_dir, "progress.json")
        progress = {
            "last_updated": datetime.now().isoformat(),
            "completed": count,
            "total": total,
            "success": sum(1 for r in results if r["status"] == "success"),
            "warnings": sum(1 for r in results if r["status"] == "warning"),
            "bad_links": sum(1 for r in results if r["status"] == "bad_link"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "results": results
        }
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2)
        logger.debug(f"Progress saved: {count}/{total} completed")
        
        # Reset scraper state for next university
        pipeline.list_scraper.seen_urls.clear()
    
    # Save summary
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "warnings": len(warnings),
        "bad_links": len(bad_links),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "results": results
    }
    
    summary_file = os.path.join(output_dir, f"batch_summary_{timestamp}.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    # Save bad links separately
    if bad_links:
        bad_links_file = os.path.join(output_dir, f"bad_links_{timestamp}.json")
        bad_links_data = {
            "timestamp": datetime.now().isoformat(),
            "description": "URLs that appear to be department pages instead of faculty directories",
            "count": len(bad_links),
            "links": bad_links
        }
        with open(bad_links_file, "w", encoding="utf-8") as f:
            json.dump(bad_links_data, f, indent=2)
        logger.warning(f"⚠️ Bad links saved to: {bad_links_file}")
    
    # Save warnings separately
    if warnings:
        warnings_file = os.path.join(output_dir, f"warnings_{timestamp}.json")
        warnings_data = {
            "timestamp": datetime.now().isoformat(),
            "description": "URLs that may need manual review",
            "count": len(warnings),
            "links": warnings
        }
        with open(warnings_file, "w", encoding="utf-8") as f:
            json.dump(warnings_data, f, indent=2)
        logger.warning(f"⚠️ Warnings saved to: {warnings_file}")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"BATCH COMPLETE:")
    logger.info(f"  ✅ Success: {summary['success']}/{summary['total']}")
    logger.info(f"  ⚠️ Warnings: {summary['warnings']}")
    logger.info(f"  🔴 Bad Links: {summary['bad_links']}")
    logger.info(f"  ❌ Failed: {summary['failed']}")
    logger.info(f"Summary saved to: {summary_file}")
    
    return summary


def check_urls_only(excel_path: str, output_dir: str, limit: int = None):
    """
    Dry-run: Check all URLs without scraping.
    Outputs a report of good, warning, and bad URLs.
    """
    os.makedirs(output_dir, exist_ok=True)
    universities_df = load_universities(excel_path)
    
    if limit:
        universities_df = universities_df.head(limit)
    
    results = {"good": [], "warning": [], "bad": []}
    
    print(f"\n{'='*60}")
    print(f"URL VALIDATION CHECK - {len(universities_df)} URLs")
    print(f"{'='*60}\n")
    
    for idx, row in universities_df.iterrows():
        university_name = row.get("Name", f"University_{idx}")
        url = row["Uni faculty link"]
        rank = str(row.get("Rank", "N/A"))
        
        quality, reason = analyze_url_quality(url)
        
        entry = {
            "rank": rank,
            "name": university_name,
            "url": url,
            "quality": quality,
            "reason": reason
        }
        results[quality].append(entry)
        
        # Print colored output
        if quality == "good":
            symbol = "✅"
        elif quality == "warning":
            symbol = "⚠️"
        else:
            symbol = "🔴"
        
        print(f"{symbol} [{rank}] {university_name}")
        print(f"   URL: {url}")
        print(f"   {reason}\n")
    
    # Save report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = os.path.join(output_dir, f"url_check_report_{timestamp}.json")
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": len(universities_df),
            "good": len(results["good"]),
            "warning": len(results["warning"]),
            "bad": len(results["bad"])
        },
        "good_urls": results["good"],
        "warning_urls": results["warning"],
        "bad_urls": results["bad"]
    }
    
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    
    print(f"{'='*60}")
    print(f"SUMMARY:")
    print(f"  ✅ Good URLs: {len(results['good'])}")
    print(f"  ⚠️ Warning URLs: {len(results['warning'])}")
    print(f"  🔴 Bad URLs: {len(results['bad'])}")
    print(f"\nReport saved to: {report_file}")
    print(f"{'='*60}")
    
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Batch scrape universities from Excel file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard batch scraping
  insti-batch --input universities.xlsx --output-dir ./results
  
  # Auto-discover faculty pages from any URL
  insti-batch --input universities.xlsx --discover
  
  # Use Ollama for free local inference
  insti-batch --input universities.xlsx --model "ollama/llama3.1:8b"
        """
    )
    parser.add_argument("--input", required=True, help="Input Excel file path")
    parser.add_argument("--output-dir", default="./batch_results", help="Output directory for results")
    parser.add_argument("--model", default=None, help="LLM model (default: gpt-4o-mini or ollama if available)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of universities to process")
    parser.add_argument("--check-urls", action="store_true", help="Only check URLs without scraping (dry-run)")
    parser.add_argument("--skip-bad", action="store_true", help="Skip URLs detected as bad quality")
    
    # Discovery options
    parser.add_argument("--discover", action="store_true",
        help="Enable auto-discovery from any URL (not just faculty pages)")
    parser.add_argument("--discover-mode", choices=["sitemap", "deep", "auto"],
        default="auto", help="Discovery mode: sitemap (fast), deep (thorough), auto (default)")
    parser.add_argument("--prefer-local", action="store_true",
        help="Prefer Ollama models when available (saves API costs)")
    
    args = parser.parse_args()
    
    # Check URLs only mode (no API key needed)
    if args.check_urls:
        check_urls_only(args.input, args.output_dir, args.limit)
        return
    
    # Determine model
    if args.model:
        model = args.model
    elif args.prefer_local and settings.is_ollama_available():
        model = settings.get_model_for_task("schema_discovery", prefer_local=True)
        logger.info(f"🏠 Using local Ollama model: {model}")
    else:
        model = settings.MODEL_NAME
    
    # Check for API key (not needed for Ollama)
    if "ollama" not in model.lower() and not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY not found. Please set it or use --prefer-local with Ollama.")
        return
    
    asyncio.run(run_batch(
        args.input, args.output_dir, model, args.limit, args.skip_bad,
        discover=args.discover, discover_mode=args.discover_mode
    ))


if __name__ == "__main__":
    main()
