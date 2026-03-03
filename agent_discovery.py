"""
Discovery Agent — finds model page URLs from a brand's index/models page.
Tries static fetch (httpx + BS4) first, falls back to Playwright for JS-heavy sites.
"""

import json
import sys
import time
import re
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

os.environ.setdefault("PYTHONUTF8", "1")
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
from bs4 import BeautifulSoup

CACHE_DIR = Path(__file__).parent / "discovery_cache"
BRAND_URLS = Path(__file__).parent / "brand_urls.json"
USER_AGENT = "SACarFeedBot/1.0 (+https://github.com/sa-car-feed; data aggregation)"
RATE_LIMIT = 2  # seconds between requests


def load_brand_config(brand_key: str) -> dict:
    with open(BRAND_URLS) as f:
        data = json.load(f)
    for tier in ("tier1", "tier2"):
        if brand_key in data[tier]:
            return data[tier][brand_key]
    raise ValueError(f"Brand '{brand_key}' not found in brand_urls.json")


def check_robots(base_url: str, path: str) -> bool:
    """Check robots.txt — returns True if crawling is allowed."""
    robots_url = urljoin(base_url, "/robots.txt")
    try:
        r = httpx.get(robots_url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=10)
        if r.status_code != 200:
            return True  # can't read robots.txt, assume allowed
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch("*", urljoin(base_url, path))
    except Exception:
        return True  # if robots.txt unreachable, assume allowed


def static_fetch(url: str) -> str | None:
    """Fetch page with httpx. Returns HTML or None on failure."""
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(3):
        try:
            r = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 503):
                print(f"  Rate limited ({r.status_code}), waiting 30s...")
                time.sleep(30)
                continue
            print(f"  HTTP {r.status_code} for {url}")
            return None
        except httpx.RequestError as e:
            print(f"  Request error: {e}")
            if attempt < 2:
                time.sleep(5)
    return None


def playwright_fetch(url: str) -> str | None:
    """Fetch page with Playwright (headless Chromium). Returns HTML or None."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Playwright not installed, skipping JS fallback")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=USER_AGENT)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # Wait for JS rendering of car cards
            page.wait_for_timeout(8000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"  Playwright error: {e}")
        return None


def extract_model_links(html: str, base_url: str, brand_key: str) -> list[dict]:
    """Extract model page links from brand index page HTML."""
    soup = BeautifulSoup(html, "lxml")
    models = []
    seen_urls = set()

    # Common patterns for model links on SA car manufacturer sites
    # Pattern 1: Links containing model-related paths
    model_patterns = [
        r"/models?/",
        r"/vehicles?/",
        r"/range/",
        r"/showroom/",
        r"/cars?/",
        r"/passengercars?/",
    ]

    # Pattern 2: Look for links within model card/tile containers
    card_selectors = [
        "a[href*='/models/']",
        "a[href*='/model/']",
        "a[href*='/vehicles/']",
        "a[href*='/range/']",
        "a[href*='/en/models/']",
        "a[href*='/cars/']",
        "a[href*='/new-cars/']",
        "a[href*='/new-vehicles/']",
        ".model-card a",
        ".vehicle-card a",
        ".model-tile a",
        "[class*='model'] a",
        "[class*='vehicle'] a",
        "[class*='car-card'] a",
        "[data-model] a",
        ".product-card a",
    ]

    for selector in card_selectors:
        for link in soup.select(selector):
            href = link.get("href", "")
            if not href or href == "#":
                continue

            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)

            # Skip if not same domain or subdomain
            base_domain = urlparse(base_url).netloc.replace("www.", "")
            link_domain = parsed.netloc.replace("www.", "")
            if base_domain not in link_domain and link_domain not in base_domain:
                continue

            # Skip index pages, configurators, downloads, etc.
            skip_patterns = [
                r"configurator", r"build-your", r"price-list",
                r"brochure", r"download", r"contact", r"dealer",
                r"finance", r"service", r"accessories", r"#",
                r"compare", r"offers", r"special",
                r"search\.html", r"__app", r"certified",
                r"pre-owned", r"used", r"build-price", r"build-your",
                r"request-a-part", r"recalls?$", r"panel-beater",
                r"book-a-test", r"test-drive$", r"warranty",
                r"parts$", r"owners?$",
            ]
            if any(re.search(p, full_url, re.I) for p in skip_patterns):
                continue

            # Normalize URL — strip query params and trailing slash
            full_url = full_url.split("?")[0].rstrip("/")
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Try to extract model name from link text or URL
            model_name = ""
            text = link.get_text(strip=True)
            if text and len(text) < 60:
                # Clean up text — strip common suffixes
                text = re.sub(r'\.(html?|php|aspx?)$', '', text, flags=re.I)
                text = re.sub(r'\s*(Explore|View|Discover|Learn More|See More).*$', '', text, flags=re.I).strip()
                # Reject if text looks like garbage (price patterns, all-caps junk, too many words)
                is_clean = True
                if re.search(r'R\s*\d{3}', text):  # contains price
                    is_clean = False
                if re.search(r'[A-Z]{5,}', text):  # long uppercase runs
                    is_clean = False
                if len(text.split()) > 6:  # too many words for a model name
                    is_clean = False
                if re.search(r'(FROM|CHOOSE|STARTING|PER MONTH)', text, re.I):
                    is_clean = False
                if text and is_clean:
                    model_name = text

            if not model_name:
                # Extract from URL path
                path_parts = parsed.path.strip("/").split("/")
                if path_parts:
                    slug = path_parts[-1]
                    # Strip file extensions
                    slug = re.sub(r'\.(html?|php|aspx?)$', '', slug, flags=re.I)
                    model_name = slug.replace("-", " ").replace("_", " ").title()

            models.append({
                "model_name": model_name,
                "url": full_url,
            })

    # Fallback: card-based extraction (Toyota-style — buttons, no <a> links)
    # Look for card containers with model names and construct URLs from slug
    if not models:
        card_selectors_nolink = [
            "[class*='card-container']",
            "[class*='vehicle-card']",
            "[class*='model-card']",
            "[class*='product-card']",
        ]
        parsed_base = urlparse(base_url)
        # Figure out the vehicles path from the index URL
        index_parsed = urlparse(soup.find("meta", {"property": "og:url"}) and "" or base_url)
        vehicles_path = urlparse(base_url).path.rstrip("/")

        for selector in card_selectors_nolink:
            cards = soup.select(selector)
            if not cards:
                continue

            for card in cards:
                # Get model name from h2, h3, button[title], or strong
                model_name = ""
                for tag in ["h2", "h3", "h4", "button[title]", "strong", "[class*='title']", "[class*='name']"]:
                    el = card.select_one(tag)
                    if el:
                        model_name = el.get("title", "") or el.get_text(strip=True)
                        if model_name and len(model_name) < 60:
                            break
                        model_name = ""

                if not model_name:
                    continue

                # Skip generic/non-model cards
                if any(kw in model_name.lower() for kw in ["offer", "finance", "service", "compare"]):
                    continue

                # Construct URL from model name slug
                slug = model_name.lower().strip()
                slug = re.sub(r'[^\w\s-]', '', slug)
                slug = re.sub(r'\s+', '-', slug)

                # Use the index URL path to build the model URL
                index_path = urlparse(base_url + "/vehicles").path  # default
                full_url = f"{base_url}/vehicles/{slug}"

                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                models.append({
                    "model_name": model_name,
                    "url": full_url,
                })

            if models:
                break

    # Deduplicate by URL, keeping first occurrence
    final = []
    final_urls = set()
    for m in models:
        if m["url"] not in final_urls:
            final.append(m)
            final_urls.add(m["url"])

    return final


def discover(brand_key: str) -> list[dict]:
    """Main discovery function for a brand."""
    config = load_brand_config(brand_key)
    index_url = config["index_url"]
    base_url = config["base_url"]
    brand_name = config["name"]

    print(f"[Discovery] {brand_name} — {index_url}")

    # Check for manual model list (for bot-protected sites like Ford)
    if "manual_models" in config:
        models = config["manual_models"]
        print(f"  Using manual model list: {len(models)} models")
        # Save to cache
        CACHE_DIR.mkdir(exist_ok=True)
        cache_file = CACHE_DIR / f"{brand_key}.json"
        cache_data = {
            "brand": brand_key, "brand_name": brand_name,
            "index_url": index_url,
            "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model_count": len(models), "models": models,
            "source": "manual",
        }
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=2)
        print(f"  Saved {len(models)} models to {cache_file}")
        return models

    # Check robots.txt
    parsed = urlparse(index_url)
    if not check_robots(base_url, parsed.path):
        print(f"  Blocked by robots.txt: {index_url}")
        return []

    # Try static fetch first
    print("  Trying static fetch...")
    html = static_fetch(index_url)

    models = []
    if html:
        models = extract_model_links(html, base_url, brand_key)
        print(f"  Static fetch found {len(models)} model links")

    # Fall back to Playwright if static fetch found nothing useful
    if len(models) < 2:
        print("  Falling back to Playwright...")
        time.sleep(RATE_LIMIT)
        html = playwright_fetch(index_url)
        if html:
            pw_models = extract_model_links(html, base_url, brand_key)
            print(f"  Playwright found {len(pw_models)} model links")
            if len(pw_models) > len(models):
                models = pw_models

    # Rate limit
    time.sleep(RATE_LIMIT)

    # Save to cache
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{brand_key}.json"
    cache_data = {
        "brand": brand_key,
        "brand_name": brand_name,
        "index_url": index_url,
        "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model_count": len(models),
        "models": models,
    }
    with open(cache_file, "w") as f:
        json.dump(cache_data, f, indent=2)

    print(f"  Saved {len(models)} models to {cache_file}")
    return models


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent_discovery.py <brand_key>")
        print("Example: python agent_discovery.py vw")
        sys.exit(1)

    brand = sys.argv[1].lower()
    results = discover(brand)

    if results:
        print(f"\nDiscovered {len(results)} models:")
        for m in results:
            print(f"  {m['model_name']:30s} {m['url']}")
    else:
        print("\nNo models discovered.")
