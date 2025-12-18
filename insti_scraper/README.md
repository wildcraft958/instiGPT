# InstiGPT Faculty Scraper

A universal AI-powered faculty data scraper that extracts professor profiles from university websites.

## Features

- **Automatic Schema Discovery**: Uses LLM to detect page structure
- **CSS + LLM Fallback**: Fast CSS extraction with LLM fallback for complex pages
- **Detail Extraction**: Scrapes profile pages for emails, research interests, publications

## Installation

```bash
uv pip install -e .
```

## Usage

### Single URL
```bash
python -m insti_scraper --url "https://university.edu/faculty" --output faculty.json
```

### Batch Processing (Excel)
```bash
python -m insti_scraper.batch --input data.xlsx --output-dir ./results
```

## Environment Variables

```bash
export OPENAI_API_KEY="your-api-key"
```

## Logs

Logs are saved to `logs/scraper_YYYYMMDD_HHMMSS.log` with detailed debug info.
