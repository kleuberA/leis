
from bs4 import BeautifulSoup
import hashlib

def check_html(filepath):
    with open(filepath, 'rb') as f:
        html_bytes = f.read()
    
    html = html_bytes.decode('latin-1', errors='replace')
    print(f"File size: {len(html_bytes)}")
    
    for parser in ['lxml', 'html.parser']:
        try:
            soup = BeautifulSoup(html, parser)
            print(f"Parser '{parser}': Soup len={len(str(soup))}, Art. 1 found: {'Art. 1' in str(soup)}")
        except Exception as e:
            print(f"Parser '{parser}' failed: {e}")

    # Check sample around char 3000
    print("\n--- SAMPLE AROUND 3000 (possible truncation point) ---")
    print(html[2800:3500])

check_html('cache/html/29e352996bdf08ad91f068c1e2847049.html')

check_html('cache/html/29e352996bdf08ad91f068c1e2847049.html')
