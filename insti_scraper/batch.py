"""
Batch processing script for scraping multiple universities from an Excel file.
"""
import argparse
import asyncio
import json
import os
from datetime import datetime

import pandas as pd

from .crawler import UniversalScraper
from .logger import logger


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


async def scrape_single(scraper: UniversalScraper, uni_name: str, url: str, output_dir: str) -> dict:
    """Scrape a single university and save results."""
    logger.info(f"Starting scrape: {uni_name}")
    logger.debug(f"URL: {url}")
    
    try:
        data = await scraper.run(url)
        
        # Save individual result
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in uni_name)[:50]
        output_file = os.path.join(output_dir, f"{safe_name}.json")
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"✅ {uni_name}: Saved {len(data)} profiles to {output_file}")
        return {"name": uni_name, "url": url, "profiles": len(data), "status": "success", "file": output_file}
    
    except Exception as e:
        logger.error(f"❌ {uni_name}: Failed - {e}", exc_info=True)
        return {"name": uni_name, "url": url, "profiles": 0, "status": "failed", "error": str(e)}


async def run_batch(excel_path: str, output_dir: str, model: str, limit: int = None):
    """Run batch scraping on all universities in the Excel file."""
    os.makedirs(output_dir, exist_ok=True)
    
    df = load_universities(excel_path)
    
    if limit:
        df = df.head(limit)
        logger.info(f"Limited to first {limit} universities")
    
    scraper = UniversalScraper(model_name=model)
    results = []
    
    for idx, row in df.iterrows():
        uni_name = row.get("Name", f"University_{idx}")
        url = row["Uni faculty link"]
        rank = row.get("Rank", "N/A")
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[{idx+1}/{len(df)}] Rank #{rank}: {uni_name}")
        logger.info(f"{'='*60}")
        
        result = await scrape_single(scraper, uni_name, url, output_dir)
        results.append(result)
        
        # Reset scraper state for next university
        scraper.seen_urls.clear()
        scraper.all_profiles.clear()
    
    # Save summary
    summary_file = os.path.join(output_dir, "batch_summary.json")
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "results": results
    }
    
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"BATCH COMPLETE: {summary['success']}/{summary['total']} successful")
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
