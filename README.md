# Ultimate Guitar Archive Scraper

This is hastily made, not particularly high quality, and Claude-4 stained. Not looking to win any awards, just looking to preserve the tabs. 

A Python-based web scraper for Ultimate Guitar that extracts tabs, artist information, and metadata using Selenium WebDriver. The scraper supports both mobile site scraping and flexible download modes for comprehensive tab archiving.

## Features

- **Full Site Scraping**: Scrape all bands and tabs from Ultimate Guitar's mobile site
- **Selenium WebDriver**: Handles JavaScript-rendered content and React components
- **Flexible Tab Filtering**: Filter by tab types (CRD, TAB, PRO, BASS, etc.)
- **Metadata Extraction**: Optional metadata headers with rating, difficulty, tuning, etc.
- **Multiple Operating Modes**: Scrape-only, download-only, or combined modes
- **Resume Support**: Process existing scraped data without re-scraping
- **Rate Limiting**: Built-in delays to respect server resources
- **PRO Tab Support**: Downloads binary files for Guitar Pro tabs
## Requirements

- Python 3.7+
- Chrome browser
- ChromeDriver (must be in PATH)
- Required Python packages: `selenium`, `beautifulsoup4`, `requests`

## Installation

### Local Installation

1. Clone this repository
2. Install Chrome and ChromeDriver
3. Install Python dependencies:
   ```bash
   pip install selenium beautifulsoup4 requests
   ```

### Docker Installation (Recommended)

The easiest way to run the scraper is using the provided Docker container which includes all dependencies and is optimized for containerized environments:

```bash
# Build the container
./run-docker.sh build

# Test the container setup
./test-docker.sh

# Run scrape-only mode
./run-docker.sh scrape-only --max-bands 5 --starting-letter a --end-letter a

# Run download-only mode (requires existing scraped data)
./run-docker.sh download-only --tab-types CRD TAB --include-metadata

# Run full scraping mode
./run-docker.sh full-scrape --max-bands 5 --max-tabs-per-band 10
```

The Docker setup automatically detects container environments and applies optimized Chrome settings for better stability and performance.

For detailed Docker usage, see [DOCKER.md](DOCKER.md).

## Usage

### Basic Usage Patterns

#### 1. Full Scraping Mode (Scrape + Download)
```bash
# Scrape all bands and download all tabs
python main.py

# Scrape specific letter range
python main.py --starting-letter a --end-letter c

# Limit scope for testing
python main.py --max-bands 5 --max-tabs-per-band 10
```

#### 2. Scrape-Only Mode (Metadata Only)
```bash
# Scrape metadata without downloading tab content
python main.py --scrape-only

# Scrape with filtering
python main.py --scrape-only --max-bands 10 --tab-types CRD TAB
```

#### 3. Download-Only Mode (Use Existing Data)
```bash
# Download tabs from previously scraped metadata
python main.py --download-only --local-files-dir ./tabs

# Download with filtering and metadata
python main.py --download-only --local-files-dir ./tabs --tab-types CRD --include-metadata
```

### Command Line Arguments

#### Core Arguments
- `--outdir` - Output directory (default: `./tabs`)
- `--starting-letter` - Start position (default: `0-9`)
- `--end-letter` - End position (default: `z`)

#### Filtering Options
- `--max-bands` - Maximum bands to process
- `--max-tabs-per-band` - Maximum tabs per band
- `--tab-types` - Filter by tab types (space-separated list)
  - Common types: `CRD` (chords), `TAB` (tablature), `PRO` (Guitar Pro), `BASS`, `DRUM`, `UKULELE`
  - Example: `--tab-types CRD TAB BASS`

#### Operating Modes
- `--scrape-only` - Only scrape metadata, skip downloads
- `--download-only` - Only download using existing files
- `--local-files-dir` - Directory with existing band JSON files (for download-only)

#### Content Options
- `--include-metadata` - Include metadata headers in downloaded files (default: false)
- `--user-agent` - Custom user agent string
- `--base-url` - Base URL (default: `https://www.ultimate-guitar.com`)

### Advanced Examples

#### Testing Workflow
```bash
# 1. Quick scrape test
python main.py --scrape-only --max-bands 2 --starting-letter a --end-letter a

# 2. Download test with filtering
python main.py --download-only --max-tabs-per-band 3 --tab-types CRD TAB
```

#### Production Workflow
```bash
# 1. Scrape all metadata first
python main.py --scrape-only --outdir ./metadata

# 2. Download filtered content later
python main.py --download-only --local-files-dir ./metadata --tab-types CRD TAB BASS --include-metadata --outdir ./downloads
```

#### Targeted Scraping
```bash
# Rock bands starting with A-D, chords and tabs only
python main.py --starting-letter a --end-letter d --tab-types CRD TAB --include-metadata

# Limit scope for testing
python main.py --max-bands 10 --max-tabs-per-band 5 --tab-types CRD
```

## Output Structure

### Directory Layout
```
tabs/
├── bands_summary.json          # Overview of all scraped bands
├── download_summary.json       # Download statistics (if downloaded)
├── band_12345.json            # Individual band metadata
├── band_67890.json
├── Artist_Name_12345/         # Band-specific folder
│   ├── Song_Title_CRD_123.txt # Regular tab file
│   ├── Song_Title_PRO_456.gp5 # PRO tab file
│   └── ...
└── Another_Artist_67890/
    └── ...
```

### File Formats

#### Regular Tab Files (.txt)
Without metadata:
```
[Intro]
C Am F G

[Verse]
C                Am
This is the song content...
```

With metadata (`--include-metadata`):
```
=== Tab Metadata ===
Rating: ★ 4.5 / 5(1,836)
Difficulty: intermediate
Tuning: E A D G B E
Key: Cm
Author: MusicNArt
====================

[Intro]
C Am F G

[Verse]
C                Am
This is the song content...
```

#### PRO Tab Files
Binary files with appropriate extensions (.gp4, .gp5, .gp6, .gp7, .ptb, .tg) detected automatically.

#### JSON Metadata Files
```json
{
  "id": "12345",
  "name": "Artist Name",
  "url": "https://www.ultimate-guitar.com/artist/12345",
  "tabs": {
    "123": {
      "id": "123",
      "title": "Song Title",
      "type": "CRD",
      "url": "https://tabs.ultimate-guitar.com/tab/123",
      "file_path": "./tabs/Artist_Name_12345/Song_Title_CRD_123.txt",
      "metadata": {...}
    }
  }
}
```

## Tab Type Reference

- **CRD** - Chord charts
- **TAB** - Guitar tablature
- **PRO** - Guitar Pro files (binary)
- **BASS** - Bass tabs
- **DRUM** - Drum tabs
- **UKULELE** - Ukulele tabs
- **PIANO** - Piano arrangements
- **POWER** - Power tabs
- **VIDEO** - Video lessons
- **OFFICIAL** - Official content (automatically skipped)

## Technical Details

### Selenium Configuration
- Chrome browser with mobile emulation (Android viewport)
- JavaScript validation for React components
- Automatic retry logic for late-loading content
- Built-in timeouts and error handling
- Container-optimized settings when running in Docker

### Container Optimizations
- Automatic detection of container environments via `RUNNING_IN_CONTAINER` variable
- Container-specific Chrome flags for better stability
- Optimized for headless operation with virtual display support
- Minimal resource usage with single-process Chrome mode

### Rate Limiting
- 1-second delay between tab downloads
- 2-second wait for JavaScript rendering
- Configurable timeouts for page loads

### Error Handling
- Graceful handling of missing pages (301 redirects)
- Automatic retry for failed JavaScript loads
- Progress saving on keyboard interrupt
- Detailed error logging

## Troubleshooting

### Common Issues

1. **ChromeDriver not found**
   - Ensure ChromeDriver is installed and in your PATH
   - Download from: [https://chromedriver.chromium.org/](https://googlechromelabs.github.io/chrome-for-testing/)

2. **JavaScript not loading**
   - Script includes automatic retries with additional wait time
   - Check internet connection stability

3. **Files not downloading**
   - Verify tab types are not filtered out
   - Check for OFFICIAL tabs (automatically skipped)
   - Ensure sufficient disk space

4. **Large memory usage**
   - Use `--max-bands` and `--max-tabs-per-band` to limit scope
   - Use `--scrape-only` mode first, then `--download-only`

### Performance Tips

1. **Use scrape-then-download workflow** for large collections
2. **Filter by tab types** to reduce download volume
3. **Limit scope** with max-bands/max-tabs-per-band for testing
