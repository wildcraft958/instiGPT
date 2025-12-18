.PHONY: install dev clean lint test run batch help

# Default target
help:
	@echo "InstiGPT Scraper - Available commands:"
	@echo ""
	@echo "  make install    Install package with uv"
	@echo "  make dev        Install with dev dependencies"
	@echo "  make setup      Run crawl4ai setup"
	@echo "  make lint       Run ruff linter"
	@echo "  make test       Run tests"
	@echo "  make clean      Remove build artifacts"
	@echo ""
	@echo "  make run URL=<url>          Scrape single URL"
	@echo "  make batch FILE=<xlsx>      Batch scrape from Excel"

# Installation
install:
	uv pip install -e .

dev:
	uv pip install -e ".[dev]"

setup:
	crawl4ai-setup

# Development
lint:
	ruff check insti_scraper/

test:
	pytest tests/ -v

# Cleaning
clean:
	rm -rf build/ dist/ *.egg-info/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

# Running
run:
ifndef URL
	@echo "Usage: make run URL=https://example.edu/faculty"
else
	python -m insti_scraper --url "$(URL)"
endif

batch:
ifndef FILE
	@echo "Usage: make batch FILE=data.xlsx"
else
	python -m insti_scraper.batch --input "$(FILE)"
endif
