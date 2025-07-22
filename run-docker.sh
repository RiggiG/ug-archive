#!/bin/bash

# Ultimate Guitar Scraper Docker Runner
# This script provides easy commands to run the scraper in different modes

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
OUTPUT_DIR="./output"
TABS_DIR="./tabs"
IMAGE_NAME="ultimate-guitar-scraper"

# Helper functions
print_usage() {
    echo -e "${BLUE}Ultimate Guitar Scraper Docker Runner${NC}"
    echo ""
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  build                   Build the Docker image"
    echo "  test                    Test the Docker setup (build + run tests)"
    echo "  scrape-only            Run in scrape-only mode (metadata collection)"
    echo "  download-only          Run in download-only mode (using existing data)"
    echo "  full-scrape            Run full scraping mode (scrape + download)"
    echo "  help                   Show help message from the scraper"
    echo "  shell                  Start interactive shell in container"
    echo ""
    echo "Environment Variables:"
    echo "  OUTPUT_DIR             Host output directory (default: ./output)"
    echo "  TABS_DIR               Host tabs directory for existing data (default: ./tabs)"
    echo ""
    echo "Examples:"
    echo "  $0 build"
    echo "  $0 scrape-only --max-bands 10"
    echo "  $0 download-only --tab-types CRD TAB --include-metadata"
    echo "  OUTPUT_DIR=/host/path/output $0 full-scrape --starting-letter a --end-letter c"
}

ensure_dirs() {
    mkdir -p "$OUTPUT_DIR"
    if [ "$1" = "download-only" ] && [ ! -d "$TABS_DIR" ]; then
        echo -e "${YELLOW}Warning: $TABS_DIR does not exist. Download-only mode requires existing scraped data.${NC}"
    fi
}

build_image() {
    echo -e "${BLUE}Building Docker image: $IMAGE_NAME${NC}"
    docker build -t "$IMAGE_NAME" .
    echo -e "${GREEN}Build complete!${NC}"
}

run_container() {
    local mode="$1"
    shift
    
    ensure_dirs "$mode"
    
    local docker_args=(
        "run"
        "--rm"
        "-v" "$(realpath "$OUTPUT_DIR"):/app/output"
    )
    
    # Add tabs directory mount for download-only mode
    if [ "$mode" = "download-only" ] && [ -d "$TABS_DIR" ]; then
        docker_args+=("-v" "$(realpath "$TABS_DIR"):/app/tabs:ro")
    fi
    
    docker_args+=("$IMAGE_NAME" "python3" "main.py")
    
    # Add mode-specific arguments
    case "$mode" in
        "scrape-only")
            docker_args+=("--scrape-only" "--outdir" "/app/output")
            ;;
        "download-only")
            docker_args+=("--download-only" "--local-files-dir" "/app/tabs" "--outdir" "/app/output")
            ;;
        "full-scrape")
            docker_args+=("--outdir" "/app/output")
            ;;
        "help")
            docker_args+=("--help")
            ;;
    esac
    
    # Add user-provided arguments
    docker_args+=("$@")
    
    echo -e "${BLUE}Running container with mode: $mode${NC}"
    echo -e "${YELLOW}Command: docker ${docker_args[*]}${NC}"
    echo ""
    
    docker "${docker_args[@]}"
}

run_shell() {
    ensure_dirs
    echo -e "${BLUE}Starting interactive shell in container${NC}"
    docker run --rm -it \
        -v "$(realpath "$OUTPUT_DIR"):/app/output" \
        -v "$(realpath "$TABS_DIR"):/app/tabs:ro" \
        "$IMAGE_NAME" \
        /bin/bash
}

# Main script logic
case "${1:-help}" in
    "build")
        build_image
        ;;
    "test")
        build_image
        echo -e "${BLUE}Running container tests...${NC}"
        ./test-docker.sh
        ;;
    "scrape-only")
        shift
        run_container "scrape-only" "$@"
        ;;
    "download-only")
        shift
        run_container "download-only" "$@"
        ;;
    "full-scrape")
        shift
        run_container "full-scrape" "$@"
        ;;
    "help")
        shift
        run_container "help" "$@"
        ;;
    "shell")
        run_shell
        ;;
    *)
        print_usage
        exit 1
        ;;
esac
