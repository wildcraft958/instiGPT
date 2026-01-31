# InstiGPT Faculty Scraper

**AI-powered universal faculty data scraper** that extracts professor profiles from any university website and enriches them with Google Scholar metrics.

## 🚀 Key Features

- **🔍 Universal Auto-Discovery**: Auto-detects faculty pages via sitemap, DuckDuckGo search, or deep crawling
- **📸 Vision Analysis**: Uses GPT-4o-mini to classify pages (directory, gateway, profile, blocked)
- **⚡ Multi-Fallback Extraction**: CSS selectors → LLM extraction → Pagination handling
- **🎓 Google Scholar Linking**: Enriches profiles with H-Index, citations, top papers
- **🛡️ Block Detection**: Detects CAPTCHA, Cloudflare, login walls automatically
- **📋 University Profiles**: Pre-configured URLs/selectors for Princeton, MIT, Stanford, IITs
- **📦 Batch Processing**: Process hundreds of universities from an Excel sheet

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

### Option A: OpenAI (Recommended)
```bash
export OPENAI_API_KEY="sk-..."
```

### Option B: Ollama (Free/Local)
```bash
ollama serve
ollama pull llama3.1:8b

export OLLAMA_BASE_URL="http://localhost:11434"
```

## 📖 Usage

### 1. Scrape a University
```bash
# Basic scrape with enrichment
python -m insti_scraper scrape "https://princeton.edu"

# Skip Google Scholar enrichment (faster)
python -m insti_scraper scrape "https://mit.edu" --no-enrich
```

### 2. Discover Faculty Pages Only
```bash
python -m insti_scraper discover "https://stanford.edu"
```

### 3. Batch Process from Excel
```bash
python -m insti_scraper batch universities.xlsx --output ./results
```

### 4. List Database Content
```bash
python -m insti_scraper list
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         DISCOVERY PHASE                         │
├─────────────────────────────────────────────────────────────────┤
│  1. Check University Profiles (YAML config)                     │
│  2. DuckDuckGo Search (site:domain + faculty keywords)          │
│  3. Sitemap Parsing                                             │
│  4. Deep Crawling (BFS with keyword scoring)                    │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        EXTRACTION PHASE                         │
├─────────────────────────────────────────────────────────────────┤
│  1. Vision Analysis: Classify page type (A-F, Z)                │
│     - Type A: Full directory → Extract directly                 │
│     - Type C: Gateway → Crawl department links                  │
│     - Type D: Paginated → Use pagination handler                │
│     - Type F: Individual → Skip or extract single               │
│  2. Multi-Fallback Selectors: DataTables, Cards, Grids          │
│  3. LLM Extraction: GPT-4o for complex layouts                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       ENRICHMENT PHASE                          │
├─────────────────────────────────────────────────────────────────┤
│  Google Scholar → H-Index, Citations, Top Papers                │
└─────────────────────────────────────────────────────────────────┘
```

## 📂 Project Structure

```
insti_scraper/
├── config/                   # University profiles & config
│   ├── university_profiles.yaml
│   └── profile_loader.py
├── core/                     # Core utilities
│   ├── config.py             # Settings
│   ├── retry_wrapper.py      # Exponential backoff
│   ├── selector_strategies.py # Multi-fallback CSS
│   └── auto_config.py        # Pagination detection
├── discovery/                # Page discovery
│   ├── discovery.py          # FacultyPageDiscoverer
│   └── duckduckgo_discovery.py
├── handlers/                 # Page type handlers
│   ├── page_handlers.py      # Abstract handlers
│   └── pagination_handler.py
├── services/                 # Business logic
│   ├── extraction_service.py # LLM extraction
│   ├── enrichment_service.py # Scholar enrichment
│   └── vision_analyzer.py    # Screenshot analysis
├── domain/                   # Data models
│   └── models.py             # University, Dept, Professor
├── database/                 # Persistence
│   └── crud.py
└── main.py                   # CLI entrypoint
```

## 🧪 Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run integration tests only
pytest tests/test_integration.py -v
```

## 📄 License
MIT
