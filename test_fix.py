
import re
from bs4 import BeautifulSoup

html = '<html><body>Header</body></html><p>Article 1</p></body></html>'

def clean_html_tags(h):
    h = re.sub(r"</body>", "", h, flags=re.IGNORECASE)
    h = re.sub(r"</html>", "", h, flags=re.IGNORECASE)
    return h + "</body></html>"

print(f"Original BS: {BeautifulSoup(html, 'lxml').get_text()}")
print(f"Fixed BS: {BeautifulSoup(clean_html_tags(html), 'lxml').get_text()}")
