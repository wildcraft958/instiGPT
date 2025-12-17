# University Faculty Web Scraper

A **hybrid web scraper** that intelligently crawls university faculty directories using either cloud-based (Gemini) or local vision-based (Qwen3-VL) backends.

## Features

- 🔄 **Hybrid Backend**: Auto-switches between local and cloud processing
- 👁️ **Vision Navigation**: Qwen3-VL "sees" pages like a human
- 🧠 **Smart Planning**: Gemini-powered with CMS pattern detection
- 📊 **Validated Output**: Pydantic `ProfessorProfile` schema
- 🔁 **Pagination**: Handles "Load More" and numbered pages
- 🤖 **Self-Correction**: Retries with alternative selectors

## Quick Start

```bash
# Install dependencies
uv pip install -r requirements.txt
playwright install chromium

# Set up .env file
echo "GOOGLE_API_KEY=your_key_here" > .env

# Start Ollama (for local backend)
ollama pull qwen3-vl && ollama pull llama3.2:latest

# Run the scraper
source .venv/bin/activate
python -m scraper_app.main \
    --url "https://engineering.wustl.edu/faculty/index.html" \
    --objective "Scrape all engineering faculty"
```

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--url`, `-u` | Required | Starting URL |
| `--objective`, `-o` | Required | Scraping objective |
| `--backend`, `-b` | `auto` | `auto` / `gemini` / `local` |
| `--headless` | False | Headless browser mode |
| `--delay` | 1000 | Request delay (ms) |
| `--max-steps` | 50 | Max crawl steps |
| `--output`, `-O` | `faculty_data.json` | Output file |
| `--debug`, `-d` | False | Debug logging |

## Architecture

```
scraper_app/
├── main.py              # CLI entry point
├── manager.py           # LangGraph orchestrator
├── browser.py           # Playwright manager
├── state.py             # State definitions
├── config.py            # Settings
├── utils.py             # Utilities
└── backends/
    ├── base.py          # Abstract base class
    ├── gemini.py        # Cloud backend (Gemini + Ollama)
    └── ollama_vision.py # Local backend (Qwen3-VL)
```

## Output Format

```json
[
  {
    "name": "Dr. Jane Smith",
    "title": "Professor of Computer Science",
    "email": "jsmith@university.edu",
    "profile_url": "https://...",
    "research_interests": ["Machine Learning", "NLP"],
    "publications": ["Paper 1", "Paper 2"],
    "lab": "AI Research Lab"
  }
]
```

## Examples

```bash
# Auto mode (tries local first, falls back to cloud)
python -m scraper_app.main \
    --url "https://engineering.wustl.edu/faculty" \
    --objective "Scrape engineering faculty"

# Force Gemini backend
python -m scraper_app.main \
    --url "https://olin.wustl.edu/faculty" \
    --objective "Scrape business faculty" \
    --backend gemini

# Headless mode for servers
python -m scraper_app.main \
    --url "https://cs.stanford.edu/people" \
    --objective "Scrape CS faculty" \
    --backend local --headless
```

## 🌐 Colab Workflow

For running on Google Colab (no local GPU needed):

1. **Open** `colab_scraper.ipynb` in Colab
2. **Select GPU runtime** (T4 recommended)
3. **Run cells in order:**
   - Cell 1: Install Ollama & dependencies
   - Cell 2: Start Ollama server
   - Cell 3: Pull Qwen3-VL model (~4GB)
   - Cell 4: Run scraper
4. **Download** `faculty_data.json`

Or run via CLI in Colab:
```bash
python -m scraper_app.main \
    --url "https://engineering.wustl.edu/faculty" \
    --objective "Scrape faculty" \
    --backend ollama_only \
    --headless
```
