"""
AFC Knowledge Base Scraper
Runs via GitHub Actions every 3 hours.
Scrapes the AFC website and updates knowledge_base.txt in the repo.
"""

import requests
import re
from datetime import datetime, timezone

SITE_BASE = "https://africanfreefirecommunity.com"
OUTPUT_FILE = "knowledge_base.txt"

# Starting pages — scraper will also discover new links automatically
SEED_PAGES = [
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

# Skip these paths
SKIP_PREFIXES = [
    "/_next", "/static", "/api", "/favicon", "/images",
    "/fonts", "/.well-known", "/login", "/create-account",
]

HEADERS = {"User-Agent": "AFC-Bot-Scraper/1.0"}


def scrape_page(path: str) -> tuple[str, list]:
    """Scrape a page. Returns (text_content, discovered_internal_links)."""
    try:
        url = SITE_BASE + path
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return "", []
        html = resp.text

        # Discover new internal links
        raw_links = re.findall(r'href=["\'](/[^"\'#?]+)["\']', html)
        internal_links = list({
            l for l in raw_links
            if not any(l.startswith(skip) for skip in SKIP_PREFIXES)
            and len(l) > 1
        })

        # Clean text
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        for ent, rep in [
            ("&amp;", "&"), ("&apos;", "'"), ("&#39;", "'"),
            ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " ")
        ]:
            text = text.replace(ent, rep)
        text = re.sub(r"\s{2,}", " ", text).strip()
        return text, internal_links

    except Exception as e:
        print(f"  ⚠️  Failed: {path} — {e}")
        return "", []


def run():
    print(f"🌐 AFC Knowledge Base Scraper — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"   Target: {SITE_BASE}\n")

    pages_to_scrape = list(SEED_PAGES)
    scraped = set()
    sections = [
        "============================",
        "AFC WEBSITE KNOWLEDGE",
        f"Source: {SITE_BASE}",
        f"Last Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "============================",
        "",
    ]

    while pages_to_scrape:
        path = pages_to_scrape.pop(0)
        if path in scraped:
            continue
        scraped.add(path)

        print(f"  Scraping {path}...")
        content, new_links = scrape_page(path)

        if content:
            sections.append(f"\n--- PAGE: {path} ---")
            sections.append(content)
            print(f"  ✅  {len(content):,} chars | {len(new_links)} new links found")

            # Queue newly discovered pages
            for link in new_links:
                if link not in scraped and link not in pages_to_scrape:
                    pages_to_scrape.append(link)
        else:
            print(f"  ⏭️  Skipped (empty/error)")

    output = "\n".join(sections)

    if len(output) > 1000:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\n✅ {OUTPUT_FILE} updated")
        print(f"   Pages scraped: {len(scraped)}")
        print(f"   Total chars:   {len(output):,}")
    else:
        print("\n⚠️  Too little content scraped — file not updated")


if __name__ == "__main__":
    run()
