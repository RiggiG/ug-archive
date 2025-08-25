#!/usr/bin/env python
'''
This script is for scraping all tabs, artist by artist, from ultimate-guitar.com using the mobile site (as they have removed the download links from the desktop site).
It will iterate over artists from the /bands/ pages, and then iterate through all tabs and try new pages with ?page=2, page=3, etc. until that request is redirected with a 301 response.
It uses Selenium WebDriver to handle HTTP requests with JavaScript rendering and argparse for command-line argument parsing.
'''
import argparse
import glob
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import requests
import json
import os
import re
import time
import random
import functools
import threading
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

BANDS = ['0-9', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z']
SKIP_TAB_TYPES = ['OFFICIAL', 'VID']
# Retry configuration
DEFAULT_RETRY_CONFIG = {
    'max_attempts': 3,
    'base_delay': 1.0,
    'max_delay': 30.0,
    'exponential_base': 2.0,
    'jitter': True
}

# Adaptive delay configuration
ADAPTIVE_DELAY_CONFIG = {
    'initial_delay': 0.0,          # Initial delay between downloads (seconds)
    'max_delay': 10.0,             # Maximum delay between downloads (seconds)
    'failure_threshold': 0.2,      # Failure rate threshold (20%)
    'window_size': 50,             # Number of recent downloads to track
    'delay_increment': 0.5,        # How much to increase delay when failure rate is high
    'delay_decrement': 0.1,        # How much to decrease delay when failure rate is low
    'check_interval': 10           # Check and adjust delay every N downloads
}

class AdaptiveDelayTracker:
    """
    Tracks download failure rates across threads and adjusts delay accordingly.
    Thread-safe implementation for use in multi-threaded download scenarios.
    """
    
    def __init__(self, config=None):
        if config is None:
            config = ADAPTIVE_DELAY_CONFIG.copy()
        
        self.config = config
        self.lock = threading.Lock()
        
        # Tracking variables
        self.current_delay = config['initial_delay']
        self.download_results = []  # List of (success: bool, timestamp: float) tuples
        self.download_count = 0
        self.last_adjustment = 0
        
        # Statistics
        self.total_downloads = 0
        self.total_failures = 0
        
    def record_download(self, success):
        """
        Record the result of a download attempt.
        
        Args:
            success (bool): True if download succeeded, False if failed
        """
        with self.lock:
            timestamp = time.time()
            self.download_results.append((success, timestamp))
            self.download_count += 1
            self.total_downloads += 1
            
            if not success:
                self.total_failures += 1
            
            # Keep only the most recent results within the window
            if len(self.download_results) > self.config['window_size']:
                self.download_results.pop(0)
            
            # Check if we should adjust delay
            if (self.download_count - self.last_adjustment) >= self.config['check_interval']:
                self._adjust_delay()
                self.last_adjustment = self.download_count
    
    def _adjust_delay(self):
        """
        Adjust the current delay based on recent failure rate.
        Must be called with lock held.
        """
        if len(self.download_results) < 5:  # Need minimum data points
            return
        
        # Calculate failure rate from recent downloads
        recent_failures = sum(1 for success, _ in self.download_results if not success)
        failure_rate = recent_failures / len(self.download_results)
        
        # Adjust delay based on failure rate
        if failure_rate > self.config['failure_threshold']:
            # High failure rate - increase delay
            old_delay = self.current_delay
            self.current_delay = min(
                self.current_delay + self.config['delay_increment'],
                self.config['max_delay']
            )
            if self.current_delay > old_delay:
                print(f"\n⚠ High failure rate ({failure_rate:.1%}) detected - increasing delay to {self.current_delay:.1f}s")
        
        elif failure_rate < (self.config['failure_threshold'] * 0.5):
            # Low failure rate - decrease delay
            old_delay = self.current_delay
            self.current_delay = max(
                self.current_delay - self.config['delay_decrement'],
                self.config['initial_delay']
            )
            if self.current_delay < old_delay:
                print(f"\n✓ Low failure rate ({failure_rate:.1%}) detected - decreasing delay to {self.current_delay:.1f}s")
    
    def get_current_delay(self):
        """
        Get the current delay value (thread-safe).
        
        Returns:
            float: Current delay in seconds
        """
        with self.lock:
            return self.current_delay
    
    def get_statistics(self):
        """
        Get current statistics (thread-safe).
        
        Returns:
            dict: Statistics including failure rate, total downloads, etc.
        """
        with self.lock:
            if self.total_downloads == 0:
                overall_failure_rate = 0.0
                recent_failure_rate = 0.0
            else:
                overall_failure_rate = self.total_failures / self.total_downloads
                
                if len(self.download_results) > 0:
                    recent_failures = sum(1 for success, _ in self.download_results if not success)
                    recent_failure_rate = recent_failures / len(self.download_results)
                else:
                    recent_failure_rate = 0.0
            
            return {
                'current_delay': self.current_delay,
                'total_downloads': self.total_downloads,
                'total_failures': self.total_failures,
                'overall_failure_rate': overall_failure_rate,
                'recent_failure_rate': recent_failure_rate,
                'window_size': len(self.download_results)
            }

def with_retry(config=None, retry_on=None):
    """
    Decorator for implementing exponential backoff retry logic.
    
    Args:
        config (dict): Retry configuration with keys:
            - max_attempts (int): Maximum number of retry attempts (default: 3)
            - base_delay (float): Base delay in seconds (default: 1.0)
            - max_delay (float): Maximum delay in seconds (default: 30.0)
            - exponential_base (float): Base for exponential backoff (default: 2.0)
            - jitter (bool): Add random jitter to delays (default: True)
        retry_on (tuple): Exception types to retry on (default: network/timeout exceptions)
    
    Returns:
        Decorated function with retry logic
    """
    if config is None:
        config = DEFAULT_RETRY_CONFIG.copy()
    else:
        # Merge with defaults
        merged_config = DEFAULT_RETRY_CONFIG.copy()
        merged_config.update(config)
        config = merged_config
    
    if retry_on is None:
        retry_on = (
            TimeoutException,
            WebDriverException,
            requests.exceptions.RequestException,
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            Exception  # Catch-all for other network issues
        )
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(config['max_attempts']):
                try:
                    result = func(*args, **kwargs)
                    if attempt > 0:
                        print(f"      ✓ Success on attempt {attempt + 1}")
                    return result
                    
                except retry_on as e:
                    last_exception = e
                    
                    # Don't retry on the last attempt
                    if attempt == config['max_attempts'] - 1:
                        break
                    
                    # Calculate delay with exponential backoff
                    delay = min(
                        config['base_delay'] * (config['exponential_base'] ** attempt),
                        config['max_delay']
                    )
                    
                    # Add jitter to prevent thundering herd
                    if config['jitter']:
                        delay *= (0.5 + random.random() * 0.5)
                    
                    print(f"      ⚠ Attempt {attempt + 1} failed ({type(e).__name__}: {str(e)[:100]}), retrying in {delay:.1f}s...")
                    time.sleep(delay)
                
                except Exception as e:
                    # Don't retry on non-retryable exceptions
                    print(f"      ✗ Non-retryable error: {type(e).__name__}: {e}")
                    raise
            
            # All attempts failed
            print(f"      ✗ All {config['max_attempts']} attempts failed")
            raise last_exception
        
        return wrapper
    return decorator

def validate_js_loading(session, validators, retry_config=None):
    """
    Validate JavaScript loading with retry logic.
    
    Args:
        session: SeleniumSession instance
        validators (dict): Dictionary of validation functions to run
        retry_config (dict): Custom retry configuration
    
    Returns:
        dict: Validation results
    """
    if retry_config is None:
        retry_config = {
            'max_attempts': 5,
            'base_delay': 4.0,
            'max_delay': 20.0
        }
    
    @with_retry(config=retry_config, retry_on=(Exception,))
    def _validate():
        results = {}
        for name, validator_func in validators.items():
            try:
                results[name] = session.driver.execute_script(validator_func)
            except Exception as e:
                print(f"        Validator '{name}' failed: {e}")
                results[name] = False
        
        # Check if critical validators passed
        critical_passed = all(
            results.get(key, False) 
            for key in ['domReady', 'hasContent'] 
            if key in results
        )
        
        if not critical_passed:
            raise Exception("Critical JavaScript validation failed")
        
        return results
    
    return _validate()

class SeleniumSession:
  def __init__(self, user_agent=None, headless=True):
    self.user_agent = user_agent or 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36'
    self.headless = headless
    self.driver = None
    self._setup_driver()
    
  def _setup_driver(self):
    chrome_options = Options()
    if self.headless:
      chrome_options.add_argument("--headless")
    
    # Mobile emulation for mobile site
    chrome_options.add_argument("--user-agent=" + self.user_agent)
    chrome_options.add_argument("--window-size=915,412")  # Mobile viewport, landscape
    
    # Essential Docker/container options - always apply these in containers
    if os.environ.get('RUNNING_IN_CONTAINER'):
      # Core container options
      chrome_options.add_argument("--no-sandbox")
      chrome_options.add_argument("--disable-dev-shm-usage")
      chrome_options.add_argument("--disable-gpu")
      chrome_options.add_argument("--disable-software-rasterizer")
      chrome_options.add_argument("--disable-background-timer-throttling")
      chrome_options.add_argument("--disable-backgrounding-occluded-windows")
      chrome_options.add_argument("--disable-renderer-backgrounding")
      chrome_options.add_argument("--disable-features=TranslateUI")
      chrome_options.add_argument("--disable-ipc-flooding-protection")
      chrome_options.add_argument("--no-zygote")
      chrome_options.add_argument("--single-process")
      chrome_options.add_argument("--remote-debugging-port=9222")
      chrome_options.add_argument("--disable-web-security")
      chrome_options.add_argument("--disable-features=VizDisplayCompositor")
    else:
      # Non-container options
      chrome_options.add_argument("--no-sandbox")
      chrome_options.add_argument("--disable-dev-shm-usage")
      chrome_options.add_argument("--disable-gpu")
    
    # Performance and stability options
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-images")  # Speed up loading
    
    # Enable JavaScript execution
    chrome_options.add_argument("--enable-javascript")
    
    # Shut the hell up Chrome
    chrome_options.add_argument("--enable-unsafe-swiftshader")
    chrome_options.add_argument("--silent")
    chrome_options.add_argument("--log-level=3")
    
    # Set Chrome binary path (for container compatibility)
    chrome_binary = os.environ.get('CHROME_BIN')
    if chrome_binary and os.path.exists(chrome_binary):
      chrome_options.binary_location = chrome_binary
    
    try:
      # Debug logging for container mode
      if os.environ.get('RUNNING_IN_CONTAINER'):
        print("Running in container mode - additional Chrome options applied")
        print(f"Chrome binary: {chrome_options.binary_location}")
        print(f"Chrome arguments: {chrome_options.arguments}")
      
      # Try to use system ChromeDriver first
      chromedriver_path = os.environ.get('CHROMEDRIVER_PATH')
      if chromedriver_path and os.path.exists(chromedriver_path):
        print(f"Using ChromeDriver at: {chromedriver_path}")
        from selenium.webdriver.chrome.service import Service
        service = Service(chromedriver_path)
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
      else:
        print("Using default ChromeDriver from PATH")
        self.driver = webdriver.Chrome(options=chrome_options)
      
      self.driver.implicitly_wait(10)  # 10 second implicit wait
      print("WebDriver initialized successfully")
    except Exception as e:
      print(f"Error setting up Chrome driver: {e}")
      print("Make sure ChromeDriver is installed and in PATH")
      print("For containers, ensure CHROME_BIN and CHROMEDRIVER_PATH are set correctly")
      
      # Additional debugging for container mode
      if os.environ.get('RUNNING_IN_CONTAINER'):
        print("\nContainer debugging info:")
        print(f"  RUNNING_IN_CONTAINER: {os.environ.get('RUNNING_IN_CONTAINER')}")
        print(f"  CHROME_BIN: {os.environ.get('CHROME_BIN')}")
        print(f"  CHROMEDRIVER_PATH: {os.environ.get('CHROMEDRIVER_PATH')}")
        print(f"  Chrome binary exists: {os.path.exists(os.environ.get('CHROME_BIN', ''))}")
        print(f"  ChromeDriver exists: {os.path.exists(os.environ.get('CHROMEDRIVER_PATH', ''))}")
        
        # Try to run chrome directly to see if it works
        import subprocess
        try:
          result = subprocess.run([os.environ.get('CHROME_BIN', 'chromium'), '--version'], 
                                capture_output=True, text=True, timeout=10)
          print(f"  Chrome version check: {result.stdout.strip()}")
        except Exception as chrome_e:
          print(f"  Chrome direct execution failed: {chrome_e}")
      
      import traceback
      traceback.print_exc()
      raise
  
  @with_retry(config=DEFAULT_RETRY_CONFIG)
  def get(self, url, wait_for_element=None, timeout=30):
    """
    Navigate to URL and optionally wait for specific element to load
    """
    try:
      self.driver.get(url)
      
      # Wait for page to load completely
      WebDriverWait(self.driver, timeout).until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
      )
      
      # Wait for specific element if provided
      if wait_for_element:
        WebDriverWait(self.driver, timeout).until(
          EC.presence_of_element_located(wait_for_element)
        )
      
      # Additional wait for React/JS to render
      time.sleep(2)
      
      return SeleniumResponse(self.driver)
      
    except TimeoutException:
      print(f"Timeout waiting for page to load: {url}")
      return SeleniumResponse(self.driver, timeout_occurred=True)
    except Exception as e:
      print(f"Error loading page {url}: {e}")
      return SeleniumResponse(self.driver, error_occurred=True)
  
  def post(self, url, data=None):
    """
    Handle POST requests by executing JavaScript
    """
    # For tab downloads, we'll need to handle this differently
    # For now, fall back to requests for POST operations
    import requests
    session = requests.Session()
    session.headers.update({'User-Agent': self.user_agent})
    return session.post(url, data=data)
  
  def close(self):
    if self.driver:
      self.driver.quit()
  
  def __enter__(self):
    return self
  
  def __exit__(self, exc_type, exc_val, exc_tb):
    self.close()

class SeleniumResponse:
  def __init__(self, driver, timeout_occurred=False, error_occurred=False):
    self.driver = driver
    self.timeout_occurred = timeout_occurred
    self.error_occurred = error_occurred
    
  @property
  def status_code(self):
    try:
      # Check for redirect by comparing current URL with original
      performance_logs = self.driver.execute_script(
        "return window.performance.getEntriesByType('navigation')[0]"
      )
      if performance_logs and performance_logs.get('redirectCount', 0) > 0:
        return 301
      return 200 if not (self.timeout_occurred or self.error_occurred) else 500
    except:
      return 200
  
  @property
  def content(self):
    try:
      return self.driver.page_source.encode('utf-8')
    except:
      return b''
  
  @property
  def text(self):
    try:
      return self.driver.page_source
    except:
      return ''
  
  @property
  def url(self):
    try:
      return self.driver.current_url
    except:
      return ''
  
  def raise_for_status(self):
    if self.error_occurred:
      raise Exception("Request failed")
    if self.timeout_occurred:
      raise Exception("Request timed out")

class Band:
  def __init__(self, id, name, url):
    self.id = id
    self.name = name
    self.url = url
  def add_tab(self, tab):
    if not hasattr(self, 'tabs'):
      self.tabs = {}
    self.tabs[tab.id] = tab
  def _sanitize_folder_name(self, folder_name):
    '''Remove or replace characters that are invalid in folder names'''
    # Replace invalid characters with underscores
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
      folder_name = folder_name.replace(char, '_')
    
    # Remove leading/trailing dots and spaces
    folder_name = folder_name.strip('. ')
    
    # Limit length to avoid filesystem issues
    if len(folder_name) > 100:
      folder_name = folder_name[:100]
    
    return folder_name if folder_name else 'unknown_band'
  def to_dict(self):
    return {
      'id': self.id,
      'name': self.name,
      'url': self.url,
      'tabs': {tab_id: tab.to_dict() for tab_id, tab in getattr(self, 'tabs', {}).items()}
    }

class Tab:
  def __init__(self, id, title, type, url):
    self.id = id
    self.title = title
    self.type = type
    self.url = url
  def download(self, session, include_metadata=False, verbose=True):
    '''
    Downloads the tab content using the provided session.
    The method will depend on the tab type. This function will call the appropriate download method based on the type.
    PRO tabs will download an arbitrary binary file using a POST request mimicking the form submit
    button housed in a section with class "downloadProTab-container". The form class is "downloadProTab-form".
    Other types should be a text file that we generate from the contents of the code element with class `tabContent-code` 
    on the tab page (the link for which we pulled from the href when parsing). Additionally, metadata is extracted from
    the unordered list element with class `tabHeader-info` and included in the text file if include_metadata is True.
    '''
    if self.type.upper() in ['PRO', 'PWR']:
      result = self._download_pro_tab(session, verbose)
      if result and isinstance(result, dict):
        # Store the extension info for later use
        self._pro_download_info = result
        return result['content']
      return result
    else:
      return self._download_regular_tab(session, include_metadata, verbose)
  
  @with_retry(config=DEFAULT_RETRY_CONFIG)
  def _download_pro_tab(self, session, verbose=True):
    '''Download PRO tab as binary file using form submission'''
    try:
      # First get the tab page to find the download form
      wait_element = (By.CSS_SELECTOR, "section.downloadProTab-container")
      response = session.get(self.url, wait_for_element=wait_element, timeout=30)
      
      response.raise_for_status()
      
      # Validate JavaScript execution for PRO download form with retry
      validators = {
        'hasDownloadContainer': """
          const downloadContainer = document.querySelector('section.downloadProTab-container');
          return !!downloadContainer;
        """,
        'hasDownloadForm': """
          const downloadContainer = document.querySelector('section.downloadProTab-container');
          const downloadForm = downloadContainer ? downloadContainer.querySelector('form.downloadProTab-form') : null;
          return !!downloadForm;
        """,
        'domReady': "return document.readyState === 'complete';"
      }
      
      try:
        js_results = validate_js_loading(session, validators)
        if verbose:
          print(f"      JS Validation: Download container: {js_results.get('hasDownloadContainer')}, "
                f"Form: {js_results.get('hasDownloadForm')}, "
                f"DOM ready: {js_results.get('domReady')}")
      except Exception as e:
        if verbose:
          print(f"      JavaScript validation failed for PRO tab {self.id}: {e}")
        return None
      
      soup = BeautifulSoup(response.content, 'html.parser')
      
      # Find the download form
      download_container = soup.find('section', class_='downloadProTab-container')
      if not download_container:
        return None
        
      download_form = download_container.find('form', class_='downloadProTab-form')
      if not download_form:
        return None
      
      # Extract form action and any hidden fields
      form_action = download_form.get('action')
      form_data = {}
      
      # Get all form inputs
      for input_field in download_form.find_all('input'):
        name = input_field.get('name')
        value = input_field.get('value', '')
        if name:
          form_data[name] = value
      
      # Submit the form to download the file using requests module directly
      # (Selenium's POST handling for file downloads can be problematic)
      import requests
      download_url = urljoin(self.url, form_action) if form_action else self.url
      
      # Copy cookies and headers from Selenium session
      cookies = {cookie['name']: cookie['value'] for cookie in session.driver.get_cookies()}
      headers = {
        'User-Agent': session.driver.execute_script("return navigator.userAgent;"),
        'Referer': self.url,
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive'
      }
      
      # Create a requests session for the download
      download_session = requests.Session()
      download_session.cookies.update(cookies)
      download_session.headers.update(headers)
      
      # Download with retry
      @with_retry(config=DEFAULT_RETRY_CONFIG)
      def _download_file():
        download_response = download_session.post(download_url, data=form_data, timeout=30)
        download_response.raise_for_status()
        return download_response
      
      download_response = _download_file()
      
      # Return both content and response for extension detection
      return {
        'content': download_response.content,
        'headers': download_response.headers,
        'url': download_response.url
      }
      
    except Exception as e:
      print(f"Error downloading PRO tab {self.id}: {e}")
      return None
  
  @with_retry(config=DEFAULT_RETRY_CONFIG)
  def _download_regular_tab(self, session, include_metadata=False, verbose=True):
    '''Download regular tab as text from main tab page using tabContent-code (mobile version)'''
    try:
      # Use the actual tab URL from the scraped data
      tab_url = self.url
      
      # Wait for the tabContent-code to load (mobile version)
      wait_element = (By.CSS_SELECTOR, "code.tabContent-code")
      response = session.get(tab_url, wait_for_element=wait_element, timeout=30)
      
      response.raise_for_status()
      
      # Validate JavaScript execution for tab page with retry
      validators = {
        'hasTabContentCode': """
          const tabContentCode = document.querySelector('code.tabContent-code');
          return !!tabContentCode;
        """,
        'hasContent': """
          const tabContentCode = document.querySelector('code.tabContent-code');
          return tabContentCode && tabContentCode.textContent && tabContentCode.textContent.length > 10;
        """,
        'domReady': "return document.readyState === 'complete';"
      }
      
      try:
        js_results = validate_js_loading(session, validators)
        if verbose:
          content_preview = session.driver.execute_script("""
            const tabContentCode = document.querySelector('code.tabContent-code');
            return tabContentCode ? tabContentCode.textContent.substring(0, 100) : null;
          """)
          
          print(f"      JS Validation: Tab content code: {js_results.get('hasTabContentCode')}, "
                f"Content preview: {content_preview[:50] if content_preview else 'None'}..., "
                f"DOM ready: {js_results.get('domReady')}")
      except Exception as e:
        if verbose:
          print(f"      JavaScript validation failed for regular tab {self.id}: {e}")
        return None
      
      soup = BeautifulSoup(response.content, 'html.parser')
      
      # Extract metadata from tabHeader-info only if requested
      metadata = {}
      if include_metadata:
        metadata = self._extract_tab_metadata(soup)

      # Find the code element with tabContent-code class
      tab_content_code = soup.find('code', class_='tabContent-code')
      if not tab_content_code:
        print(f"      No tabContent-code found for tab {self.id}")
        return None

      # Extract text content from the code element, preserving preformatted spacing
      # Use get_text() without separator to maintain exact whitespace formatting
      text_content = tab_content_code.find('pre').get_text()

      if not text_content:
        print(f"      No text content found in tabContent-code for tab {self.id}")
        return None
      
      # Store metadata for later use (even if not including in file)
      self.metadata = metadata
      
      # Combine metadata and tab content only if include_metadata is True
      if include_metadata and metadata:
        metadata_text = self._format_metadata_for_file(metadata)
        full_content = f"{metadata_text}\n\n{text_content}"
      else:
        full_content = text_content
      
      return full_content.encode('utf-8')
      
    except Exception as e:
      print(f"Error downloading regular tab {self.id}: {e}")
      return None
  
  def _extract_tab_metadata(self, soup):
    '''Extract metadata from tabHeader-info unordered list'''
    metadata = {}
    try:
      # Find the tabHeader-info ul element
      tab_header_info = soup.find('ul', class_='tabHeader-info')
      if not tab_header_info:
        return metadata
      
      # Extract each metadata item
      list_items = tab_header_info.find_all('li')
      for item in list_items:
        try:
          # Find the span with tabHeader-name class
          name_span = item.find('span', class_='tabHeader-name')
          if not name_span:
            continue
          
          # Get the header name
          header_name = name_span.get_text(strip=True).rstrip(':')
          
          # Get the value (everything after the span)
          # Remove the span from the item temporarily to get remaining text
          item_copy = item.__copy__()
          name_span_copy = item_copy.find('span', class_='tabHeader-name')
          if name_span_copy:
            name_span_copy.decompose()
          
          value = item_copy.get_text(strip=True)
          
          if header_name and value:
            metadata[header_name] = value
            
        except Exception as e:
          print(f"        Error extracting metadata item: {e}")
          continue
      
    except Exception as e:
      print(f"      Error extracting tab metadata: {e}")
    
    return metadata
  
  def _format_metadata_for_file(self, metadata):
    '''Format metadata for inclusion in tab file'''
    if not metadata:
      return ""
    
    lines = ["=== Tab Metadata ==="]
    for key, value in metadata.items():
      lines.append(f"{key}: {value}")
    lines.append("=" * 20)
    
    return "\n".join(lines)
  def save_to_disk(self, session, artist_folder, include_metadata=False, skip_existing=True, verbose=True, delay_tracker=None):
    '''
    Downloads and saves the tab content to disk.
    Returns the file path if successful, None otherwise.
    
    Args:
      session: SeleniumSession instance
      artist_folder: Directory to save the tab file
      include_metadata: Whether to include metadata in the file
      skip_existing: Skip download if file already exists (default: True)
      verbose: Whether to print detailed progress information (default: True)
      delay_tracker: AdaptiveDelayTracker instance for failure rate tracking
    '''
    try:
      # Create a safe filename from title and type
      safe_title = self._sanitize_filename(self.title)
      safe_type = self._sanitize_filename(self.type)
      base_filename = f"{safe_title}_{safe_type}_{self.id}"
      acceptable_extensions = {
        "PRO": [".gp3", ".gp4", ".gp5", ".gp6", ".gp7", ".gpx", ".tg"],
        "PWR": [".ptb"],
        "TAB": [".txt"],
        "CRD": [".txt"],
      }
      # Use single glob to find any existing files with the base filename
      pattern = os.path.join(artist_folder, f"{base_filename}.*")
      existing_files = glob.glob(pattern)
      if len(existing_files) > 1:
        if verbose:
          print(f"      Warning: Multiple existing files found for tab {self.id}")
        for ef in existing_files:
          if (os.path.basename(ef)).split('.')[-1] not in acceptable_extensions[self.type.upper()]:
            os.remove(ef)
            existing_files.remove(ef)
      existing_file = existing_files[0] if existing_files else None
      
      # Handle existing file based on skip_existing flag
      if existing_file and skip_existing:
        if verbose:
          print(f"      File already exists, skipping: {os.path.basename(existing_file)}")
        return existing_file
      elif existing_file and not skip_existing:
        if verbose:
          print(f"      File already exists, will overwrite: {os.path.basename(existing_file)}")
      
      # Apply adaptive delay before download if delay tracker is provided
      if delay_tracker:
        current_delay = delay_tracker.get_current_delay()
        if current_delay > 0:
          time.sleep(current_delay)
      
      # Download the tab content
      content = self.download(session, include_metadata, verbose)
      if content is None:
        if delay_tracker:
          delay_tracker.record_download(False)
        if verbose:
          print(f"      Failed to download tab {self.id}")
        return None
      
      # Determine the final file path
      if self.type.upper() in ['PRO', 'PWR']:
        # For PRO/PWR tabs, detect extension after download
        extension = self._detect_pro_file_extension()
        filename = f"{base_filename}{extension}"
        filepath = os.path.join(artist_folder, filename)
        
        # If we're overwriting and the extension changed, remove the old file
        if existing_file and existing_file != filepath:
          try:
            os.remove(existing_file)
            if verbose:
              print(f"      Removed old file: {os.path.basename(existing_file)}")
          except Exception as e:
            if verbose:
              print(f"      Warning: Could not remove old file {os.path.basename(existing_file)}: {e}")
      else:
        # Regular tabs use .txt extension
        extension = '.txt'
        filename = f"{base_filename}{extension}"
        filepath = os.path.join(artist_folder, filename)
      
      # Write content to file
      mode = 'wb' if isinstance(content, bytes) else 'w'
      encoding = None if isinstance(content, bytes) else 'utf-8'
      
      with open(filepath, mode, encoding=encoding) as f:
        f.write(content)
      
      # Determine if we're overwriting for the action message
      was_overwritten = existing_file is not None and not skip_existing
      
      # Verify file was written
      if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        if delay_tracker:
          delay_tracker.record_download(True)
        action = "Overwritten" if was_overwritten else "Saved"
        if verbose:
          print(f"      {action}: {filename} ({os.path.getsize(filepath)} bytes)")
        return filepath
      else:
        if delay_tracker:
          delay_tracker.record_download(False)
        if verbose:
          print(f"      Failed to save file or file is empty: {filename}")
        return None
      
    except Exception as e:
      if verbose:
        print(f"      Error saving tab {self.id}: {e}")
      return None
  
  def _detect_pro_file_extension(self):
    '''
    Detect the file extension for PRO tabs based on download info.
    Supports multiple methods for detection:
    1. Tab type (PWR tabs always get .ptb)
    2. Content-Disposition header filename
    3. URL path extension
    4. Content-Type header
    5. File signature/magic bytes (GP4/5/6/7, TuxGuitar, PowerTab)
    
    Returns appropriate extension (.gp4, .gp5, .gp6, .gp7, .ptb, .tg, etc.)
    '''
    # Check if this is a PWR tab first - they always use .ptb
    if hasattr(self, 'type') and self.type.upper() == 'PWR':
      return '.ptb'
    
    download_info = self._pro_download_info
    
    # Try to get extension from Content-Disposition header
    if 'headers' in download_info:
      content_disposition = download_info['headers'].get('Content-Disposition', '')
      if 'filename=' in content_disposition:
        # Extract filename from header like: attachment; filename="song.gp5"
        import re
        filename_match = re.search(r'filename[="]([^"]+)', content_disposition)
        if filename_match:
          filename = filename_match.group(1)
          _, ext = os.path.splitext(filename)
          if ext:
            return ext.lower()
    
    # Try to get extension from URL
    if 'url' in download_info:
      parsed_url = urlparse(download_info['url'])
      _, ext = os.path.splitext(parsed_url.path)
      if ext:
        return ext.lower()
    
    # Try to detect by content type
    if 'headers' in download_info:
      content_type = download_info['headers'].get('Content-Type', '').lower()
      if 'guitar' in content_type or 'gp' in content_type:
        return '.gp5'
      elif 'powertab' in content_type or 'ptb' in content_type:
        return '.ptb'
      elif 'tuxguitar' in content_type or 'tg' in content_type:
        return '.tg'
    
    # Try to detect by file signature/magic bytes
    if 'content' in download_info and download_info['content']:
      content = download_info['content']
      if len(content) >= 4:
        # Guitar Pro 5/6 files typically start with specific signatures
        if content[:4] == b'FICHIER_GUITARE_PRO_':  # GP5
          return '.gp5'
        elif content[:4] == b'FICHIER_GUITAR_PRO_':   # GP4
          return '.gp4'
        elif content[:3] == b'GP6':  # GP6
          return '.gp6'
        elif content[:3] == b'GP7':  # GP7
          return '.gp7'
        elif content[:3] == b'TG':   # TuxGuitar
          return '.tg'
        # PowerTab files often start with 'ptab'
        elif b'ptab' in content[:20].lower():
          return '.ptb'
    
    # Default fallback for PRO tabs
    return '.gp5'
  
  def _sanitize_filename(self, filename):
    '''Remove or replace characters that are invalid in filenames'''
    # Replace invalid characters with underscores
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
      filename = filename.replace(char, '_')
    
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    
    # Limit length to avoid filesystem issues
    if len(filename) > 100:
      filename = filename[:100]
    
    return filename if filename else 'untitled'
  
  def to_dict(self):
    return {
      'id': self.id,
      'title': self.title,
      'type': self.type,
      'url': self.url,
      'file_path': getattr(self, 'file_path', None),
      'metadata': getattr(self, 'metadata', {})
    }

@with_retry(config=DEFAULT_RETRY_CONFIG)
def parse_bands(start, end, session, max_bands=None, existing_bands=None):
  '''
  Base url: /bands/
  Each letter (or number range) page (e.g. `a.htm`) contains a paginated list of bands. 
  The pagination is done with an arbitrary digit added on after the letter, like `a2.htm`, `a3.htm`, etc.
  The band items are list items housed in a div with class "baseListComponent-section".
  Each band is a div with class "listItemElementWrapper-row", which eventually contains a span with class "bandTitle-content"
  wherein there is a link to the artist page. 
  Example of an individual band item:
  ```
  <div class="listItemElementWrapper-row listItemElementWrapper-mobile"><section class="primaryListItemElement-content primaryListItemElement-mobile"><div class="listItemElementCellElement-cell primaryListItemSubtitleElement-subtitle primaryListItemSubtitleElement-fullCell primaryListItemSubtitleElement-mobile listItemElementCellElement-mobile"><span class="bandTitle-content"><a href="/artist/64300" class="linkElement-link linkElement-secondary linkElement-mobile"><span class="styles-tabSubtitle styles-mobile">Пицца Tabs</span></a></span></div></section><section class="primaryListItemElement-metaContent primaryListItemElement-mobile"><div class="listItemElementCellElement-cell primaryListItemElement-meta primaryListItemElement-metaprimary listItemElementCellElement-mobile"><span class="styles-tabCount styles-mobile">12</span> <span class="styles-tabLabel styles-mobile">tabs</span></div></section></div>
  ```
  Returns: A hash of objects, indexed by band ID, each containing the band name and URL.
  '''
  bands = {}
  
  # Get the range of letters to process
  start_idx = BANDS.index(start) if start in BANDS else 0
  end_idx = BANDS.index(end) if end in BANDS else len(BANDS) - 1
  
  for letter in BANDS[start_idx:end_idx + 1]:
    print(f"Processing bands starting with '{letter}'...")
    
    # Start with the first page for this letter
    page = 1
    base_filename = letter
    
    while True:
      # Construct the URL for this page
      if page == 1:
        url = f"https://www.ultimate-guitar.com/bands/{base_filename}.htm"
      else:
        url = f"https://www.ultimate-guitar.com/bands/{base_filename}{page}.htm"
      
      try:
        # Wait for the base list component to load (React component)
        wait_element = (By.CLASS_NAME, "baseListComponent-section")
        response = session.get(url, wait_for_element=wait_element, timeout=30)
        
        # Check for redirect (301 status indicates end of pages)
        if response.status_code == 301:
          print(f"  Reached end of pages for '{letter}' at page {page}")
          break
          
        response.raise_for_status()
        
        # Validate JavaScript execution by checking for React components with retry
        validators = {
          'hasListSection': """
            const listSection = document.querySelector('.baseListComponent-section');
            return !!listSection;
          """,
          'hasBandRows': """
            const bandRows = document.querySelectorAll('.listItemElementWrapper-row');
            return bandRows.length > 0;
          """,
          'hasReactRoot': """
            const reactRoot = document.querySelector('[data-reactroot]') || document.querySelector('#react-root');
            return !!reactRoot;
          """,
          'domReady': "return document.readyState === 'complete';"
        }
        
        try:
          js_results = validate_js_loading(session, validators)
          band_count = session.driver.execute_script("return document.querySelectorAll('.listItemElementWrapper-row').length;")
          
          print(f"  JS Validation: React root: {js_results.get('hasReactRoot')}, "
                f"List section: {js_results.get('hasListSection')}, "
                f"Band rows: {band_count}, "
                f"DOM ready: {js_results.get('domReady')}")
        except Exception as e:
          print(f"  JavaScript validation failed for bands page {page} '{letter}': {e}")
          break
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the base list component section
        list_section = soup.find('div', class_='baseListComponent-section')
        if not list_section:
          print(f"  No bands found on page {page} for '{letter}'")
          break
        
        # Find all band rows
        band_rows = list_section.find_all('span', class_='bandTitle-content')
        
        if not band_rows:
          print(f"  No band rows found on page {page} for '{letter}'")
          break
        
        print(f"  Found {len(band_rows)} bands on page {page} for '{letter}'")
        
        for row in band_rows:
          try:
            # Find the link within the span
            link = row.find('a')
            if not link:
              continue
            
            # Extract band URL and ID
            band_url = link.get('href')
            if not band_url:
              continue
            
            # Extract band ID from URL (e.g., /artist/64300 -> 64300)
            #url_match = re.search(r'\/artist\/\w*?(\d+)', band_url)
            url_match = re.search(r'\/artist\/\w*?(\d+)$', band_url)
            if not url_match:
              continue
            
            band_id = url_match.group(1)
            
            # Skip if this band already exists and skip-existing is enabled
            if existing_bands and band_id in existing_bands:
              print(f"    Skipping existing band: {band_name} ({band_id})")
              continue
            
            # Extract band name
            name_span = link.find('span')
            band_name = name_span.get_text(strip=True) if name_span else link.get_text(strip=True)
            band_name = band_name.replace('Tabs', '').strip()  # Clean up name
            
            # Create full URL
            full_url = urljoin('https://www.ultimate-guitar.com', band_url)
            
            # Create Band object and add to dictionary
            bands[band_id] = Band(band_id, band_name, full_url)
            
            # Check if we've reached the maximum bands limit
            if max_bands and len(bands) >= max_bands:
              print(f"    Reached maximum bands limit ({max_bands}) - stopping band collection")
              break
            
          except Exception as e:
            print(f"    Error processing band row: {e}")
            continue
        
        # Check if we've reached the maximum bands limit before continuing to next page
        if max_bands and len(bands) >= max_bands:
          print(f"  Reached maximum bands limit ({max_bands}) - stopping pagination")
          break
        
        page += 1
        
      except Exception as e:
        print(f"  Error fetching page {page} for '{letter}': {e}")
        break
    
    # Check if we've reached the maximum bands limit before continuing to next letter
    if max_bands and len(bands) >= max_bands:
      print(f"Reached maximum bands limit ({max_bands}) - stopping letter processing")
      break
  
  print(f"Total bands found: {len(bands)}")
  return bands

def get_band_letter_category(band_name):
  '''
  Determine which letter category a band name falls into.
  Returns the appropriate BANDS category ('0-9', 'a', 'b', etc.)
  
  Args:
    band_name (str): The name of the band
    
  Returns:
    str: The letter category ('0-9' for non-alphabetic, or lowercase letter)
  '''
  if not band_name:
    return '0-9'
  
  first_char = band_name.strip().lower()[:1]
  
  # Check if it's a lowercase letter a-z
  if first_char.isalpha() and 'a' <= first_char <= 'z':
    return first_char
  else:
    # Anything else (numbers, symbols, non-Latin characters) goes to '0-9'
    return '0-9'

def download_band_tabs(band, session, base_outdir, include_metadata=False, skip_existing=True, progress_callback=None, thread_id=None, delay_tracker=None):
  '''
  Downloads all tabs for a given band and saves them to disk.
  Creates a folder for the band and saves each tab as a separate file.
  Updates tab objects with file paths.
  
  Args:
    band: Band object containing tabs to download
    session: SeleniumSession instance
    base_outdir: Base output directory
    include_metadata: Whether to include metadata in tab files
    skip_existing: Skip download if file already exists
    progress_callback: Function to call for progress updates (increment-based)
    thread_id: Thread identifier (None if single-threaded, reduces verbosity if set)
    delay_tracker: AdaptiveDelayTracker instance for failure rate tracking
  
  Returns:
    dict: Statistics including tabs processed, downloaded, failed
  '''
  # Determine verbosity based on threading mode
  verbose = thread_id is None  # Verbose only in single-threaded mode
  
  if not hasattr(band, 'tabs') or not band.tabs:
    if verbose:
      print(f"  No tabs to download for {band.name}")
    return {'tabs_processed': 0, 'downloaded_count': 0, 'failed_count': 0}
  
  # Create safe folder name for the band
  safe_band_name = band._sanitize_folder_name(band.name)
  band_folder = os.path.join(base_outdir, f"{safe_band_name}_{band.id}")
  
  # Create the band folder if it doesn't exist
  if not os.path.exists(band_folder):
    os.makedirs(band_folder)
  
  if verbose:
    print(f"  Downloading {len(band.tabs)} tabs to: {band_folder}")
  
  downloaded_count = 0
  failed_count = 0
  tabs_processed = 0
  
  for i, (tab_id, tab) in enumerate(band.tabs.items()):
    try:
      # Call progress callback if provided (increment by 1 for each tab processed)
      if progress_callback:
        progress_callback(1)
      
      file_path = tab.save_to_disk(session, band_folder, include_metadata, skip_existing, verbose, delay_tracker)
      success = file_path is not None
      
      if success:
        tab.file_path = file_path
        downloaded_count += 1
      else:
        failed_count += 1
      
      tabs_processed += 1
      
    except Exception as e:
      # Record failure for tracking
      if delay_tracker:
        delay_tracker.record_download(False)
        
      if verbose:
        print(f"      Error downloading tab {tab_id}: {e}")
      failed_count += 1
      tabs_processed += 1
  
  if verbose:
    print(f"  Downloaded: {downloaded_count} tabs, Failed: {failed_count} tabs")
  
  return {
    'tabs_processed': tabs_processed,
    'downloaded_count': downloaded_count,
    'failed_count': failed_count
  }


def process_band_chunk(band_files_chunk, output_dir, max_tabs_per_band, allowed_types, include_metadata, thread_id, skip_existing=True, progress_callback=None, delay_tracker=None):
  """
  Process a chunk of band files in a single thread.
  Each thread gets its own Selenium session to avoid conflicts.
  
  Args:
    band_files_chunk: List of band file paths to process
    output_dir: Output directory for downloaded tabs
    max_tabs_per_band: Maximum tabs per band to process
    allowed_types: List of allowed tab types
    include_metadata: Whether to include metadata in files
    thread_id: Thread identifier for logging
    skip_existing: Skip download if file already exists
    progress_callback: Function to call for progress updates
    delay_tracker: AdaptiveDelayTracker instance for failure rate tracking
  """
  # Create a separate Selenium session for this thread
  session = SeleniumSession()
  
  try:
    thread_stats = {
      'bands_processed': 0,
      'tabs_found': 0,
      'files_downloaded': 0,
      'files_failed': 0,
      'thread_id': thread_id
    }
    
    print(f"Thread {thread_id}: Processing {len(band_files_chunk)} band files")
    
    for band_file in band_files_chunk:
      try:
        # Load band data from JSON
        with open(band_file, 'r', encoding='utf-8') as f:
          band_data = json.load(f)
        
        # Reconstruct Band object
        band = Band(band_data['id'], band_data['name'], band_data['url'])
        
        # Reconstruct Tab objects
        if 'tabs' in band_data and band_data['tabs']:
          tabs_to_process = band_data['tabs']
          
          # Limit tabs if specified
          if max_tabs_per_band and len(tabs_to_process) > max_tabs_per_band:
            print(f"Thread {thread_id}: Limiting to {max_tabs_per_band} tabs for {band.name} (found {len(tabs_to_process)})")
            # Take the first N tabs
            tabs_items = list(tabs_to_process.items())[:max_tabs_per_band]
            tabs_to_process = dict(tabs_items)
          
          for tab_id, tab_data in tabs_to_process.items():
            # Always skip OFFICIAL and VID tabs
            if tab_data['type'].upper() in SKIP_TAB_TYPES:
              continue
            
            # Filter by allowed types if specified
            if allowed_types and tab_data['type'].upper() not in [t.upper() for t in allowed_types]:
              continue  # Skip this tab if its type is not in the allowed list
            
            tab = Tab(tab_data['id'], tab_data['title'], tab_data['type'], tab_data['url'])
            band.add_tab(tab)
          
          print(f"Thread {thread_id}: Processing band: {band.name} ({band.id}) - {len(band.tabs)} tabs")
          thread_stats['tabs_found'] += len(band.tabs)
          
          # Download tabs for this band with adaptive delay tracking
          download_results = download_band_tabs(band, session, output_dir, include_metadata, skip_existing, progress_callback, thread_id, delay_tracker)
          
          # Update thread statistics
          thread_stats['files_downloaded'] += download_results['downloaded_count']
          thread_stats['files_failed'] += download_results['failed_count']
          
          # Update the band JSON file with file paths
          updated_band_data = band.to_dict()
          with open(band_file, 'w', encoding='utf-8') as f:
            json.dump(updated_band_data, f, indent=2, ensure_ascii=False)
          
          print(f"Thread {thread_id}: Updated band file: {os.path.basename(band_file)}")
          
        else:
          print(f"Thread {thread_id}: No tabs found in band file: {os.path.basename(band_file)}")
        
        thread_stats['bands_processed'] += 1
        
      except Exception as e:
        print(f"Thread {thread_id}: Error processing band file {os.path.basename(band_file)}: {e}")
        continue
    
    print(f"Thread {thread_id}: Completed processing {thread_stats['bands_processed']} bands")
    return thread_stats
    
  finally:
    # Clean up Selenium session for this thread
    try:
      session.close()
    except Exception as e:
      print(f"Thread {thread_id}: Error closing session: {e}")


def process_local_artist_files(local_files_dir, output_dir, session, max_tabs_per_band=None, max_bands=None, allowed_types=None, include_metadata=False, num_threads=1, starting_letter='0-9', end_letter='z', skip_existing=True, disable_adaptive_delay=False):
  '''
  Process existing local artist JSON files to download tabs without scraping.
  This allows downloading tabs from previously scraped metadata.
  Supports parallel processing with multiple threads for faster downloads.
  
  Args:
    local_files_dir (str): Directory containing band JSON files
    output_dir (str): Directory to save downloaded tabs
    session: SeleniumSession instance
    max_tabs_per_band (int): Maximum tabs per band to process
    max_bands (int): Maximum number of bands to process
    allowed_types (list): List of allowed tab types to filter
    include_metadata (bool): Whether to include metadata in tab files
    num_threads (int): Number of parallel threads for processing
    starting_letter (str): Starting letter/category for band filtering
    end_letter (str): Ending letter/category for band filtering
    skip_existing (bool): Skip download if file already exists
    disable_adaptive_delay (bool): Disable adaptive delay tracking for failure rate management
  '''
  if not os.path.exists(local_files_dir):
    print(f"Error: Local files directory does not exist: {local_files_dir}")
    return
  
  # Find all band JSON files
  band_files = []
  for filename in os.listdir(local_files_dir):
    if filename.startswith('band_') and filename.endswith('.json'):
      band_files.append(os.path.join(local_files_dir, filename))
  
  if not band_files:
    print(f"No band JSON files found in: {local_files_dir}")
    return
  
  # Filter band files by letter range if specified
  if starting_letter != '0-9' or end_letter != 'z':
    print(f"Filtering bands by letter range: '{starting_letter}' to '{end_letter}'")
    
    # Get the range of letters to process
    start_idx = BANDS.index(starting_letter) if starting_letter in BANDS else 0
    end_idx = BANDS.index(end_letter) if end_letter in BANDS else len(BANDS) - 1
    allowed_letters = set(BANDS[start_idx:end_idx + 1])
    
    filtered_band_files = []
    for band_file in band_files:
      try:
        # Load band data to get the band name
        with open(band_file, 'r', encoding='utf-8') as f:
          band_data = json.load(f)
        
        band_name = band_data.get('name', '')
        band_letter = get_band_letter_category(band_name)
        
        if band_letter in allowed_letters:
          filtered_band_files.append(band_file)
        else:
          print(f"  Skipping band '{band_name}' (letter '{band_letter}' not in range)")
          
      except Exception as e:
        print(f"  Warning: Could not read band file {os.path.basename(band_file)}: {e}")
        continue
    
    print(f"Filtered {len(band_files)} band files to {len(filtered_band_files)} based on letter range")
    band_files = filtered_band_files
    
    if not band_files:
      print(f"No band files match the letter range '{starting_letter}' to '{end_letter}'")
      return
  
  # Limit bands if specified
  if max_bands and len(band_files) > max_bands:
    print(f"Limiting to {max_bands} band files (found {len(band_files)})")
    band_files = band_files[:max_bands]
  
  print(f"Found {len(band_files)} band files to process")
  
  # Count total tabs for progress tracking
  print("Counting total tabs for progress tracking...")
  total_tabs = 0
  for band_file in band_files:
    try:
      with open(band_file, 'r', encoding='utf-8') as f:
        band_data = json.load(f)
      
      if 'tabs' in band_data and band_data['tabs']:
        tabs_to_process = band_data['tabs']
        
        # Apply same filtering as in processing
        if max_tabs_per_band and len(tabs_to_process) > max_tabs_per_band:
          tabs_to_process = dict(list(tabs_to_process.items())[:max_tabs_per_band])
        
        # Count tabs that would actually be processed
        for tab_data in tabs_to_process.values():
          if tab_data['type'].upper() == 'OFFICIAL':
            continue
          if allowed_types and tab_data['type'].upper() not in [t.upper() for t in allowed_types]:
            continue
          total_tabs += 1
    except Exception as e:
      print(f"  Warning: Could not count tabs in {os.path.basename(band_file)}: {e}")
      continue
  
  print(f"Total tabs to process: {total_tabs}")
  
  # Create progress tracking variables
  processed_tabs = 0
  progress_lock = None
  if num_threads > 1:
    progress_lock = threading.Lock()
  
  def progress_callback(increment=1):
    """
    Thread-safe progress callback that increments the counter.
    Args:
      increment (int): Number of tabs to add to progress (default: 1)
    """
    nonlocal processed_tabs
    if progress_lock:
      with progress_lock:
        processed_tabs += increment
        print(f"\rProgress: {processed_tabs}/{total_tabs} tabs processed", end='', flush=True)
    else:
      processed_tabs += increment
      print(f"Progress: {processed_tabs}/{total_tabs} tabs processed", end='', flush=True)

  if num_threads > 1:
    print(f"Using {num_threads} parallel threads for processing")
    
    # Create shared adaptive delay tracker for failure rate management (unless disabled)
    delay_tracker = None
    if not disable_adaptive_delay:
      delay_tracker = AdaptiveDelayTracker()
      print(f"Adaptive delay tracking enabled - initial delay: {delay_tracker.get_current_delay():.1f}s, "
            f"failure threshold: {delay_tracker.config['failure_threshold']:.1%}")
    else:
      print("Adaptive delay tracking disabled")
    
    # Split band files into chunks for parallel processing
    chunk_size = len(band_files) // num_threads
    if chunk_size == 0:
      chunk_size = 1
      num_threads = len(band_files)  # Adjust threads to match available work
    
    band_chunks = []
    for i in range(0, len(band_files), chunk_size):
      chunk = band_files[i:i + chunk_size]
      if chunk:  # Only add non-empty chunks
        band_chunks.append(chunk)
    
    # If we have leftover files due to uneven division, distribute them
    if len(band_chunks) > num_threads:
      # Merge the last chunk with the second-to-last chunk
      band_chunks[-2].extend(band_chunks[-1])
      band_chunks.pop()
    
    print(f"Split into {len(band_chunks)} chunks: {[len(chunk) for chunk in band_chunks]}")
    
    # Process chunks in parallel using ThreadPoolExecutor
    total_stats = {
      'bands_processed': 0,
      'tabs_found': 0,
      'files_downloaded': 0,
      'files_failed': 0
    }
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
      # Submit all chunks for processing
      future_to_thread = {
        executor.submit(
          process_band_chunk, 
          chunk, 
          output_dir, 
          max_tabs_per_band, 
          allowed_types, 
          include_metadata, 
          i + 1,
          skip_existing,
          progress_callback,
          delay_tracker  # Pass shared delay tracker to all threads
        ): i + 1 
        for i, chunk in enumerate(band_chunks)
      }
      
      # Collect results as they complete
      for future in as_completed(future_to_thread):
        thread_id = future_to_thread[future]
        try:
          thread_stats = future.result()
          total_stats['bands_processed'] += thread_stats['bands_processed']
          total_stats['tabs_found'] += thread_stats['tabs_found']
          total_stats['files_downloaded'] += thread_stats['files_downloaded']
          total_stats['files_failed'] += thread_stats.get('files_failed', 0)
          print(f"Thread {thread_id} completed: {thread_stats['bands_processed']} bands, "
                f"{thread_stats['tabs_found']} tabs, {thread_stats['files_downloaded']} downloads, "
                f"{thread_stats.get('files_failed', 0)} failures")
        except Exception as e:
          print(f"Thread {thread_id} failed with error: {e}")
    
    # Print final delay tracker statistics (if enabled)
    if delay_tracker:
      delay_stats = delay_tracker.get_statistics()
      print(f"\nAdaptive delay final statistics:")
      print(f"  Final delay: {delay_stats['current_delay']:.1f}s")
      print(f"  Total downloads: {delay_stats['total_downloads']}")
      print(f"  Total failures: {delay_stats['total_failures']}")
      print(f"  Overall failure rate: {delay_stats['overall_failure_rate']:.1%}")
      print(f"  Recent failure rate: {delay_stats['recent_failure_rate']:.1%}")
    
    total_bands_processed = total_stats['bands_processed']
    total_tabs_found = total_stats['tabs_found']
    total_files_downloaded = total_stats['files_downloaded']
    
  else:
    # Single-threaded processing (original behavior)
    print("Using single-threaded processing")
    
    total_bands_processed = 0
    total_tabs_found = 0
    total_files_downloaded = 0
    current_tab_count = 0
    
    for band_file in band_files:
      try:
        # Load band data from JSON
        with open(band_file, 'r', encoding='utf-8') as f:
          band_data = json.load(f)
        
        # Reconstruct Band object
        band = Band(band_data['id'], band_data['name'], band_data['url'])
        
        # Reconstruct Tab objects
        if 'tabs' in band_data and band_data['tabs']:
          tabs_to_process = band_data['tabs']
          
          # Limit tabs if specified
          if max_tabs_per_band and len(tabs_to_process) > max_tabs_per_band:
            print(f"  Limiting to {max_tabs_per_band} tabs for {band.name} (found {len(tabs_to_process)})")
            # Take the first N tabs
            tabs_items = list(tabs_to_process.items())[:max_tabs_per_band]
            tabs_to_process = dict(tabs_items)
          
          for tab_id, tab_data in tabs_to_process.items():
            # Always skip OFFICIAL tabs
            if tab_data['type'].upper() == 'OFFICIAL':
              continue
            
            # Filter by allowed types if specified
            if allowed_types and tab_data['type'].upper() not in [t.upper() for t in allowed_types]:
              continue  # Skip this tab if its type is not in the allowed list
            
            tab = Tab(tab_data['id'], tab_data['title'], tab_data['type'], tab_data['url'])
            band.add_tab(tab)
          
          print(f"Processing band: {band.name} ({band.id}) - {len(band.tabs)} tabs")
          total_tabs_found += len(band.tabs)
          
          # Download tabs for this band (single-threaded mode, verbose=True)
          download_results = download_band_tabs(band, session, output_dir, include_metadata, skip_existing, progress_callback, None, None)
          
          # Count successful downloads
          total_files_downloaded += download_results['downloaded_count']
          
          # Update the band JSON file with file paths
          updated_band_data = band.to_dict()
          with open(band_file, 'w', encoding='utf-8') as f:
            json.dump(updated_band_data, f, indent=2, ensure_ascii=False)
          
          print(f"  Updated band file: {os.path.basename(band_file)}")
          
        else:
          print(f"  No tabs found in band file: {os.path.basename(band_file)}")
        
        total_bands_processed += 1
        
      except Exception as e:
        print(f"  Error processing band file {os.path.basename(band_file)}: {e}")
        continue
  
  # Print final newline to complete progress display
  if total_tabs > 0:
    print()  # New line after progress
    
  # Create download summary
  download_summary = {
    'total_bands_processed': total_bands_processed,
    'total_tabs_found': total_tabs_found,
    'total_files_downloaded': total_files_downloaded,
    'download_date': time.strftime('%Y-%m-%d %H:%M:%S'),
    'source_directory': local_files_dir,
    'output_directory': output_dir,
    'letter_range': {
      'starting_letter': starting_letter,
      'end_letter': end_letter
    },
    'max_tabs_per_band': max_tabs_per_band,
    'max_bands': max_bands,
    'allowed_tab_types': allowed_types,
    'num_threads': num_threads
  }
  
  summary_filename = os.path.join(output_dir, "download_summary.json")
  with open(summary_filename, 'w', encoding='utf-8') as f:
    json.dump(download_summary, f, indent=2, ensure_ascii=False)
  
  print(f"\nDownload processing completed!")
  print(f"Total bands processed: {total_bands_processed}")
  print(f"Total tabs found: {total_tabs_found}")
  print(f"Total files downloaded: {total_files_downloaded}")
  print(f"Download summary saved to: {summary_filename}")


@with_retry(config=DEFAULT_RETRY_CONFIG)
def parse_tabs(band_url, session, max_tabs=None, allowed_types=None):
  '''
  Each artist page contains a paginated list of tabs. The pages are set with a query parameter like `?page=2`, `?page=3`, etc.
  An invalid page number will return a 301 redirect, which we can use to stop iterating.
  The tabs are listed in an `article` element with class `ugm-list`. Each tab is then an `a` element with class `ugm-list--link`.
  Each one contains subsections that include the tab title and the type. 
  Example of an individual tab item:
  ```
  <a class="clearfix ugm-list--link ugm-list--link__lined js-tapped js-bottom-sheet-target" href="https://tabs.ultimate-guitar.com/tab/2874578" target="_self" data-tab-id="2874578">
        <section class="ugm-list--link--body">
            <div class="ugm-list--link--link">
                Посолонь             </div>
        </section>
        <section class="ugm-list--link--side">
            <div class="text-left ugm-list--rate">
                            </div>
        </section>
        <section class="ugm-list--link--side">
            <div class="text-right ugm-list--type">
                CRD            </div>
        </section>
    </a>
  ```
  Returns: A hash of objects, indexed by tab ID, each containing the tab title, type, and URL.
  '''
  tabs = {}
  page = 1
  
  while True:
    try:
      # Construct URL for this page
      if page == 1:
        url = band_url
      else:
        separator = '&' if '?' in band_url else '?'
        url = f"{band_url}{separator}page={page}"
      
      # Wait for the tab list to load
      wait_element = (By.CSS_SELECTOR, "article.ugm-list")
      response = session.get(url, wait_for_element=wait_element, timeout=30)
      
      # If we get a redirect (301), we've reached the end of pages
      if response.status_code == 301:
        print(f"    Reached end of pages at page {page}")
        break
        
      response.raise_for_status()
      
      # Validate JavaScript execution by checking for tab list components with retry
      validators = {
        'hasUgmList': """
          const ugmList = document.querySelector('article.ugm-list');
          return !!ugmList;
        """,
        'hasTabLinks': """
          const tabLinks = document.querySelectorAll('a.ugm-list--link');
          return tabLinks.length > 0;
        """,
        'domReady': "return document.readyState === 'complete';"
      }
      
      try:
        js_results = validate_js_loading(session, validators)
        tab_count = session.driver.execute_script("return document.querySelectorAll('a.ugm-list--link').length;")
        
        print(f"    JS Validation: UGM list: {js_results.get('hasUgmList')}, "
              f"Tab links: {tab_count}, "
              f"DOM ready: {js_results.get('domReady')}")
      except Exception as e:
        print(f"    JavaScript validation failed for tabs page {page}: {e}")
        break
      
      soup = BeautifulSoup(response.content, 'html.parser')
      
      # Find the ugm-list article
      ugm_list = soup.find('article', class_='ugm-list')
      if not ugm_list:
        print(f"    No ugm-list found on page {page}")
        break
      
      # Find all tab links
      tab_links = ugm_list.find_all('a', class_='ugm-list--link')
      
      if not tab_links:
        print(f"    No tab links found on page {page}")
        break
      
      print(f"    Found {len(tab_links)} tabs on page {page}")
      
      for link in tab_links:
        try:
          # Extract tab ID from data attribute or URL
          tab_id = link.get('data-tab-id')
          tab_url = link.get('href')
          
          if not tab_id and tab_url:
            # Try to extract ID from URL
            url_match = re.search(r'/tab/(\d+)', tab_url)
            if url_match:
              tab_id = url_match.group(1)
          
          if not tab_id or not tab_url:
            continue
          
          # Extract tab title from the body section
          body_section = link.find('section', class_='ugm-list--link--body')
          if not body_section:
            continue
          
          title_div = body_section.find('div', class_='ugm-list--link--link')
          if not title_div:
            continue
          
          tab_title = title_div.get_text(strip=True)
          
          # Extract tab type from the side section
          tab_type = 'Unknown'
          side_sections = link.find_all('section', class_='ugm-list--link--side')
          for side_section in side_sections:
            type_div = side_section.find('div', class_='ugm-list--type')
            if type_div:
              tab_type = type_div.get_text(strip=True)
              break
          
          # Always skip OFFICIAL and VID tabs
          if tab_type.upper() in SKIP_TAB_TYPES:
            continue
          
          # Filter by allowed types if specified
          if allowed_types and tab_type.upper() not in [t.upper() for t in allowed_types]:
            continue  # Skip this tab if its type is not in the allowed list
          
          # Check if we've reached the maximum tabs limit AFTER filtering
          if max_tabs and len(tabs) >= max_tabs:
            print(f"    Reached maximum tabs limit ({max_tabs}) - stopping tab collection")
            break
          
          # Create full URL if it's relative
          full_url = urljoin('https://www.ultimate-guitar.com', tab_url)
          
          # Create Tab object and add to dictionary
          tabs[tab_id] = Tab(tab_id, tab_title, tab_type, full_url)
          
        except Exception as e:
          print(f"      Error processing tab link: {e}")
          continue
      
      # Check if we've reached the maximum tabs limit before continuing to next page
      if max_tabs and len(tabs) >= max_tabs:
        print(f"    Reached maximum tabs limit ({max_tabs}) - stopping pagination")
        break
      
      page += 1
      
    except Exception as e:
      print(f"    Error fetching page {page}: {e}")
      break
  
  print(f"  Total tabs found: {len(tabs)}")
  return tabs


def save_bands_summary(bands, args, summary_filename):
  '''
  Generate and save the bands summary file
  '''
  # Calculate total tabs and files downloaded
  total_tabs = 0
  total_files_downloaded = 0
  
  summary_bands = {}
  for band_id, band in bands.items():
    tab_count = len(getattr(band, 'tabs', {}))
    total_tabs += tab_count
    
    # Count downloaded files
    files_downloaded = 0
    if hasattr(band, 'tabs') and not args.scrape_only:
      for tab in band.tabs.values():
        if hasattr(tab, 'file_path') and tab.file_path:
          files_downloaded += 1
    
    total_files_downloaded += files_downloaded
    
    summary_bands[band_id] = {
      'name': band.name, 
      'url': band.url, 
      'tab_count': tab_count,
      'files_downloaded': files_downloaded if not args.scrape_only else None
    }
  
  summary_data = {
    'total_bands': len(bands),
    'total_tabs': total_tabs,
    'total_files_downloaded': total_files_downloaded if not args.scrape_only else None,
    'scrape_only_mode': args.scrape_only,
    'bands': summary_bands
  }
  
  with open(summary_filename, 'w', encoding='utf-8') as f:
    json.dump(summary_data, f, indent=2, ensure_ascii=False)
  
  return total_tabs, total_files_downloaded

def load_existing_bands(outdir):
  """
  Load existing band IDs from JSON files and summary file to avoid reprocessing.
  
  Returns:
    set: Set of band IDs that already exist
  """
  existing_bands = set()
  
  # Load from individual band JSON files
  if os.path.exists(outdir):
    for filename in os.listdir(outdir):
      if filename.startswith('band_') and filename.endswith('.json'):
        try:
          # Extract band ID from filename: band_12345.json -> 12345
          band_id = filename[5:-5]  # Remove 'band_' prefix and '.json' suffix
          existing_bands.add(band_id)
        except Exception as e:
          print(f"  Warning: Could not parse band ID from filename {filename}: {e}")
  
  # Load from summary file
  summary_file = os.path.join(outdir, "bands_summary.json")
  if os.path.exists(summary_file):
    try:
      with open(summary_file, 'r', encoding='utf-8') as f:
        summary_data = json.load(f)
      
      if 'bands' in summary_data:
        for band_id in summary_data['bands'].keys():
          existing_bands.add(band_id)
    except Exception as e:
      print(f"  Warning: Could not load summary file {summary_file}: {e}")
  
  return existing_bands

def main():
  parser = argparse.ArgumentParser(description='Scrape tabs from ultimate-guitar.com')
  parser.add_argument('--base-url', type=str, default='https://www.ultimate-guitar.com', help='Base URL of the site to scrape')
  parser.add_argument('--user-agent', type=str, default='Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36', help='User agent string to use for requests')
  parser.add_argument('--starting-letter', type=str, default='0-9', help='Starting position for the band list (default: 0-9)')
  parser.add_argument('--end-letter', type=str, default='z', help='Ending position for the band list (default: z)')
  parser.add_argument('--outdir', type=str, default='./tabs', help='Output directory to save the scraped data')
  parser.add_argument('--max-tabs-per-band', type=int, default=None, help='Maximum number of tabs to download per band (useful for testing)')
  parser.add_argument('--max-bands', type=int, default=None, help='Maximum number of bands to process (useful for testing)')
  parser.add_argument('--tab-types', type=str, nargs='*', default=None, help='Filter tabs by type (e.g., CRD, TAB, PRO, BASS). Can specify multiple types separated by spaces.')
  parser.add_argument('--include-metadata', action='store_true', help='Include metadata header in downloaded tab files (default: False)')
  
  # Retry configuration
  parser.add_argument('--max-retry-attempts', type=int, default=4, help='Maximum number of retry attempts for failed requests (default: 4)')
  parser.add_argument('--retry-base-delay', type=float, default=2.0, help='Base delay in seconds for exponential backoff (default: 2.0)')
  parser.add_argument('--retry-max-delay', type=float, default=30.0, help='Maximum delay in seconds for exponential backoff (default: 30.0)')
  parser.add_argument('--disable-retry-jitter', action='store_true', help='Disable random jitter in retry delays (default: enabled)')
  
  # Adaptive delay configuration (for threaded downloads)
  parser.add_argument('--adaptive-delay-initial', type=float, default=0.0, help='Initial delay between downloads in seconds (default: 0.0)')
  parser.add_argument('--adaptive-delay-max', type=float, default=10.0, help='Maximum delay between downloads in seconds (default: 10.0)')
  parser.add_argument('--adaptive-delay-threshold', type=float, default=0.2, help='Failure rate threshold for increasing delay (default: 0.2 = 20%%)')
  parser.add_argument('--adaptive-delay-window', type=int, default=50, help='Number of recent downloads to track for failure rate (default: 50)')
  parser.add_argument('--adaptive-delay-increment', type=float, default=1, help='How much to increase delay when failure rate is high (default: 1s)')
  parser.add_argument('--adaptive-delay-decrement', type=float, default=0.5, help='How much to decrease delay when failure rate is low (default: 0.5s)')
  parser.add_argument('--adaptive-delay-check-interval', type=int, default=10, help='Check and adjust delay every N downloads (default: 10)')
  parser.add_argument('--disable-adaptive-delay', action='store_true', help='Disable adaptive delay tracking (default: enabled in threaded mode)')
  
  # Scraping control switches
  parser.add_argument('--scrape-only', action='store_true', help='Only scrape bands and tabs metadata, skip downloading tab content')
  parser.add_argument('--download-only', action='store_true', help='Only download tabs using existing local artist files, skip scraping')
  parser.add_argument('--local-files-dir', type=str, default=None, help='Directory containing local artist JSON files (for --download-only mode)')
  parser.add_argument('--input-files-dir', type=str, default=None, dest='local_files_dir', help='Directory containing local artist JSON files (for --download-only mode)')
  parser.add_argument('--skip-existing-bands', action='store_true', help='Skip bands that already have JSON files or entries in summary file (default: False)')
  parser.add_argument('--threads', type=int, default=1, help='Number of parallel threads for download-only mode (default: 1)')
  
  # Tab file handling
  parser.add_argument('--skip-existing-tabs', dest='skip_existing_tabs', action='store_true', default=True, help='Skip downloading tabs if file already exists on disk (default: True)')
  parser.add_argument('--overwrite-existing-tabs', dest='skip_existing_tabs', action='store_false', help='Overwrite existing tab files on disk (opposite of --skip-existing-tabs)')
  
  # Legacy compatibility
  parser.add_argument('--skip-downloads', action='store_true', help='Legacy: same as --scrape-only (for backward compatibility)')
  
  args = parser.parse_args()

  # Handle legacy compatibility and argument validation
  if args.skip_downloads and not args.scrape_only:
    args.scrape_only = True
    print("Note: --skip-downloads is deprecated, use --scrape-only instead")
  
  if args.scrape_only and args.download_only:
    print("Error: Cannot use both --scrape-only and --download-only at the same time")
    return
  
  if args.download_only and not args.local_files_dir:
    args.local_files_dir = args.outdir
    print(f"Note: Using output directory as local files directory: {args.local_files_dir}")
  
  if args.threads < 1:
    print("Error: --threads must be at least 1")
    return
  
  if args.threads > 1 and not args.download_only:
    print("Warning: --threads only applies to download-only mode, ignoring for scraping mode")

  # Configure global retry settings
  global DEFAULT_RETRY_CONFIG
  DEFAULT_RETRY_CONFIG.update({
    'max_attempts': args.max_retry_attempts,
    'base_delay': args.retry_base_delay,
    'max_delay': args.retry_max_delay,
    'jitter': not args.disable_retry_jitter
  })
  
  print(f"Retry configuration: {args.max_retry_attempts} attempts, "
        f"{args.retry_base_delay}s base delay, "
        f"{args.retry_max_delay}s max delay, "
        f"jitter {'disabled' if args.disable_retry_jitter else 'enabled'}")

  # Configure adaptive delay settings
  global ADAPTIVE_DELAY_CONFIG
  ADAPTIVE_DELAY_CONFIG.update({
    'initial_delay': args.adaptive_delay_initial,
    'max_delay': args.adaptive_delay_max,
    'failure_threshold': args.adaptive_delay_threshold,
    'window_size': args.adaptive_delay_window,
    'delay_increment': args.adaptive_delay_increment,
    'delay_decrement': args.adaptive_delay_decrement,
    'check_interval': args.adaptive_delay_check_interval
  })
  
  if args.threads > 1 and not args.disable_adaptive_delay:
    print(f"Adaptive delay configuration: initial={args.adaptive_delay_initial}s, "
          f"max={args.adaptive_delay_max}s, "
          f"threshold={args.adaptive_delay_threshold:.1%}, "
          f"window={args.adaptive_delay_window}")
  elif args.disable_adaptive_delay:
    print("Adaptive delay tracking disabled")
  else:
    print("Adaptive delay tracking only active in multi-threaded mode")

  # Setup Selenium session
  session = SeleniumSession()
  bands = {}  # Initialize bands dictionary for cleanup
  
  try:
    if not os.path.exists(args.outdir):
        os.makedirs(args.outdir)

    if args.download_only:
      # Download-only mode: process existing local files
      print("=== Download-Only Mode ===")
      print(f"Processing local artist files from: {args.local_files_dir}")
      print(f"Output directory: {args.outdir}")
      print(f"Letter range: '{args.starting_letter}' to '{args.end_letter}'")
      if args.max_bands:
        print(f"Max bands to process: {args.max_bands}")
      if args.tab_types:
        print(f"Tab types filter: {', '.join(args.tab_types)}")
      if args.max_tabs_per_band:
        print(f"Max tabs per band: {args.max_tabs_per_band}")
      if args.threads > 1:
        print(f"Parallel threads: {args.threads}")
      if not args.skip_existing_tabs:
        print("Tab file handling: Overwrite existing files")
      else:
        print("Tab file handling: Skip existing files")
      
      process_local_artist_files(args.local_files_dir, args.outdir, session, args.max_tabs_per_band, args.max_bands, args.tab_types, args.include_metadata, args.threads, args.starting_letter, args.end_letter, args.skip_existing_tabs, args.disable_adaptive_delay)
      
    else:
      # Scraping mode (with or without downloads)
      print("=== Scraping Mode ===")
      print(f"Starting scrape from '{args.starting_letter}' to '{args.end_letter}'")
      print(f"Output directory: {args.outdir}")
      if args.max_bands:
        print(f"Max bands to process: {args.max_bands}")
      if args.tab_types:
        print(f"Tab types filter: {', '.join(args.tab_types)}")
      if args.skip_existing_bands:
        print("Skip existing bands: enabled")
      if args.scrape_only:
        print("Scrape-only mode: metadata only, no tab downloads")
      else:
        print("Full mode: scraping + downloading")
        if args.max_tabs_per_band:
          print(f"Max tabs per band: {args.max_tabs_per_band}")
        if not args.skip_existing_tabs:
          print("Tab file handling: Overwrite existing files")
        else:
          print("Tab file handling: Skip existing files")
      
      # Load existing bands if skip-existing is enabled
      existing_bands = set()
      if args.skip_existing_bands:
        existing_bands = load_existing_bands(args.outdir)
        print(f"Found {len(existing_bands)} existing bands to skip")
      
      # Parse all bands in the specified range
      bands = parse_bands(args.starting_letter, args.end_letter, session, args.max_bands, existing_bands)
      
      # For each band, parse their tabs
      for band_id, band in bands.items():
        print(f"Processing band: {band.name} ({band_id})")
        
        try:
          tabs = parse_tabs(band.url, session, args.max_tabs_per_band, args.tab_types)
          
          # Add tabs to band
          for tab_id, tab in tabs.items():
            band.add_tab(tab)
          
          # Download tabs if not in scrape-only mode
          if not args.scrape_only:
            download_band_tabs(band, session, args.outdir, args.include_metadata, args.skip_existing_tabs, None, 0)
          
          # Save band data to individual JSON file
          band_filename = os.path.join(args.outdir, f"band_{band_id}.json")
          with open(band_filename, 'w', encoding='utf-8') as f:
            json.dump(band.to_dict(), f, indent=2, ensure_ascii=False)
          
          print(f"  Saved {len(tabs)} tabs for {band.name}")
          
        except Exception as e:
          print(f"  Error processing band {band.name}: {e}")
          continue
      
      # Save summary file with all bands
      summary_filename = os.path.join(args.outdir, "bands_summary.json")
      total_tabs, total_files_downloaded = save_bands_summary(bands, args, summary_filename)
      
      print(f"\nScraping completed!")
      print(f"Total bands processed: {len(bands)}")
      print(f"Total tabs found: {total_tabs}")
      if not args.scrape_only:
        print(f"Total files downloaded: {total_files_downloaded}")
      print(f"Summary saved to: {summary_filename}")

  except KeyboardInterrupt:
    print("\nInterrupted by user. Saving progress...")
    # Save summary file for any bands that were processed before interruption
    if bands and not args.download_only:
      try:
        summary_filename = os.path.join(args.outdir, "bands_summary.json")
        total_tabs, total_files_downloaded = save_bands_summary(bands, args, summary_filename)
        print(f"Progress saved: {len(bands)} bands, {total_tabs} tabs")
        if not args.scrape_only:
          print(f"Files downloaded: {total_files_downloaded}")
        print(f"Summary saved to: {summary_filename}")
      except Exception as e:
        print(f"Error saving progress: {e}")
    print("Cleaning up...")
  except Exception as e:
    print(f"\nUnexpected error: {e}")
    import traceback
    traceback.print_exc()
  finally:
    # Clean up Selenium session
    try:
      session.close()
    except Exception as e:
      print(f"Error closing session: {e}")


if __name__ == '__main__':
  main()
