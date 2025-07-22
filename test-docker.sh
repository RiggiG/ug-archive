#!/bin/bash

# Docker Build and Test Script
# This script builds the container and runs basic tests to verify functionality

set -e

IMAGE_NAME="ultimate-guitar-scraper"

echo "=== Building Docker Image ==="
docker build -t "$IMAGE_NAME" .

echo -e "\n=== Testing Container Environment ==="
docker run --rm "$IMAGE_NAME" python3 -c "
import os
print('Python version check: OK')
print('Container mode enabled:', bool(os.environ.get('RUNNING_IN_CONTAINER')))
print('Chrome binary path:', os.environ.get('CHROME_BIN', 'Not set'))
print('ChromeDriver path:', os.environ.get('CHROMEDRIVER_PATH', 'Not set'))
"

echo -e "\n=== Testing Chrome Installation ==="
docker run --rm "$IMAGE_NAME" chromium-browser --version

echo -e "\n=== Testing ChromeDriver Installation ==="
docker run --rm "$IMAGE_NAME" chromedriver --version

echo -e "\n=== Testing Python Dependencies ==="
docker run --rm "$IMAGE_NAME" python3 -c "
try:
    import selenium
    print('Selenium version:', selenium.__version__)
    import requests
    print('Requests available: OK')
    from bs4 import BeautifulSoup
    print('BeautifulSoup available: OK')
    print('All dependencies OK!')
except ImportError as e:
    print('Dependency error:', e)
    exit(1)
"

echo -e "\n=== Testing Application Help ==="
docker run --rm "$IMAGE_NAME" python3 main.py --help

echo -e "\n=== All tests passed! ==="
echo "Container is ready for use."
echo ""
echo "Usage examples:"
echo "  ./run-docker.sh build"
echo "  ./run-docker.sh scrape-only --max-bands 2 --starting-letter a --end-letter a"
echo "  ./run-docker.sh download-only --tab-types CRD TAB"
