# Docker Setup Guide

This directory contains a complete Docker setup for the Ultimate Guitar Archive Scraper, packaged as an Ubuntu 24.04 LTS container with all necessary dependencies.

## Quick Start

### 1. Build the Container
```bash
# Linux/macOS
./run-docker.sh build

# Windows
run-docker.bat build

# Or manually
docker build -t ultimate-guitar-scraper .
```

### 2. Run the Scraper
```bash
# Linux/macOS - Scrape metadata only
./run-docker.sh scrape-only --max-bands 5 --starting-letter a --end-letter a

# Windows - Scrape metadata only
run-docker.bat scrape-only --max-bands 5 --starting-letter a --end-letter a
```

## Container Features

### Included Components
- **Ubuntu 24.04 LTS** base image
- **Python 3.12** with pip
- **Chromium browser** and ChromeDriver
- **All Python dependencies** (selenium, beautifulsoup4, requests)
- **Virtual display support** (Xvfb for headless operation)
- **Non-root user** for security

### Container Configuration
- **Working directory**: `/app`
- **Output volume**: `/app/output` (mount your host directory here)
- **Input volume**: `/app/tabs` (for download-only mode with existing data)
- **User**: `scraper` (UID 1000)

## Usage Modes

### 1. Scrape-Only Mode (Metadata Collection)
Collects band and tab metadata without downloading content.

```bash
# Helper script
./run-docker.sh scrape-only --max-bands 10 --tab-types CRD TAB

# Direct Docker command
docker run --rm -v ./output:/app/output ultimate-guitar-scraper \
  python3 main.py --scrape-only --max-bands 10 --outdir /app/output
```

### 2. Download-Only Mode (Using Existing Data)
Downloads tab content using previously scraped metadata.

```bash
# Helper script (requires ./tabs directory with scraped data)
./run-docker.sh download-only --tab-types CRD TAB --include-metadata

# Direct Docker command
docker run --rm \
  -v ./output:/app/output \
  -v ./tabs:/app/tabs:ro \
  ultimate-guitar-scraper \
  python3 main.py --download-only --local-files-dir /app/tabs --outdir /app/output
```

### 3. Full Scraping Mode (Scrape + Download)
Complete workflow: scrape metadata and download content.

```bash
# Helper script
./run-docker.sh full-scrape --max-bands 5 --max-tabs-per-band 10

# Direct Docker command
docker run --rm -v ./output:/app/output ultimate-guitar-scraper \
  python3 main.py --max-bands 5 --max-tabs-per-band 10 --outdir /app/output
```

## Docker Compose

Use docker-compose for more complex configurations:

```bash
# Edit docker-compose.yml command section, then:
docker-compose up

# Or run specific configurations:
docker-compose run --rm ultimate-guitar-scraper python3 main.py --help
```

## Directory Structure

```
project/
├── Dockerfile              # Container definition
├── docker-compose.yml      # Compose configuration
├── run-docker.sh          # Linux/macOS helper script
├── run-docker.bat         # Windows helper script
├── requirements.txt       # Python dependencies
├── main.py               # Scraper application
├── output/               # Output directory (created automatically)
└── tabs/                # Input directory for existing data
```

## Environment Variables

### Container Environment
- `CHROME_BIN`: Path to Chrome binary (`/usr/bin/chromium-browser`)
- `CHROMEDRIVER_PATH`: Path to ChromeDriver (`/usr/bin/chromedriver`)
- `DISPLAY`: Virtual display (`:99`)
- `PYTHONUNBUFFERED`: Unbuffered Python output (`1`)
- `RUNNING_IN_CONTAINER`: Enables container-specific Chrome options (`true`)

### Host Environment
- `OUTPUT_DIR`: Host output directory (default: `./output`)
- `TABS_DIR`: Host tabs directory (default: `./tabs`)

## Advanced Usage

### Custom Output Directory
```bash
# Set custom output directory
OUTPUT_DIR=/path/to/custom/output ./run-docker.sh scrape-only --max-bands 5

# Windows
set OUTPUT_DIR=C:\path\to\custom\output && run-docker.bat scrape-only --max-bands 5
```

### Interactive Shell
```bash
# Debug or manual operation
./run-docker.sh shell

# Or directly
docker run --rm -it -v ./output:/app/output ultimate-guitar-scraper /bin/bash
```

### Background Processing
```bash
# Run in background
docker run -d --name ug-scraper -v ./output:/app/output ultimate-guitar-scraper \
  python3 main.py --scrape-only --max-bands 100

# Check logs
docker logs -f ug-scraper

# Stop when done
docker stop ug-scraper
```

## Troubleshooting

### Common Issues

1. **Permission Denied on Output Directory**
   ```bash
   # Fix permissions (Linux/macOS)
   sudo chown -R 1000:1000 ./output
   ```

2. **Chrome/Chromium Not Starting**
   - Container includes all necessary dependencies
   - Uses headless mode by default
   - Includes `--no-sandbox` for container compatibility

3. **Out of Memory**
   ```bash
   # Increase Docker memory limit or use smaller batches
   docker run --memory=2g --rm -v ./output:/app/output ultimate-guitar-scraper \
     python3 main.py --max-bands 5
   ```

4. **Slow Performance**
   - Use `--max-bands` and `--max-tabs-per-band` to limit scope
   - Consider scrape-then-download workflow for large collections

### Container Debugging

```bash
# Check container health
docker run --rm ultimate-guitar-scraper python3 -c "import selenium; print('Selenium OK')"

# Test Chrome/Chromium
docker run --rm ultimate-guitar-scraper chromium-browser --version

# Test ChromeDriver
docker run --rm ultimate-guitar-scraper chromedriver --version
```

## Production Considerations

### Resource Limits
```bash
# Set memory and CPU limits
docker run --memory=1g --cpus=1.0 --rm -v ./output:/app/output ultimate-guitar-scraper \
  python3 main.py --scrape-only
```

### Data Persistence
```bash
# Use named volumes for better performance
docker volume create ug-output
docker run --rm -v ug-output:/app/output ultimate-guitar-scraper \
  python3 main.py --scrape-only
```

### Monitoring
```bash
# Monitor resource usage
docker stats ug-scraper

# Export container logs
docker logs ug-scraper > scraper.log 2>&1
```

## Helper Scripts Reference

### Linux/macOS (run-docker.sh)
```bash
./run-docker.sh build                    # Build image
./run-docker.sh scrape-only [options]    # Scrape metadata
./run-docker.sh download-only [options]  # Download tabs
./run-docker.sh full-scrape [options]    # Full workflow
./run-docker.sh shell                    # Interactive shell
./run-docker.sh help                     # Show help
```

### Windows (run-docker.bat)
```cmd
run-docker.bat build                    REM Build image
run-docker.bat scrape-only [options]    REM Scrape metadata
run-docker.bat download-only [options]  REM Download tabs
run-docker.bat full-scrape [options]    REM Full workflow
run-docker.bat shell                    REM Interactive shell
```

All scripts support the same command-line arguments as the main application.
