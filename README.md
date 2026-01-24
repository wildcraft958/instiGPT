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

### 1. Scrape a University
Auto-discover and extract faculty profiles from a given URL.

```bash
# Basic Scrape (Auto-discovery enabled by default)
uv run insti-scraper scrape "https://www.cse.iitb.ac.in"

# Disable enrichment (skip Google Scholar)
uv run insti-scraper scrape "https://cse.iitkgp.ac.in" --no-enrich
```

### 2. List Database Content
View the extracted professors in a rich CLI table.

```bash
uv run insti-scraper list
```

## 🏗️ Architecture

The project now uses a **Service-Oriented Architecture** with **SQLModel** persistence.

1.  **Discovery Service**: Analyzes pages to find faculty directories using Vision/LLM and Crawl4AI.
2.  **Extraction Service**: Extracts rich profile data (Name, Dept, Interests, Papers) using LLMs.
    - *Features*: Infer Department context, extract Publication Summaries, handle Garbage Links.
3.  **Enrichment Service**: Enhances profiles with Google Scholar metrics (H-Index, Citations).
4.  **Persistence**: Data is stored in a normalized `insti.db` SQLite database with correct University/Department hierarchy.

## 📂 Project Structure

```text
instiGPT/
├── insti_scraper/          # Main package
│   ├── core/               # Config, Database, Prompts
│   ├── domain/             # SQLModel Tables (University, Dept, Professor)
│   ├── services/           # Business Logic
│   │   ├── discovery_service.py   # Page Classification
│   │   ├── extraction_service.py  # LLM Extraction
│   │   └── enrichment_service.py  # Google Scholar
│   └── main.py             # CLI Entrypoint
├── tests/                  # Pytest suite
└── logs/                   # Execution logs
```

## 📄 License
MIT
