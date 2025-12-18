# InstiGPT Faculty Scraper

AI-powered universal faculty data scraper that extracts professor profiles from university websites.

## Features

- 🔍 **Auto Schema Discovery** - LLM detects page structure automatically
- ⚡ **CSS + LLM Fallback** - Fast CSS extraction with LLM backup
- 📊 **Batch Processing** - Scrape multiple universities from Excel
- 📝 **Detailed Logging** - Debug logs saved to `logs/`

## ⚠️ Known Limitations

> **🔴 IMPORTANT: URL Requirements**
> 
> This scraper works best with **direct faculty/people directory pages**, NOT department landing pages.
> 
> ❌ **Won't work well:**
> - `https://university.edu/engineering/` (department homepage)
> - `https://university.edu/faculties-and-departments/` (lists faculties, not people)
> 
> ✅ **Works best with:**
> - `https://university.edu/people/` (people directory)
> - `https://university.edu/faculty/directory/` (faculty listing)
> - `https://profiles.university.edu/` (profile pages)

> **🔴 Current Shortcomings:**
> - May extract departments/faculties instead of individual professors
> - Duplicate entries possible when same URL appears multiple times
> - No pagination support for large directories yet
> - Some universities require login or have anti-scraping measures

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
# Set API key
export OPENAI_API_KEY="your-key"

# Single URL
insti-scraper --url "https://university.edu/faculty" --output data.json

# Batch from Excel
insti-batch --input universities.xlsx --output-dir ./results --limit 5
```

## Excel Format

Your Excel file should have a column named `Uni faculty link` containing faculty page URLs.

| Name | Uni faculty link |
|------|------------------|
| MIT | https://web.mit.edu/faculty |
| Stanford | https://profiles.stanford.edu |

## Batch Output

The batch scraper automatically detects problematic URLs and generates separate reports:

```
batch_results/
├── MIT_20241218_120000.json          # Individual university data
├── Stanford_20241218_120100.json
├── batch_summary_20241218_120200.json # Overall summary
├── bad_links_20241218_120200.json     # 🔴 Department pages (not faculty)
└── warnings_20241218_120200.json      # ⚠️ URLs needing review
```

**URL Quality Detection:**
- 🔴 **Bad**: `/faculties-and-departments/`, `/engineering/`, `/medicine/` (department pages)
- ✅ **Good**: `/people/`, `/faculty/`, `/profiles/`, `/directory/` (faculty directories)

**Result Quality Assessment:**
- Detects when scraper extracts departments instead of professors
- Flags results with no emails or very few profiles

## Development

```bash
make dev      # Install with dev deps
make lint     # Run linter
make test     # Run tests
make clean    # Remove artifacts
```

## License

MIT
