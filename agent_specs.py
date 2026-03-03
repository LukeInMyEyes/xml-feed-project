"""
Spec Scraper Agent — extracts variant/derivative spec data from a model page.
Handles tables, accordions, tabs, and spec sheets.
Creates one record per variant/derivative.
"""

import json
import sys
import re
import time
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse

# Force UTF-8 output on Windows
os.environ.setdefault("PYTHONUTF8", "1")
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
from bs4 import BeautifulSoup, Tag

RAW_DIR = Path(__file__).parent / "raw_data"
USER_AGENT = "SACarFeedBot/1.0 (+https://github.com/sa-car-feed; data aggregation)"
RATE_LIMIT = 2


def static_fetch(url: str) -> str | None:
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
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=USER_AGENT)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)  # wait for JS rendering
            # Click any "specs" or "specifications" tabs/buttons
            for selector in [
                "text=Specifications", "text=Specs", "text=Technical",
                "[data-tab='specs']", "[data-tab='specifications']",
                "button:has-text('Spec')", "a:has-text('Spec')",
            ]:
                try:
                    el = page.query_selector(selector)
                    if el and el.is_visible():
                        el.click()
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    pass
            # Expand accordions
            for selector in [
                "[class*='accordion'] button",
                "[class*='expand']",
                "[class*='collapse'] .header",
                "details summary",
            ]:
                try:
                    for el in page.query_selector_all(selector):
                        if el.is_visible():
                            el.click()
                            page.wait_for_timeout(300)
                except Exception:
                    pass

            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"  Playwright error: {e}")
        return None


def clean_text(text: str) -> str:
    """Clean whitespace from extracted text."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def parse_price(text: str) -> int | None:
    """Extract numeric price from text like 'R 399 900' or 'From R399,900'."""
    if not text:
        return None
    # Remove currency symbols, spaces, commas
    match = re.search(r'R\s*([\d\s,\.]+)', text)
    if match:
        num_str = match.group(1).replace(' ', '').replace(',', '').replace('.', '')
        try:
            return int(num_str)
        except ValueError:
            pass
    return None


def extract_spec_tables(soup: BeautifulSoup) -> list[dict]:
    """Extract spec data from HTML tables."""
    specs = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                key = clean_text(cells[0].get_text())
                val = clean_text(cells[1].get_text())
                if key and val and len(key) < 100:
                    specs[key] = val
    return specs


def extract_dl_specs(soup: BeautifulSoup) -> dict:
    """Extract specs from definition lists (dt/dd pairs)."""
    specs = {}
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            key = clean_text(dt.get_text())
            val = clean_text(dd.get_text())
            if key and val:
                specs[key] = val
    return specs


def extract_keyvalue_divs(soup: BeautifulSoup) -> dict:
    """Extract specs from key-value div patterns common on car sites."""
    specs = {}
    # Pattern: div with label + value children
    for container in soup.select(
        "[class*='spec'] [class*='row'], "
        "[class*='spec'] [class*='item'], "
        "[class*='feature'] [class*='row'], "
        "[class*='detail'] [class*='row'], "
        "[class*='tech'] [class*='row']"
    ):
        children = container.find_all(recursive=False)
        if len(children) >= 2:
            key = clean_text(children[0].get_text())
            val = clean_text(children[1].get_text())
            if key and val and len(key) < 100:
                specs[key] = val
    return specs


def extract_comparison_table(soup: BeautifulSoup) -> list[dict]:
    """Extract variants from comparison tables where columns = variants.
    Common on VW, BMW, Mercedes prices pages.
    First column = spec labels, subsequent columns = variant values.
    First row typically has variant names.
    """
    variants = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue

        # Get header row — variant names
        header_cells = rows[0].find_all(["td", "th"])
        if len(header_cells) < 2:
            continue

        variant_names = []
        for cell in header_cells[1:]:  # skip first col (label column)
            name = clean_text(cell.get_text())
            if name:
                variant_names.append(name)

        if not variant_names:
            continue

        # Initialize variant dicts
        variant_data = [{"variant_name": n, "price_incl": None, "specs": {}} for n in variant_names]

        # Parse remaining rows
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            label = clean_text(cells[0].get_text())
            if not label:
                continue

            # Check if this is the price row
            is_price_row = any(kw in label.lower() for kw in [
                "price", "retail", "rrp", "cost", "from"
            ])

            for i, cell in enumerate(cells[1:]):
                if i >= len(variant_data):
                    break
                val = clean_text(cell.get_text())
                if not val or val == "-":
                    continue

                if is_price_row:
                    price = parse_price(val)
                    if price and price > 50000:
                        variant_data[i]["price_incl"] = price
                else:
                    variant_data[i]["specs"][label] = val

        # Only keep variants that have a price or at least some specs
        valid = [v for v in variant_data if v["price_incl"] or len(v["specs"]) > 3]
        if len(valid) >= 2:
            variants = valid
            break

    return variants


def extract_variants(soup: BeautifulSoup, url: str) -> list[dict]:
    """Extract individual variants/derivatives from the page."""
    variants = []

    # Try comparison table first (VW, BMW style: columns = variants)
    variants = extract_comparison_table(soup)
    if variants:
        return variants

    # Look for variant sections — common patterns:
    # 1. Tabs for each derivative
    # 2. Cards for each derivative
    # 3. Accordion sections per derivative

    variant_selectors = [
        "[class*='variant']",
        "[class*='derivative']",
        "[class*='trim']",
        "[class*='grade']",
        "[class*='model-card']",
        "[class*='pricing-card']",
        "[class*='version']",
    ]

    for selector in variant_selectors:
        cards = soup.select(selector)
        if len(cards) >= 1:
            for card in cards:
                variant = extract_variant_from_element(card)
                if variant and variant.get("variant_name"):
                    variants.append(variant)
            if variants:
                break

    # If no variant cards found, try to get a single model's data
    if not variants:
        variant = extract_single_model(soup, url)
        if variant:
            variants.append(variant)

    return variants


def extract_variant_from_element(el: Tag) -> dict | None:
    """Extract variant info from a card/section element."""
    # Get variant name from headings
    name = ""
    for tag in ["h1", "h2", "h3", "h4", "h5", ".title", "[class*='name']", "[class*='title']"]:
        found = el.select_one(tag)
        if found:
            name = clean_text(found.get_text())
            if name and len(name) < 100:
                break
            name = ""

    if not name:
        return None

    # Get price
    price_text = ""
    for selector in [
        "[class*='price']", "[class*='cost']", ".price",
    ]:
        found = el.select_one(selector)
        if found:
            price_text = clean_text(found.get_text())
            break

    if not price_text:
        # Search for R followed by numbers in the text
        text = el.get_text()
        price_match = re.search(r'R\s*[\d\s,\.]+', text)
        if price_match:
            price_text = price_match.group()

    price = parse_price(price_text)

    # Get specs from within this variant's section
    specs = extract_spec_tables(el)
    specs.update(extract_dl_specs(el))
    specs.update(extract_keyvalue_divs(el))

    return {
        "variant_name": name,
        "price_incl": price,
        "specs": specs,
    }


def extract_single_model(soup: BeautifulSoup, url: str) -> dict | None:
    """Extract data when the page represents a single model (no variants)."""
    # Get model name
    name = ""
    for selector in ["h1", ".model-name", "[class*='hero'] h1", "[class*='banner'] h1"]:
        found = soup.select_one(selector)
        if found:
            name = clean_text(found.get_text())
            if name and len(name) < 100:
                break
            name = ""

    if not name:
        # Fallback: extract from URL
        path = urlparse(url).path
        parts = path.strip("/").split("/")
        name = parts[-1].replace("-", " ").replace("_", " ").title() if parts else "Unknown"

    # Get price
    price = None
    for selector in ["[class*='price']", "[class*='from'] [class*='amount']", ".price"]:
        found = soup.select_one(selector)
        if found:
            price = parse_price(found.get_text())
            if price:
                break

    if not price:
        text = soup.get_text()
        prices = re.findall(r'R\s*([\d\s,]+)', text)
        for p in prices:
            val = parse_price(f"R {p}")
            if val and 100000 < val < 5000000:
                price = val
                break

    # Get all specs
    specs = extract_spec_tables(soup)
    specs.update(extract_dl_specs(soup))
    specs.update(extract_keyvalue_divs(soup))

    return {
        "variant_name": name,
        "price_incl": price,
        "specs": specs,
    }


def normalize_specs(specs: dict) -> dict:
    """Map common spec field names to standardized keys."""
    mapping = {
        # Engine
        r"engine\s*(type|capacity|size|displacement)": "engine_capacity",
        r"(cubic\s*capacity|displacement|cc)": "engine_capacity",
        r"(max|peak)?\s*power|kw": "power_kw",
        r"(max|peak)?\s*torque|nm": "torque_nm",
        r"fuel\s*type|fuel": "fuel_type",
        r"cylinders?": "cylinders",
        r"transmission|gearbox": "transmission",
        r"drive\s*(train|type)|drivetrain": "drivetrain",
        # Performance
        r"top\s*speed": "top_speed_kmh",
        r"0.*(100|60)": "acceleration_0_100",
        r"fuel\s*consumption|combined|average": "fuel_consumption_l100km",
        r"co2|carbon|emission": "co2_emissions_gkm",
        # Dimensions
        r"length": "length_mm",
        r"width": "width_mm",
        r"height": "height_mm",
        r"wheelbase": "wheelbase_mm",
        r"boot|luggage|cargo\s*capacity|trunk": "boot_capacity_l",
        r"kerb\s*weight|curb\s*weight|weight": "kerb_weight_kg",
        r"fuel\s*tank|tank\s*(capacity|size)": "fuel_tank_l",
        r"ground\s*clearance": "ground_clearance_mm",
        r"turning\s*(circle|radius)": "turning_circle_m",
        # Safety
        r"airbag": "airbags",
        r"abs": "abs",
        r"esp|esc|stability": "stability_control",
        # Warranty
        r"warranty": "warranty",
        r"service\s*plan": "service_plan",
    }

    # Values that are option prices, not actual specs — skip these
    price_pattern = re.compile(r'^R\s*[\d\s,]+$|^No Cost$|^-$|^X$|^Included$|^Standard$|^Optional$', re.I)

    normalized = {}
    for key, val in specs.items():
        # Skip if the value looks like an option price rather than a spec value
        if price_pattern.match(val.strip()):
            continue

        matched = False
        for pattern, norm_key in mapping.items():
            if re.search(pattern, key, re.I):
                normalized[norm_key] = val
                matched = True
                break
        if not matched:
            # Keep original key, cleaned up
            clean_key = re.sub(r'[^\w\s]', '', key).strip().lower().replace(' ', '_')
            if clean_key:
                normalized[clean_key] = val

    return normalized


def find_prices_subpage(html: str, base_url: str, model_slug: str) -> str | None:
    """Look for a prices/options sub-page link on the model page."""
    soup = BeautifulSoup(html, "lxml")
    slug_clean = model_slug.replace("_", "-").replace(" ", "-").lower()
    slug_parts = [p for p in slug_clean.split("-") if len(p) > 2]

    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        href_lower = href.lower()
        text = a.get_text(strip=True).lower()

        # Skip non-HTML links (PDFs, apps, searches, etc.)
        if any(x in href_lower for x in [".pdf", "search.html", "__app", "configurator", "brochure"]):
            continue

        # Must have price-related keyword in URL or text
        has_price_kw = any(kw in href_lower for kw in ["price", "pricing"]) or \
                       any(kw in text for kw in ["price", "pricing"])
        if not has_price_kw:
            continue

        # Must relate to this model
        relates_to_model = slug_clean in href_lower or \
                          any(part in href_lower for part in slug_parts)
        if not relates_to_model:
            continue

        # Score: prefer URLs with "prices-and-options" pattern
        score = 0
        if "prices-and-options" in href_lower or "pricing" in href_lower:
            score += 10
        if "price" in text and "option" in text:
            score += 5
        if href_lower.endswith(".html"):
            score += 2

        full_url = urljoin(base_url, href)
        candidates.append((score, full_url))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    return None


def scrape_specs(url: str, brand_key: str, model_slug: str = None) -> list[dict]:
    """Main spec scraping function for a model URL."""
    if not model_slug:
        path = urlparse(url).path
        parts = [p for p in path.strip("/").split("/") if p]
        model_slug = parts[-1] if parts else "unknown"
        model_slug = re.sub(r'[^\w\-]', '_', model_slug)

    print(f"[Specs] Scraping {url}")

    # Try static first
    print("  Trying static fetch...")
    html = static_fetch(url)
    variants = []

    if html:
        soup = BeautifulSoup(html, "lxml")
        variants = extract_variants(soup, url)
        print(f"  Static: found {len(variants)} variants")

        # If model page didn't yield good variants, look for a prices sub-page
        has_good_data = any(v.get("price_incl") for v in variants)
        if not has_good_data:
            prices_url = find_prices_subpage(html, url, model_slug)
            if prices_url:
                print(f"  Found prices page: {prices_url}")
                time.sleep(RATE_LIMIT)
                prices_html = static_fetch(prices_url)
                if prices_html:
                    prices_soup = BeautifulSoup(prices_html, "lxml")
                    price_variants = extract_variants(prices_soup, prices_url)
                    if price_variants and any(v.get("price_incl") for v in price_variants):
                        print(f"  Prices page: found {len(price_variants)} variants with prices")
                        variants = price_variants

    # Playwright fallback
    if not variants or (len(variants) == 1 and not variants[0].get("specs")):
        print("  Falling back to Playwright...")
        time.sleep(RATE_LIMIT)
        html = playwright_fetch(url)
        if html:
            soup = BeautifulSoup(html, "lxml")
            pw_variants = extract_variants(soup, url)
            print(f"  Playwright: found {len(pw_variants)} variants")
            if len(pw_variants) > len(variants):
                variants = pw_variants
            elif len(pw_variants) == len(variants) and pw_variants:
                # Use Playwright version if it has more specs
                pw_spec_count = sum(len(v.get("specs", {})) for v in pw_variants)
                st_spec_count = sum(len(v.get("specs", {})) for v in variants)
                if pw_spec_count > st_spec_count:
                    variants = pw_variants

    # Normalize specs
    for v in variants:
        if v.get("specs"):
            v["specs"] = normalize_specs(v["specs"])

    # Save to raw_data
    brand_dir = RAW_DIR / brand_key
    brand_dir.mkdir(parents=True, exist_ok=True)
    out_file = brand_dir / f"{model_slug}.json"

    output = {
        "brand": brand_key,
        "model_slug": model_slug,
        "source_url": url,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "variant_count": len(variants),
        "variants": variants,
    }

    with open(out_file, "w") as f:
        json.dump(output, f, indent=2)

    print(f"  Saved {len(variants)} variants to {out_file}")
    time.sleep(RATE_LIMIT)
    return variants


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent_specs.py <model_url> [brand_key] [model_slug]")
        print("Example: python agent_specs.py https://www.vw.co.za/en/models/polo.html vw polo")
        sys.exit(1)

    url = sys.argv[1]
    brand = sys.argv[2] if len(sys.argv) > 2 else "unknown"
    slug = sys.argv[3] if len(sys.argv) > 3 else None

    results = scrape_specs(url, brand, slug)
    if results:
        print(f"\nExtracted {len(results)} variants:")
        for v in results:
            price_str = f"R {v['price_incl']:,}" if v.get("price_incl") else "No price"
            spec_count = len(v.get("specs", {}))
            print(f"  {v['variant_name']:40s} {price_str:>15s}  ({spec_count} specs)")
    else:
        print("\nNo variant data extracted.")
