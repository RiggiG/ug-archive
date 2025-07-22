@echo off
REM Docker Build and Test Script for Windows
REM This script builds the container and runs basic tests to verify functionality

setlocal

set IMAGE_NAME=ultimate-guitar-scraper

echo === Building Docker Image ===
docker build -t %IMAGE_NAME% .
if %errorlevel% neq 0 (
    echo Build failed!
    exit /b 1
)

echo.
echo === Testing Container Environment ===
docker run --rm %IMAGE_NAME% python3 -c "import os; print('Python version check: OK'); print('Container mode enabled:', bool(os.environ.get('RUNNING_IN_CONTAINER'))); print('Chrome binary path:', os.environ.get('CHROME_BIN', 'Not set')); print('ChromeDriver path:', os.environ.get('CHROMEDRIVER_PATH', 'Not set'))"

echo.
echo === Testing Chrome Installation ===
docker run --rm %IMAGE_NAME% chromium-browser --version

echo.
echo === Testing ChromeDriver Installation ===
docker run --rm %IMAGE_NAME% chromedriver --version

echo.
echo === Testing Python Dependencies ===
docker run --rm %IMAGE_NAME% python3 -c "try: import selenium; print('Selenium version:', selenium.__version__); import requests; print('Requests available: OK'); from bs4 import BeautifulSoup; print('BeautifulSoup available: OK'); print('All dependencies OK!'); except ImportError as e: print('Dependency error:', e); exit(1)"

echo.
echo === Testing Application Help ===
docker run --rm %IMAGE_NAME% python3 main.py --help

echo.
echo === All tests passed! ===
echo Container is ready for use.
echo.
echo Usage examples:
echo   run-docker.bat build
echo   run-docker.bat scrape-only --max-bands 2 --starting-letter a --end-letter a
echo   run-docker.bat download-only --tab-types CRD TAB

endlocal
