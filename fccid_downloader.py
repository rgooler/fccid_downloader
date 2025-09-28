#!/usr/bin/env uv run
# /// script
# dependencies = [
#     "requests",
#     "beautifulsoup4",
# ]
# ///
"""
FCC ID PDF Downloader

Downloads all PDF documents associated with a given FCC ID from fccid.io
Usage: uv run fccid_pdf_downloader.py <FCC_ID>
Example: uv run fccid_pdf_downloader.py BCG-E8726A
"""

import os
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import re
from datetime import datetime


class FCCIDDownloader:
    def __init__(self, fcc_id):
        self.fcc_id = fcc_id
        self.base_url = "https://fccid.io"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def get_fcc_page(self):
        """Fetch the main FCC ID page"""
        url = f"{self.base_url}/{self.fcc_id}"
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"Error fetching FCC ID page: {e}")
            return None

    def find_exhibit_links(self, html_content):
        """Extract all exhibit links from the page with their submission dates"""
        soup = BeautifulSoup(html_content, 'html.parser')
        exhibit_links = []

        # Look for the exhibits table
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            if not rows:
                continue

            # Check if this is the exhibits table by looking for headers
            header_row = rows[0]
            headers = [th.get_text(strip=True).lower() for th in header_row.find_all(['th', 'td'])]

            # Look for table with submitted/available column
            if any('submit' in header for header in headers):
                for row in rows[1:]:  # Skip header row
                    cells = row.find_all(['td', 'th'])
                    if len(cells) < 2:
                        continue

                    # Look for any links in this row (not just PDFs)
                    exhibit_link = None
                    for cell in cells:
                        link = cell.find('a', href=True)
                        if link and link['href']:
                            exhibit_link = link
                            break

                    if exhibit_link:
                        # Find the date cell (look for "Submitted available" column)
                        date_text = None
                        for i, header in enumerate(headers):
                            if 'submit' in header and i < len(cells):
                                date_cell = cells[i]
                                date_text = date_cell.get_text(strip=True)
                                # Extract first date from the cell
                                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_text)
                                if date_match:
                                    date_text = date_match.group(1)
                                break

                        full_url = urljoin(self.base_url, exhibit_link['href'])

                        # Get filename from URL or link text
                        filename = os.path.basename(urlparse(exhibit_link['href']).path)
                        if not filename:
                            filename = exhibit_link.get_text(strip=True)
                            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

                        exhibit_links.append({
                            'url': full_url,
                            'filename': filename,
                            'text': exhibit_link.get_text(strip=True),
                            'date': date_text
                        })

        # Fallback: Look for direct PDF links without dates
        if not exhibit_links:
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href.lower().endswith('.pdf'):
                    full_url = urljoin(self.base_url, href)
                    exhibit_links.append({
                        'url': full_url,
                        'filename': os.path.basename(urlparse(href).path),
                        'text': link.get_text(strip=True),
                        'date': None
                    })

        return exhibit_links

    def get_pdf_download_url(self, exhibit_url):
        """Follow an exhibit link to find the actual PDF download URL"""
        try:
            response = self.session.get(exhibit_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Look for download buttons or links
            download_links = []

            # Common patterns for download buttons/links
            for link in soup.find_all('a', href=True):
                href = link['href']
                link_text = link.get_text(strip=True).lower()

                # Look for download-related text or direct PDF links
                if (href.lower().endswith('.pdf') or
                    'download' in link_text or
                    'pdf' in link_text):
                    full_url = urljoin(self.base_url, href)
                    download_links.append(full_url)

            # Look for buttons with download functionality
            for button in soup.find_all(['button', 'input'], type='button'):
                onclick = button.get('onclick', '')
                if 'download' in onclick.lower() or '.pdf' in onclick.lower():
                    # Extract URL from onclick if present
                    url_match = re.search(r'["\']([^"\']*\.pdf[^"\']*)["\']', onclick)
                    if url_match:
                        full_url = urljoin(self.base_url, url_match.group(1))
                        download_links.append(full_url)

            # Return the first valid PDF download link found
            for url in download_links:
                if url.lower().endswith('.pdf'):
                    return url

            return None

        except requests.RequestException as e:
            print(f"Error fetching exhibit page {exhibit_url}: {e}")
            return None

    def download_exhibit(self, exhibit_info, download_dir):
        """Download a single exhibit PDF file"""
        exhibit_url = exhibit_info['url']
        exhibit_name = exhibit_info['text']

        # First, get the actual PDF download URL from the exhibit page
        print(f"Finding PDF download for: {exhibit_name}")
        pdf_url = self.get_pdf_download_url(exhibit_url)

        if not pdf_url:
            print(f"✗ Could not find PDF download link for: {exhibit_name}")
            return False

        # Create filename from exhibit name or use PDF URL
        filename = exhibit_info['filename']
        if not filename or not filename.lower().endswith('.pdf'):
            # Use exhibit name as filename
            filename = exhibit_name
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
            if not filename.lower().endswith('.pdf'):
                filename += '.pdf'

        # Sanitize filename
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filepath = os.path.join(download_dir, filename)

        try:
            print(f"Downloading PDF: {filename}")
            response = self.session.get(pdf_url, timeout=60)
            response.raise_for_status()

            # Check if response is actually a PDF
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' not in content_type and not pdf_url.lower().endswith('.pdf'):
                print(f"✗ Warning: {filename} may not be a PDF (content-type: {content_type})")

            with open(filepath, 'wb') as f:
                f.write(response.content)

            # Set file timestamp if date is available
            if exhibit_info.get('date'):
                try:
                    date_obj = datetime.strptime(exhibit_info['date'], '%Y-%m-%d')
                    timestamp = date_obj.timestamp()
                    os.utime(filepath, (timestamp, timestamp))
                except ValueError:
                    pass  # If date parsing fails, just keep current timestamp

            print(f"✓ Downloaded: {filename} ({len(response.content)} bytes)")
            return True

        except requests.RequestException as e:
            print(f"✗ Failed to download {filename}: {e}")
            return False
        except IOError as e:
            print(f"✗ Failed to save {filename}: {e}")
            return False

    def download_all_exhibits(self):
        """Main method to download all exhibits for the FCC ID"""
        print(f"Fetching FCC ID page for: {self.fcc_id}")

        html_content = self.get_fcc_page()
        if not html_content:
            return False

        exhibit_links = self.find_exhibit_links(html_content)

        if not exhibit_links:
            print("No exhibit documents found for this FCC ID")
            return False

        print(f"Found {len(exhibit_links)} exhibit document(s)")

        # Create download directory
        download_dir = self.fcc_id
        os.makedirs(download_dir, exist_ok=True)

        successful_downloads = 0

        for i, exhibit_info in enumerate(exhibit_links, 1):
            date_info = f" (submitted: {exhibit_info['date']})" if exhibit_info.get('date') else ""
            print(f"\n[{i}/{len(exhibit_links)}] {exhibit_info['text']}{date_info}")

            if self.download_exhibit(exhibit_info, download_dir):
                successful_downloads += 1

            # Be respectful and add a small delay
            time.sleep(1)

        print(f"\nDownload complete!")
        print(f"Successfully downloaded {successful_downloads}/{len(exhibit_links)} exhibit(s)")
        print(f"Files saved to: {os.path.abspath(download_dir)}")

        return successful_downloads > 0


def main():
    if len(sys.argv) != 2:
        print("Usage: uv run fccid_pdf_downloader.py <FCC_ID>")
        print("Example: uv run fccid_pdf_downloader.py BCG-E8726A")
        sys.exit(1)

    fcc_id = sys.argv[1]

    # Validate FCC ID format (basic check)
    if not re.match(r'^[A-Z0-9\-]+$', fcc_id):
        print(f"Warning: '{fcc_id}' doesn't look like a standard FCC ID format")

    downloader = FCCIDDownloader(fcc_id)
    success = downloader.download_all_exhibits()

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
