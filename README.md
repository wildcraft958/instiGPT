# InstiGPT Faculty Scraper

**AI-powered universal faculty data scraper** that extracts professor profiles from any university website and enriches them with Google Scholar metrics.

## 🚀 Key Features

- **🔍 Universal Auto-Discovery**: Automatically detects faculty list pages from a university homepage or sub-page.
- **⚡ Hybrid Extraction**: Uses fast CSS selectors for speed, falling back to LLM-based extraction for complex layouts.
- **🧠 Semantic Page Analysis**: Intelligently identifies "Faculty Directories" vs "Staff" or "News" pages.
- **🎓 Google Scholar Linking**: **[NEW]** Automatically searches and links faculty to their Google Scholar profiles to fetch:
  - H-Index
  - Total Citations
  - Top Paper Titles
- **🛠️ LLM Agnostic**: Supports **OpenAI (GPT-4o)** for quality or **Ollama** for free local inference.
- **📦 Batch Processing**: Process hundreds of universities from an Excel sheet.

## 🛠️ Installation

Prerequisites: `python >= 3.10`, `uv` (recommended).

```bash
# 1. Create and activate virtual environment
uv venv .venv
source .venv/bin/activate

# 2. Install dependencies (editable mode recommended for dev)
uv pip install -e .

# 3. Setup browser for Crawl4AI
python -m playwright install chromium
```

## ⚙️ Configuration

Create a `.env` file or export environment variables:

### Option A: OpenAI (High Quality)
```bash
export OPENAI_API_KEY="sk-..."
```

### Option B: Ollama (Free/Local)
```bash
# Start Ollama server first
ollama run llama3.1:8b

export OLLAMA_BASE_URL="http://localhost:11434"
# The scraper will automatically detect this and switch to local models
```

## 📖 Usage

### 1. Single University Scrape
Scrape a specific URL and discover faculty profiles.

```bash
# Direct scrape of a known list page
insti-scraper --url "https://nse.mit.edu/people/faculty" --output results.json

# Auto-discover faculty pages from a homepage
insti-scraper --url "https://www.stanford.edu" --discover
```

### 2. Batch Processing
Process multiple universities from an Excel file (Input columns: `Name`, `Uni faculty link`).

```bash
insti-batch --input targets.xlsx --output-dir ./results
```

**Options:**
- `--discover`: Enable auto-discovery for all links (useful if links are generic homepages).
- `--limit 5`: Process only the first 5 rows.
- `--skip-bad`: Skip URLs that look like "bad" links (e.g., login pages).

## 📊 Output Format

The scraper produces rich JSON output. Note the flat structure for Google Scholar data:

```json
[
  {
    "name": "Inder Sekhar Yadav",
    "university": "IIT Kharagpur",
    "department": "Humanities",
    "profile_url": "https://iitkgp.ac.in/department/HS/faculty/isy",
    "email": "isy@hss.iitkgp.ac.in",
    "research_interests": ["Financial Economics", "Macroeconomics"],
    
    // Google Scholar Data
    "google_scholar_url": "https://scholar.google.com/citations?user=aol7UFwAAAAJ",
    "h_index": "12",
    "total_citations": "1203",
    "paper_titles": [
      "Financial development and economic growth...",
      "The nexus between firm size, growth and profitability..."
    ]
  }
]
```

## 🏗️ Architecture

1.  **Phase 1: Discovery**
    *   Crawls the entry URL.
    *   Uses Vision/LLM analysis to identify "directory" pages.
    *   Extracts basic profile links using generated CSS selectors.
2.  **Phase 2: Enrichment**
    *   Visits each profile page.
    *   Extracts email, detailed research interests, and bio.
3.  **Phase 3: Scholar Linking**
    *   Searches DuckDuckGo for the professor's Scholar profile.
    *   Uses LLM to verify the correct match.
    *   Scrapes metrics (H-index, Citations) directly from Scholar.

## 📂 Project Structure

```text
instiGPT/
├── insti_scraper/          # Main package
│   ├── core/               # Config and models
│   ├── scrapers/           # Scraper logic
│   │   ├── list_scraper.py      # Phase 1
│   │   ├── detail_scraper.py    # Phase 2
│   │   └── google_scholar_scraper.py # Phase 3
│   └── orchestration/      # Pipeline management
├── scripts/                # Utility scripts
├── archives/               # Old logs and data storage
└── targets.xlsx            # Batch input file
```

## 📄 License
MIT
