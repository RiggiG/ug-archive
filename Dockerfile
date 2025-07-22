# Ultimate Guitar Archive Scraper Docker Container
# Based on Ubuntu 24.04 LTS with Python 3, Chromium, and ChromeDriver

FROM ubuntu:24.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99
ENV RUNNING_IN_CONTAINER=true

# Create app directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # Python and pip
    python3 \
    python3-pip \
    python3-venv \
    # Chromium and dependencies
    chromium-browser \
    chromium-chromedriver \
    # Additional dependencies for Chromium
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    # Virtual display for headless operation
    xvfb \
    # Utilities
    wget \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic link for chromium-browser to chrome (for compatibility)
RUN ln -sf /usr/bin/chromium-browser /usr/bin/google-chrome

# Copy requirements file first (for better Docker layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the main application
COPY main.py .
COPY README.md .

# Create output directory
RUN mkdir -p /app/output

# Create a non-root user for security
RUN useradd -m -u 1000 scraper && \
    chown -R scraper:scraper /app
USER scraper

# Set up environment for Chrome/Chromium
ENV CHROME_BIN=/usr/bin/chromium-browser
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Default command
CMD ["python3", "main.py", "--help"]

# Expose volume for output
VOLUME ["/app/output"]
