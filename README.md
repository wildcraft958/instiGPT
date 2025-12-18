# InstiGPT Faculty Scraper

AI-powered universal faculty data scraper that extracts professor profiles from university websites.

## Features

- 🔍 **Auto Schema Discovery** - LLM detects page structure automatically
- ⚡ **CSS + LLM Fallback** - Fast CSS extraction with LLM backup
- 📊 **Batch Processing** - Scrape multiple universities from Excel
- 📝 **Detailed Logging** - Debug logs saved to `logs/`

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

## Development

```bash
make dev      # Install with dev deps
make lint     # Run linter
make test     # Run tests
make clean    # Remove artifacts
```

## License

MIT
