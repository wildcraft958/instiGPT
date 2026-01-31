# InstiGPT Faculty Scraper

A universal AI-powered faculty data scraper that extracts professor profiles from university websites.

## Features

- **🔍 Multi-Tier Discovery**: DuckDuckGo search → Sitemap parsing → Deep crawling
- **🧠 Smart Extraction**: CSS selectors → LLM analysis → Vision AI (Gemini/GPT-4V)
- **🎓 Google Scholar Integration**: H-Index, citations, papers, research interests
- **🗃️ Advanced Database**: Bulk operations, deduplication, analytics
- **📦 Batch Processing**: Process hundreds of universities from Excel
- **🎯 Site-Specific Adapters**: Optimized for Princeton, MIT, IIT, UCT, and more
- **👁️ Vision Analysis**: AI-powered screenshot analysis for complex layouts
- **📊 Rich CLI**: Progress bars, statistics, cost tracking

## Architecture

The scraper uses a modular architecture with specialized components:

```
insti_scraper/
├── analyzers/           # Vision-based analysis (Gemini/GPT-4V)
│   └── vision_analyzer.py
├── pipelines/           # Batch processing
│   └── process_universities.py
├── models.py            # Data models (SQLModel)
├── config.py            # Configuration & logging
├── crawler.py           # HTTP/Browser fetching
├── discovery.py         # Multi-tier discovery
├── duckduckgo_discovery.py  # Enhanced DuckDuckGo search
├── extractors.py        # CSS + LLM extraction
├── enrichment.py        # Google Scholar enrichment
├── database.py          # Advanced database operations
└── main.py              # CLI entry point
```

## Installation

```bash
# Install with uv (recommended)
uv pip install -e .

# Setup browser for Crawl4AI
python -m playwright install chromium

# Optional: Install vision dependencies
pip install google-generativeai  # For Gemini
# OR use OpenAI GPT-4V (already included)
```

## Usage

### Single University
```bash
# Auto-discover and scrape
insti-scraper scrape "https://cse.iitb.ac.in"

# Skip enrichment (faster)
insti-scraper scrape "https://princeton.edu/faculty" --no-enrich

# Enable vision analysis (for complex pages)
insti-scraper scrape "https://mit.edu/people" --use-vision
```

### Batch Processing
```bash
# Process universities from Excel
insti-scraper batch universities.xlsx

# Specify output file
insti-scraper batch data.xlsx -o results.xlsx

# Control concurrency
insti-scraper batch data.xlsx -c 5
```

### Database Operations
```bash
# List all professors
insti-scraper list

# Show statistics
insti-scraper stats
```

## Excel Format

For batch processing, your Excel file should have these columns:

| Name | University Link |
|------|----------------|
| MIT  | https://mit.edu |
| Stanford | https://stanford.edu |

Output adds: `Status`, `Professors_Count`, `Error_Message`, `Processed_At`

## Advanced Features

### Vision Analysis

For JavaScript-heavy or complex layouts:

```python
from insti_scraper.analyzers import VisionAnalyzer

analyzer = VisionAnalyzer(model="gpt-4o")  # or "gemini-1.5-pro-vision"
result = await analyzer.analyze_faculty_page(screenshot_bytes, url)
```

### Database Queries

```python
from insti_scraper.database import get_db_manager

db = get_db_manager()

# Search with filters
profs = db.search_professors(
    name="Smith",
    university="MIT",
    min_h_index=20,
    has_email=True
)

# Get statistics
stats = db.get_statistics()

# Bulk operations
stats = db.bulk_insert_professors(professors, "MIT", "Computer Science")
```

### DuckDuckGo Discovery

```python
from insti_scraper.duckduckgo_discovery import discover_with_duckduckgo

pages = await discover_with_duckduckgo(
    university_name="Stanford University",
    homepage_url="https://stanford.edu",
    include_departments=True
)
```

## Environment Variables

```bash
export OPENAI_API_KEY="your-api-key"
# Or use local models via Ollama
export OLLAMA_HOST="http://localhost:11434"
```

## Logs

Logs are saved to `logs/scraper_YYYYMMDD_HHMMSS.log` with detailed debug info.

## Testing

```bash
uv run pytest tests/ -v
```
