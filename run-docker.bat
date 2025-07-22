@echo off
REM Ultimate Guitar Scraper Docker Runner for Windows
REM This script provides easy commands to run the scraper in different modes

setlocal enabledelayedexpansion

REM Default values
set OUTPUT_DIR=.\output
set TABS_DIR=.\tabs
set IMAGE_NAME=ultimate-guitar-scraper

REM Check command
if "%1"=="" goto :usage
if "%1"=="help" goto :usage
if "%1"=="build" goto :build
if "%1"=="test" goto :test
if "%1"=="scrape-only" goto :scrape_only
if "%1"=="download-only" goto :download_only
if "%1"=="full-scrape" goto :full_scrape
if "%1"=="shell" goto :shell
goto :usage

:usage
echo Ultimate Guitar Scraper Docker Runner
echo.
echo Usage: %0 [COMMAND] [OPTIONS]
echo.
echo Commands:
echo   build                   Build the Docker image
echo   test                    Test the Docker setup (build + run tests)
echo   scrape-only            Run in scrape-only mode (metadata collection)
echo   download-only          Run in download-only mode (using existing data)
echo   full-scrape            Run full scraping mode (scrape + download)
echo   help                   Show help message from the scraper
echo   shell                  Start interactive shell in container
echo.
echo Environment Variables:
echo   OUTPUT_DIR             Host output directory (default: .\output)
echo   TABS_DIR               Host tabs directory for existing data (default: .\tabs)
echo.
echo Examples:
echo   %0 build
echo   %0 scrape-only --max-bands 10
echo   %0 download-only --tab-types CRD TAB --include-metadata
goto :end

:build
echo Building Docker image: %IMAGE_NAME%
docker build -t %IMAGE_NAME% .
if %errorlevel% equ 0 (
    echo Build complete!
) else (
    echo Build failed!
    exit /b 1
)
goto :end

:test
call :build
echo Running container tests...
call test-docker.bat
goto :end

:ensure_dirs
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
goto :eof

:scrape_only
call :ensure_dirs
shift
set "args="
:loop1
if "%1"=="" goto :run_scrape_only
set "args=%args% %1"
shift
goto :loop1
:run_scrape_only
echo Running container in scrape-only mode
docker run --rm -v "%cd%\%OUTPUT_DIR%":/app/output %IMAGE_NAME% python3 main.py --scrape-only --outdir /app/output%args%
goto :end

:download_only
call :ensure_dirs
if not exist "%TABS_DIR%" (
    echo Warning: %TABS_DIR% does not exist. Download-only mode requires existing scraped data.
)
shift
set "args="
:loop2
if "%1"=="" goto :run_download_only
set "args=%args% %1"
shift
goto :loop2
:run_download_only
echo Running container in download-only mode
docker run --rm -v "%cd%\%OUTPUT_DIR%":/app/output -v "%cd%\%TABS_DIR%":/app/tabs:ro %IMAGE_NAME% python3 main.py --download-only --local-files-dir /app/tabs --outdir /app/output%args%
goto :end

:full_scrape
call :ensure_dirs
shift
set "args="
:loop3
if "%1"=="" goto :run_full_scrape
set "args=%args% %1"
shift
goto :loop3
:run_full_scrape
echo Running container in full scrape mode
docker run --rm -v "%cd%\%OUTPUT_DIR%":/app/output %IMAGE_NAME% python3 main.py --outdir /app/output%args%
goto :end

:shell
call :ensure_dirs
echo Starting interactive shell in container
docker run --rm -it -v "%cd%\%OUTPUT_DIR%":/app/output -v "%cd%\%TABS_DIR%":/app/tabs:ro %IMAGE_NAME% /bin/bash
goto :end

:end
endlocal
