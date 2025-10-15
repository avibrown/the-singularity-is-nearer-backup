#!/usr/bin/env python3
"""
Script to download and convert geohot's blog posts to PDF.
Checks if PDFs already exist to avoid redundant downloads.
"""

import os
import re
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urljoin, urlparse
import time

try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    print("Warning: weasyprint not installed. Install with: pip install weasyprint")


def sanitize_filename(title):
    """Convert blog title to valid filename."""
    # Remove or replace invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '', title)
    # Replace spaces with underscores
    filename = filename.replace(' ', '_')
    # Limit length
    filename = filename[:200]
    return filename


def get_blog_posts(base_url):
    """Fetch all blog post URLs from the main blog page."""
    print(f"Fetching blog index from {base_url}")
    response = requests.get(base_url)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Find all blog post links - Jekyll blogs use specific patterns
    blog_links = []
    for link in soup.find_all('a', href=True):
        href = link['href']
        
        # Skip navigation links, anchors, and external links
        if not href or href.startswith('#') or href.startswith('http') or href == '/':
            continue
            
        # Build full URL
        full_url = urljoin(base_url, href)
        
        # Jekyll blog posts typically match pattern: /blog/jekyll/update/YYYY/MM/DD/*.html
        # Also include any .html files under the blog
        if (full_url.startswith(base_url) and 
            full_url != base_url and 
            full_url.endswith('.html')):
            blog_links.append(full_url)
    
    # Remove duplicates and sort for consistent ordering
    blog_links = sorted(list(set(blog_links)))
    print(f"Found {len(blog_links)} blog post links")
    
    # Print first few for debugging
    if blog_links:
        print(f"Sample links:")
        for link in blog_links[:3]:
            print(f"  - {link}")
    
    return blog_links


def get_blog_title(soup):
    """Extract blog post title from HTML."""
    # Try different common title locations
    title = soup.find('h1')
    if title:
        return title.get_text().strip()
    
    title = soup.find('title')
    if title:
        return title.get_text().strip()
    
    # Fallback to first heading
    for heading in ['h2', 'h3']:
        title = soup.find(heading)
        if title:
            return title.get_text().strip()
    
    return "untitled"


def clean_html_for_pdf(soup):
    """Remove problematic elements that cause layout issues in PDF."""
    # Remove header/site-header elements
    for element in soup.find_all(['header', 'nav']):
        element.decompose()
    
    # Remove elements with specific classes that commonly cause issues
    for class_name in ['site-header', 'site-nav', 'page-header', 'site-title', 
                       'site-description', 'trigger', 'page-link']:
        for element in soup.find_all(class_=class_name):
            element.decompose()
    
    # Remove footer elements
    for element in soup.find_all('footer'):
        element.decompose()
    
    # Add inline CSS to prevent overlapping
    style_tag = soup.new_tag('style')
    style_tag.string = """
        body { padding: 20px; }
        .post-content { position: relative; z-index: 1; }
        h1, h2, h3 { break-after: avoid; }
        pre, code { break-inside: avoid; }
    """
    if soup.head:
        soup.head.append(style_tag)
    
    return soup


def extract_date_from_url(url):
    """Extract date from Jekyll blog URL pattern: /YYYY/MM/DD/"""
    import re
    # Match pattern like /2025/10/15/ in the URL
    date_pattern = r'/(\d{4})/(\d{2})/(\d{2})/'
    match = re.search(date_pattern, url)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"
    return None


def download_and_convert_to_pdf(url, output_dir, failed_urls):
    """Download a blog post and convert it to PDF."""
    print(f"\nProcessing: {url}")
    
    # Fetch the blog post
    response = requests.get(url)
    response.raise_for_status()
    
    # Parse HTML
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Get title for filename
    title = get_blog_title(soup)
    filename = sanitize_filename(title)
    
    # If filename is empty or just whitespace, use URL path
    if not filename or filename.isspace():
        parsed_url = urlparse(url)
        filename = parsed_url.path.replace('/', '_').strip('_')
        if not filename:
            filename = 'blog_post'
    
    # Extract date from URL and prepend to filename
    date = extract_date_from_url(url)
    if date:
        filename = f"{date}_{filename}"
    
    pdf_path = output_dir / f"{filename}.pdf"
    
    # Check if PDF already exists
    if pdf_path.exists():
        print(f"  ✓ Already exists: {pdf_path.name}")
        return 'existing'
    
    print(f"  → Creating PDF: {pdf_path.name}")
    
    if not WEASYPRINT_AVAILABLE:
        print(f"  ✗ Cannot create PDF - weasyprint not installed")
        failed_urls.append((url, "weasyprint not installed"))
        return 'error'
    
    try:
        # Clean HTML to remove problematic elements
        cleaned_soup = clean_html_for_pdf(soup)
        cleaned_html = str(cleaned_soup)
        
        # Convert HTML to PDF with warnings suppressed
        from weasyprint.logger import LOGGER
        import logging
        LOGGER.setLevel(logging.ERROR)
        
        html = HTML(string=cleaned_html, base_url=url)
        html.write_pdf(pdf_path)
        print(f"  ✓ Created: {pdf_path.name}")
        return 'success'
    except Exception as e:
        error_msg = str(e)
        print(f"  ✗ Error creating PDF: {error_msg}")
        failed_urls.append((url, error_msg))
        
        # Save HTML content to file as backup when PDF fails
        html_backup_path = output_dir / f"{filename}.html"
        try:
            with open(html_backup_path, 'w', encoding='utf-8') as f:
                f.write(response.text)
            print(f"  → Saved HTML backup: {html_backup_path.name}")
        except Exception as backup_error:
            print(f"  ✗ Failed to save HTML backup: {backup_error}")
        
        return 'error'


def main():
    """Main function to download all blog posts."""
    base_url = "https://geohot.github.io/blog/"
    output_dir = Path("blogs")
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(exist_ok=True)
    
    print("=" * 60)
    print("Geohot Blog Downloader")
    print("=" * 60)
    
    try:
        # Get all blog post URLs
        blog_urls = get_blog_posts(base_url)
        
        if not blog_urls:
            print("\nNo blog posts found!")
            return
        
        print(f"\nProcessing {len(blog_urls)} blog posts...")
        print("-" * 60)
        
        # Track results
        new_count = 0
        existing_count = 0
        error_count = 0
        failed_urls = []
        
        for i, url in enumerate(blog_urls, 1):
            print(f"\n[{i}/{len(blog_urls)}]", end=" ")
            try:
                result = download_and_convert_to_pdf(url, output_dir, failed_urls)
                if result == 'success':
                    new_count += 1
                elif result == 'existing':
                    existing_count += 1
                else:
                    error_count += 1
                    
                # Be respectful with requests
                time.sleep(0.5)
                
            except Exception as e:
                print(f"  ✗ Error: {e}")
                error_count += 1
                failed_urls.append((url, str(e)))
        
        # Summary
        print("\n" + "=" * 60)
        print("Summary:")
        print(f"  New PDFs created: {new_count}")
        print(f"  Already existing: {existing_count}")
        if error_count > 0:
            print(f"  Errors: {error_count}")
        print(f"  Total PDFs in directory: {len(list(output_dir.glob('*.pdf')))}")
        
        # Show failed URLs if any
        if failed_urls:
            print(f"\n  Failed conversions ({len(failed_urls)}):")
            for url, error in failed_urls[:10]:  # Show first 10
                print(f"    - {url}")
                print(f"      Error: {error[:80]}...")  # Truncate long errors
            if len(failed_urls) > 10:
                print(f"    ... and {len(failed_urls) - 10} more")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
