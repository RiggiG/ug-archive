sudo apt-get update && sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    fonts-liberation \
    libasound2t64 \
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
    xvfb \
    wget \
    curl \
    unzip

wget -q -O chrome-linux64.zip https://storage.googleapis.com/chrome-for-testing-public/138.0.7204.157/linux64/chrome-linux64.zip && \
    unzip chrome-linux64.zip && \
    rm chrome-linux64.zip && \
    sudo mv chrome-linux64 /opt/chrome/ && \
    sudo ln -sf /opt/chrome/chrome /usr/bin/chromium

wget -q -O chromedriver-linux64.zip https://storage.googleapis.com/chrome-for-testing-public/138.0.7204.157/linux64/chromedriver-linux64.zip && \
    unzip -j chromedriver-linux64.zip chromedriver-linux64/chromedriver && \
    rm chromedriver-linux64.zip && \
    sudo mv chromedriver /usr/bin/
    
python3 -m venv ./venv
source ./venv/bin/activate
pip install --no-cache-dir -r requirements.txt