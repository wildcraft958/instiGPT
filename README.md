# InstiGPT Faculty Scraper

AI-powered **universal faculty data scraper** that extracts professor profiles from any university website.

## ✅ Current Status

**Version:** 1.0.0 - Universal Scraper  
**Status:** ✅ **Working** - Tested on multiple universities with different structures

### Verified Test Results

| University | Department | Profiles Extracted | Status |
|------------|------------|-------------------|--------|
| MIT NSE | Nuclear Science & Engineering | 24 faculty | ✅ Full details |
| Imperial College | Business School Finance | 54+ faculty | ✅ Full details |

### Sample Extracted Data
```json
{
  "name": "Jacopo Buongiorno",
  "profile_url": "https://nse.mit.edu/people/jacopo-buongiorno/",
  "email": "jacopo@mit.edu",
  "research_interests": ["Nuclear safety", "Floating nuclear power plants", ...],
  "publications": ["Best Paper Award at Proc. ICAPP 2023...", ...]
}
```

## Features

- 🔍 **Universal Auto Schema Discovery** - LLM detects any page structure automatically
- ⚡ **CSS + LLM Fallback** - Fast CSS extraction with intelligent LLM backup
- 🌐 **AJAX Content Support** - Handles JavaScript-loaded dynamic content
- 🤖 **LLM Page Validation** - Semantic classification of faculty directories (90-95% accuracy)
- 📊 **Batch Processing** - Scrape multiple universities from Excel
- 📝 **Detailed Logging** - Debug logs saved to `logs/`
- 🦙 **Ollama Support** - Free local inference with Ollama

## Installation

```bash
# Clone and install
git clone <repo-url>
cd instiGPT
make install

# Setup browser (Playwright)
make setup
```

## Quick Start

```bash
# Set API key (or use Ollama for free)
export OPENAI_API_KEY="your-key"

# Single faculty page (direct)
insti-scraper --url "https://nse.mit.edu/people?people_type=faculty" --output data.json

# 🆕 Auto-discover faculty pages from ANY URL
insti-scraper --url "https://university.edu" --discover

# 🦙 Use Ollama for FREE local inference
export OLLAMA_BASE_URL="http://localhost:11434"
insti-scraper --url "https://university.edu/faculty" --model "ollama/llama3.1:8b"
```

## How It Works

### Universal Extraction Pipeline

1. **AJAX Content Loading** - Waits for JavaScript to load dynamic content (2s + scroll + 1.5s)
2. **LLM Schema Discovery** - Analyzes loaded HTML to generate CSS selectors
3. **CSS Extraction** - Fast extraction using generated selectors
4. **LLM Fallback** - If CSS fails, uses LLM to extract from markdown
5. **Profile Detail Extraction** - Visits each profile page to get full details

### Discovery Mode

The scraper can **automatically find faculty pages** from any university URL:

```bash
# Auto-discover from homepage
insti-scraper --url "https://mit.edu" --discover

# Sitemap-only (fastest, 0 API calls)
insti-scraper --url "https://stanford.edu" --discover --discover-mode sitemap

# Deep crawl (most thorough)
insti-scraper --url "https://columbia.edu" --discover --discover-mode deep
```

**Discovery modes:**
- `sitemap` - Fast, uses sitemap.xml (0 API calls)
- `deep` - Thorough, crawls intelligently with content validation
- `auto` - Tries sitemap first, falls back to deep crawl (default)

## 💰 Cost-Saving Tips

### Use Ollama (FREE)

```bash
# Start Ollama
ollama run llama3.1:8b

# Set env var
export OLLAMA_BASE_URL="http://localhost:11434"

# Use with scraper
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

## ⚠️ Known Limitations

### Current Limitations

1. **AJAX Wait Delay** - Each page requires ~3.5s wait for JavaScript content to load
   - Impact: Slower scraping (3-5s per page)
   - Workaround: None currently, this is necessary for dynamic content

2. **LLM-Generated CSS Selectors** - Sometimes generates incorrect selectors
   - Impact: Falls back to LLM extraction (slower, more API calls)
   - Workaround: LLM fallback handles this automatically

3. **Pagination** - Limited pagination support
   - Impact: May miss faculty on subsequent pages
   - Workaround: Use discovery mode to find all paginated pages

4. **Rate Limiting** - No built-in rate limiting for API calls
   - Impact: May hit API limits on large batches
   - Workaround: Use `--limit N` to process in smaller batches

5. **Profile Page Variations** - Some universities use non-standard profile structures
   - Impact: Detail extraction may be incomplete
   - Workaround: LLM handles most variations automatically

### Known Edge Cases

- `mailto:` links are filtered but may still appear in logs
- Some universities require authentication (not supported)
- Very large departments (200+ faculty) may timeout

## 🚀 Future Work

### Planned Improvements

- [ ] **Smart Pagination** - Automatic "Next" page detection and following
- [ ] **Caching Layer** - Cache successful CSS schemas per domain for reuse
- [ ] **Rate Limiting** - Built-in configurable rate limiting
- [ ] **Retry Logic** - Automatic retry on transient failures
- [ ] **More LLM Providers** - Support for Anthropic Claude, Google Gemini
- [ ] **Parallel Extraction** - Concurrent profile detail extraction
- [ ] **Schema Learning** - Save successful schemas for future runs
- [ ] **Export Formats** - CSV, XLSX, Markdown export options
- [ ] **GUI Dashboard** - Web interface for monitoring batch jobs
- [ ] **Docker Image** - Pre-built container for easy deployment

### Contributions Welcome

Areas where contributions would be helpful:
- Testing on more university websites
- Improving CSS selector generation prompts
- Adding support for new export formats
- Documentation improvements

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
