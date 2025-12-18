"""
Batch processing script for scraping multiple universities from an Excel file.
"""
import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from typing import Tuple
from urllib.parse import urlparse

import pandas as pd

from .crawler import UniversalScraper
from .logger import logger


# Patterns that indicate a URL is likely a department/landing page, not faculty directory
BAD_URL_PATTERNS = [
    r"/faculties-and-departments/?$",
    r"/departments/?$",
    r"/schools/?$",
    r"/colleges/?$",
    r"/about/?$",
    r"/engineering/?$",
    r"/medicine/?$",
    r"/science/?$",
    r"/arts/?$",
    r"/business/?$",
    r"/law/?$",
]

# Patterns that indicate a URL is likely a good faculty/people directory
GOOD_URL_PATTERNS = [
    r"/people",
    r"/faculty",
    r"/staff",
    r"/profiles",
    r"/directory",
    r"/academics",
    r"/researchers",
    r"/our-people",
    r"/team",
    r"/members",
]


def analyze_url_quality(url: str) -> Tuple[str, str]:
    """
    Analyze URL to detect if it's likely a good faculty directory or a bad department page.
    
    Returns:
        Tuple of (quality: 'good'|'warning'|'bad', reason: str)
    """
    url_lower = url.lower()
    parsed = urlparse(url_lower)
    path = parsed.path
    
    # Check for good patterns first
    for pattern in GOOD_URL_PATTERNS:
        if re.search(pattern, path):
            return ("good", f"URL contains '{pattern}' - likely a faculty directory")
    
    # Check for bad patterns
    for pattern in BAD_URL_PATTERNS:
        if re.search(pattern, path):
            return ("bad", f"URL matches '{pattern}' - likely a department landing page, not faculty directory")
    
    # Check if path is too short (likely homepage)
    if len(path.strip("/")) < 5:
        return ("warning", "URL path is very short - might be a homepage, not faculty directory")
    
    return ("warning", "Unable to determine URL quality - proceed with caution")


def load_universities(excel_path: str) -> pd.DataFrame:
    """Load and filter universities from Excel file."""
    logger.info(f"Loading Excel file: {excel_path}")
    df = pd.read_excel(excel_path)
    
    # Filter rows with valid faculty URLs
    url_column = "Uni faculty link"
    if url_column not in df.columns:
        logger.error(f"Column '{url_column}' not found. Available: {df.columns.tolist()}")
        raise ValueError(f"Missing column: {url_column}")
    
    # Filter valid URLs
    valid_df = df[df[url_column].notna() & df[url_column].str.startswith("http", na=False)].copy()
    logger.info(f"Found {len(valid_df)} universities with valid faculty URLs")
    
    return valid_df


def assess_result_quality(data: list, uni_name: str) -> Tuple[str, str]:
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


async def scrape_single(scraper: UniversalScraper, uni_name: str, url: str, output_dir: str, rank: str) -> dict:
    """Scrape a single university and save results."""
    logger.info(f"Starting scrape: {uni_name}")
    logger.debug(f"URL: {url}")
    
    # Pre-check URL quality
    url_quality, url_reason = analyze_url_quality(url)
    if url_quality == "bad":
        logger.warning(f"⚠️ {uni_name}: {url_reason}")
    
    result = {
        "name": uni_name,
        "url": url,
        "rank": rank,
        "profiles": 0,
        "status": "pending",
        "url_quality": url_quality,
        "url_quality_reason": url_reason,
    }
    
    try:
        data = await scraper.run(url)
        
        # Assess result quality
        result_quality, result_reason = assess_result_quality(data, uni_name)
        result["result_quality"] = result_quality
        result["result_quality_reason"] = result_reason
        result["profiles"] = len(data)
        
        # Determine overall status
        if result_quality == "bad" or (url_quality == "bad" and len(data) < 5):
            result["status"] = "bad_link"
        elif result_quality == "warning" or url_quality == "warning":
            result["status"] = "warning"
        else:
            result["status"] = "success"
        
        # Save individual result with unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in uni_name)[:40]
        output_file = os.path.join(output_dir, f"{safe_name}_{timestamp}.json")
        
        uni_data = {
            "university": uni_name,
            "rank": rank,
            "source_url": url,
            "scraped_at": datetime.now().isoformat(),
            "url_quality": url_quality,
            "result_quality": result_quality,
            "profiles_count": len(data),
            "profiles": data
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(uni_data, f, indent=2)
        
        result["file"] = output_file
        logger.info(f"{'✅' if result['status'] == 'success' else '⚠️'} {uni_name}: {result_reason} -> {output_file}")
        
    except Exception as e:
        logger.error(f"❌ {uni_name}: Failed - {e}", exc_info=True)
        result["status"] = "failed"
        result["error"] = str(e)
    
    return result


async def run_batch(excel_path: str, output_dir: str, model: str, limit: int = None):
    """Run batch scraping on all universities in the Excel file."""
    os.makedirs(output_dir, exist_ok=True)
    
    df = load_universities(excel_path)
    
    if limit:
        df = df.head(limit)
        logger.info(f"Limited to first {limit} universities")
    
    scraper = UniversalScraper(model_name=model)
    results = []
    bad_links = []
    warnings = []
    
    total = len(df)
    for count, (idx, row) in enumerate(df.iterrows(), 1):
        uni_name = row.get("Name", f"University_{idx}")
        url = row["Uni faculty link"]
        rank = str(row.get("Rank", "N/A"))
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[{count}/{total}] Rank #{rank}: {uni_name}")
        logger.info(f"{'='*60}")
        
        result = await scrape_single(scraper, uni_name, url, output_dir, rank)
        results.append(result)
        
        # Track bad links and warnings separately
        if result["status"] == "bad_link":
            bad_links.append(result)
        elif result["status"] == "warning":
            warnings.append(result)
        
        # Reset scraper state for next university
        scraper.seen_urls.clear()
        scraper.all_profiles.clear()
    
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


def main():
    parser = argparse.ArgumentParser(description="Batch scrape universities from Excel file")
    parser.add_argument("--input", required=True, help="Input Excel file path")
    parser.add_argument("--output-dir", default="./batch_results", help="Output directory for results")
    parser.add_argument("--model", default="openai/gpt-4o-mini", help="LLM model to use")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of universities to process")
    
    args = parser.parse_args()
    
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY not found. Please set it before running.")
        return
    
    asyncio.run(run_batch(args.input, args.output_dir, args.model, args.limit))


if __name__ == "__main__":
    main()
