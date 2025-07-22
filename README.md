# Ultimate Guitar Archive Scraper

**Docker Hub:** [riggi/ug-archive](https://hub.docker.com/r/riggi/ug-archive)

Scrapes tabs from ultimate-guitar.com using Selenium WebDriver to handle JavaScript-rendered content.

## Script Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--base-url` | `https://www.ultimate-guitar.com` | Base URL of the site to scrape |
| `--user-agent` | `Mozilla/5.0 (Linux; Android 13; Pixel 7)...` | User agent string for requests |
| `--starting-letter` | `0-9` | Starting position for band list |
| `--end-letter` | `z` | Ending position for band list |
| `--outdir` | `./tabs` | Output directory for scraped data |
| `--max-tabs-per-band` | `None` | Maximum tabs to download per band |
| `--max-bands` | `None` | Maximum bands to process |
| `--tab-types` | `None` | Filter by tab type (CRD, TAB, PRO, BASS) |
| `--include-metadata` | `False` | Include metadata header in tab files |
| `--max-retry-attempts` | `3` | Maximum retry attempts for failed requests |
| `--retry-base-delay` | `1.0` | Base delay for exponential backoff (seconds) |
| `--retry-max-delay` | `30.0` | Maximum delay for exponential backoff (seconds) |
| `--disable-retry-jitter` | `False` | Disable random jitter in retry delays |
| `--scrape-only` | `False` | Only scrape metadata, skip downloading content |
| `--download-only` | `False` | Only download using existing metadata files |
| `--local-files-dir` | Value of `--outdir` | Directory with local artist JSON files |
| `--skip-existing-bands` | `False` | Skip bands that already have JSON files |

## Environment Setup

### Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Install Chrome/Chromium and ChromeDriver for your system
```

### Docker Container
```bash
# Build with your user ID for proper file permissions
docker build --build-arg USER_UID=$(id -u) -t ug-scraper .
# Or pull from Docker Hub, uses UID 1000 and I can't be bothered to apply any further effort
docker pull riggi/ug-archive
```

## Examples

### Virtual Environment

```bash
# Full scrape + download mode, no limits
python main.py

# Scrape-only mode (metadata collection), limited to a maximum of 10 bands
python main.py --scrape-only --max-bands 10 --outdir ./metadata

# Download-only mode (using existing metadata)
python main.py --download-only --local-files-dir ./metadata --outdir ./tabs

# Tab type filtering (chord charts only)
python main.py --tab-types CRD --max-bands 5 --outdir ./chords

# Letter range setting (single letter), only 20 tabs per band, scraping + downloading
python main.py --starting-letter m --end-letter m --max-tabs-per-band 20

# Include metadata headers in downloaded tab files
python main.py --include-metadata --outdir ./tabs_with_metadata
```

### Docker Container

```bash
# Full scrape + download mode, no limits
docker run --rm -v $(pwd)/output:/app/output ug-scraper python main.py --outdir /app/output

# Scrape-only mode (metadata collection), limited to a maximum of 10 bands
docker run --rm -v $(pwd)/metadata:/app/output ug-scraper python main.py --scrape-only --max-bands 10 --outdir /app/output

# Download-only mode (using existing metadata)
docker run --rm -v $(pwd)/data:/app/output ug-scraper python main.py --download-only --local-files-dir /app/output --outdir /app/output

# Tab type filtering (chord charts only)
docker run --rm -v $(pwd)/chords:/app/output ug-scraper python main.py --tab-types CRD --max-bands 5 --outdir /app/output

# Letter range setting (single letter), only 20 tabs per band, scraping + downloading
docker run --rm -v $(pwd)/output:/app/output ug-scraper python main.py --starting-letter m --end-letter m --max-tabs-per-band 20 --outdir /app/output

# Include metadata headers in downloaded tab files
docker run --rm -v $(pwd)/tabs_with_metadata:/app/output ug-scraper python main.py --include-metadata --max-bands 3 --outdir /app/output
```

## Output Structure

- `bands_summary.json` - Overall scraping summary
- `band_{id}.json` - Individual band metadata
- `{Band_Name}_{id}/` - Directory containing tab files
- `download_summary.json` - Download-only mode summary