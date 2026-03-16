"""
AFC Bot — Website Scraper
==========================
Run this script to re-scrape https://africanfreefirecommunity.com and
refresh the knowledge_base.txt file the bot uses.

Usage:
    python scrape_site.py
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE_URL = "https://africanfreefirecommunity.com"

PAGES = [
    "/home",
    "/about",
    "/rules",
    "/contact",
    "/terms-of-service",
    "/privacy-policy",
    "/tournaments",
    "/teams",
    "/news",
    "/awards",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (AFC-Bot-Scraper/1.0)"
}


def scrape_page(path: str) -> str:
    url = BASE_URL + path
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        # Remove nav, footer, script, style tags
        for tag in soup(["nav", "footer", "script", "style", "img", "button"]):
            tag.decompose()

        # Get main content text
        main = soup.find("main") or soup.find("body")
        if main:
            lines = [line.strip() for line in main.get_text(separator="\n").splitlines()]
            lines = [l for l in lines if l]  # remove blank lines
            return "\n".join(lines)
        return ""
    except Exception as e:
        print(f"  ⚠️  Failed to scrape {url}: {e}")
        return ""


def run():
    print("🌐  Starting AFC website scrape...")
    print(f"    Target: {BASE_URL}")
    print(f"    Pages:  {len(PAGES)}\n")

    sections = [
        f"============================",
        f"AFC KNOWLEDGE BASE",
        f"Source: {BASE_URL}",
        f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"============================\n",
    ]

    for path in PAGES:
        print(f"  Scraping {path}...")
        content = scrape_page(path)
        if content:
            sections.append(f"\n--- PAGE: {path} ---\n{content}\n")
            print(f"  ✅  {path} — {len(content):,} characters")
        else:
            print(f"  ⏭️  {path} — empty/skipped")

    output = "\n".join(sections)

    with open("knowledge_base.txt", "w", encoding="utf-8") as f:
        f.write(output)

    print(f"\n✅  knowledge_base.txt updated — {len(output):,} total characters")
    print("🔄  The bot will use the new content automatically on its next reply.")


if __name__ == "__main__":
    run()
