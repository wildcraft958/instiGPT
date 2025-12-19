# InstiGPT Faculty Scraper

AI-powered universal faculty data scraper that extracts professor profiles from university websites.

## Features

- 🔍 **Auto Schema Discovery** - LLM detects page structure automatically
- ⚡ **CSS + LLM Fallback** - Fast CSS extraction with LLM backup
- 📊 **Batch Processing** - Scrape multiple universities from Excel
- 📝 **Detailed Logging** - Debug logs saved to `logs/`
- 🌐 **Auto Page Discovery** - Find faculty pages from any URL (NEW!)
- 🦙 **Ollama Support** - Free local inference with Ollama (NEW!)

## Installation

```bash
# Clone and install
git clone <repo-url>
cd instiGPT
make install

# Setup browser
make setup
```

## Quick Start

```bash
# Set API key (or use Ollama for free)
export OPENAI_API_KEY="your-key"

# Single URL (direct faculty page)
insti-scraper --url "https://university.edu/faculty" --output data.json

# 🆕 Auto-discover faculty pages from ANY URL
insti-scraper --url "https://university.edu" --discover

# 🦙 Use Ollama for FREE local inference
export OLLAMA_BASE_URL="http://localhost:11434"
insti-scraper --url "https://university.edu/faculty" --model "ollama/llama3.1:8b"
```

## Discovery Mode (NEW!)

The scraper can now **automatically find faculty pages** from any university URL:

```bash
# Auto-discover from homepage
insti-scraper --url "https://mit.edu" --discover

# Sitemap-only (fastest, 0 API calls)
insti-scraper --url "https://stanford.edu" --discover --discover-mode sitemap

# Deep crawl (most thorough)
insti-scraper --url "https://columbia.edu" --discover --discover-mode deep

# Batch with discovery
insti-batch --input universities.xlsx --discover --limit 5
```

**Discovery modes:**
- `sitemap` - Fast, uses sitemap.xml (0 API calls)
- `deep` - Thorough, crawls intelligently using keyword scoring
- `auto` - Tries sitemap first, falls back to deep crawl (default)

## 💰 Cost-Saving Tips

### Use Ollama (FREE)

```bash
# Start Ollama
ollama run llama3.1:8b

# Set env var
export OLLAMA_BASE_URL="http://localhost:11434"

# Use with scraper
insti-scraper --url "https://university.edu" --prefer-local

# Or specify model directly
insti-scraper --url "https://university.edu" --model "ollama/llama3.1:8b"
```

**Recommended Ollama models:**
- `ollama/llama3.1:8b` - Best balance
- `ollama/qwen2.5:7b` - Good for structured extraction
- `ollama/mistral:7b` - Fast and reliable

## Batch Processing

```bash
# Standard batch
insti-batch --input universities.xlsx --output-dir ./results

# With discovery (finds faculty pages automatically)
insti-batch --input universities.xlsx --discover

# Check URLs first (no API key needed)
insti-batch --input universities.xlsx --check-urls

# Skip bad URLs
insti-batch --input universities.xlsx --skip-bad
```

## Excel Format

Your Excel file should have a column named `Uni faculty link`:

| Name | Uni faculty link |
|------|------------------|
| MIT | https://mit.edu |
| Stanford | https://stanford.edu |

> **Tip:** With `--discover`, you can use any URL (homepage, department page, etc.)

## Batch Output

```
batch_results/
├── MIT_20241218_120000.json           # Individual results
├── Stanford_20241218_120100.json
├── batch_summary_20241218_120200.json # Overall summary
├── bad_links_20241218_120200.json     # 🔴 Problem URLs
└── warnings_20241218_120200.json      # ⚠️ URLs needing review
```

## CLI Reference

### insti-scraper

```bash
insti-scraper --url URL [options]

Options:
  --url URL              Target URL (required)
  --output FILE          Output JSON file (default: faculty_data.json)
  --model MODEL          LLM model (default: gpt-4o-mini)
  --discover             Enable auto-discovery from any URL
  --discover-mode MODE   sitemap, deep, or auto (default: auto)
  --prefer-local         Prefer Ollama when available
```

### insti-batch

```bash
insti-batch --input FILE [options]

Options:
  --input FILE           Input Excel file (required)
  --output-dir DIR       Output directory (default: ./batch_results)
  --model MODEL          LLM model
  --limit N              Process only first N universities
  --discover             Enable auto-discovery
  --discover-mode MODE   sitemap, deep, or auto
  --prefer-local         Prefer Ollama when available
  --check-urls           Dry-run, check URLs only
  --skip-bad             Skip bad quality URLs
```

## Development

```bash
make dev      # Install with dev deps
make lint     # Run linter
make test     # Run tests
make clean    # Remove artifacts
```

## License

MIT

