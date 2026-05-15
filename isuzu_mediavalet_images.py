"""
Isuzu MediaValet DAM Image Scraper
Logs into isuzudam.mediavalet.com, navigates category tree,
finds vehicle jellybean/studio images, and saves to raw_data/isuzu/{model}_images.json

MediaValet structure:
  Login (Azure AD B2C) -> Category tree sidebar
    -> "Image Delux" or model-specific categories
      -> Asset grid with thumbnails + full-res downloads

Usage:
  python isuzu_mediavalet_images.py              # Scrape all models
  python isuzu_mediavalet_images.py --explore     # Dump category tree (first run)
  python isuzu_mediavalet_images.py --model d-max # Scrape single model
"""

import argparse
import json
import re
import sys
import os
import time
from pathlib import Path
from urllib.parse import urljoin

os.environ.setdefault("PYTHONUTF8", "1")
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
RAW_DIR = BASE_DIR / "raw_data" / "isuzu"

LOGIN_URL = "https://isuzudam.mediavalet.com"
USERNAME = "jason@thedealersedge.co.za"
PASSWORD = "@ISUZU2018"

# Direct category URLs discovered via --explore mode
# Each model slug maps to one or more MediaValet category URLs
CATEGORY_URLS = {
    "d-max": [
        "/v5/browse/categories/54798049-90f2-4c08-80a4-e65f75147307",  # ISUZU D-MAX
    ],
    "d-max-gen-6": [
        "/v5/browse/categories/5c4d465c-c6c0-4996-addb-d7ff2da2d2de",  # ISUZU D-MAX GEN 6
        "/v5/browse/categories/aa3bef3e-0d02-42b4-8317-12fcdbd3d9af",  # ISUZU 1.9 Ddi X-RIDER
        "/v5/browse/categories/effb4074-ddf8-42b6-9491-34d70ccac97b",  # ISUZU 1.9 X-RIDER BLACK
    ],
    "mu-x": [
        "/v5/browse/categories/27ad5a1f-9d45-41b8-832f-0fdc522ef1ce",  # ISUZU MU-X MY25
    ],
}

# Keyword matching for alt-text based model detection
TARGET_MODELS = {
    "d-max": ["d-max", "d max", "dmax"],
    "d-max-gen-6": ["d-max gen 6", "gen 6", "gen6", "x-rider", "xrider"],
    "mu-x": ["mu-x", "mu x", "mux"],
}

# MediaValet CDN patterns
MEDIAVALET_CDN_PATTERNS = [
    "mediavalet.com",
    "blob.core.windows.net",
    "mvsfservicefabric",
    "mv-stg-blob",
]

# URLs to skip
SKIP_URLS = [
    "logo", "icon", "favicon", "sprite", "placeholder",
    "spacer", "pixel", "tracking", "social", "1x1", "blank",
    "avatar", "profile-pic", "user-image",
]

# Category keywords to skip during navigation
SKIP_CATEGORIES = [
    "aftersales", "ci guideline", "sales guide", "briefing",
    "festive", "safety check", "video", "campaign",
    "brand element", "dealer element", "press",
]


def classify_image(url: str, alt: str = "", context: str = "") -> str:
    """Classify image type based on URL, alt text, and context."""
    combined = f"{url} {alt} {context}".lower()
    if any(kw in combined for kw in ["interior", "cabin", "dashboard", "cockpit", "inside"]):
        return "Interior"
    if any(kw in combined for kw in ["rear", "back", "tail", "behind"]):
        return "ExteriorRear"
    if any(kw in combined for kw in ["front", "face", "headlight", "grille"]):
        return "ExteriorFront"
    if any(kw in combined for kw in ["lifestyle", "action", "driving", "road", "adventure", "scenic"]):
        return "Lifestyle"
    if any(kw in combined for kw in [".png", "cutout", "silo", "jellybean", "packshot",
                                      "transparent", "deep etch", "deep-etch", "image delux",
                                      "studio", "white background"]):
        return "Jellybean"
    return "ExteriorFront"


def is_mediavalet_image(url: str) -> bool:
    """Check if URL is a MediaValet-hosted image."""
    url_lower = url.lower()
    if any(pattern in url_lower for pattern in MEDIAVALET_CDN_PATTERNS):
        if any(skip in url_lower for skip in SKIP_URLS):
            return False
        return True
    return False


def get_full_res_url(thumb_url: str) -> str:
    """Try to derive full-resolution URL from thumbnail."""
    url = thumb_url
    url = re.sub(r'[?&]thumb=\d+', '', url)
    url = re.sub(r'[?&]width=\d+', '', url)
    url = re.sub(r'[?&]height=\d+', '', url)
    url = re.sub(r'/thumbnail/', '/original/', url)
    url = re.sub(r'/thumbs/', '/original/', url)
    return url.rstrip('?&')


def save_images(model_slug: str, images: list[dict], source_url: str):
    """Save images JSON matching existing pipeline format."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_file = RAW_DIR / f"{model_slug}_images.json"
    output = {
        "brand": "isuzu",
        "model_slug": model_slug,
        "source_url": source_url,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "image_count": len(images),
        "images": images,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"    Saved {len(images)} images -> {out_file.name}")


def safe_goto(page, url, timeout=30000, retries=3):
    """Navigate with retry on network errors."""
    for attempt in range(retries):
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout)
            time.sleep(2)
            return True
        except Exception as e:
            err = str(e)
            if "DISCONNECTED" in err or "ABORTED" in err or "FAILED" in err or "Timeout" in err:
                wait = 5 * (attempt + 1)
                print(f"      Network error, waiting {wait}s... (attempt {attempt+1}/{retries})")
                time.sleep(wait)
            else:
                print(f"      Navigation error: {err[:100]}")
                return False
    return False


def debug_screenshot(page, name: str):
    """Save debug screenshot for troubleshooting."""
    path = BASE_DIR / f"debug_mediavalet_{name}.png"
    try:
        page.screenshot(path=str(path))
        print(f"    Debug screenshot: {path.name}")
    except Exception:
        pass


def wait_for_dam_loaded(page, timeout=30000):
    """Wait for the MediaValet DAM interface to fully load."""
    try:
        # MediaValet renders a React app — wait for common UI elements
        page.wait_for_selector(
            '[class*="asset"], [class*="category"], [class*="gallery"], '
            '[class*="grid"], [class*="Card"], [class*="thumb"], '
            '[data-testid], [class*="browse"]',
            timeout=timeout
        )
        time.sleep(3)
        return True
    except Exception:
        # Fallback: just wait a bit and hope the SPA rendered
        time.sleep(5)
        return False


def login(page) -> bool:
    """Authenticate with MediaValet via Azure AD B2C."""
    print("\n[1] Logging in to Isuzu MediaValet DAM...")
    page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
    time.sleep(3)

    # Wait for any input field to appear (login form may take time to render)
    try:
        page.wait_for_selector("input", timeout=15000)
        time.sleep(2)
    except Exception:
        pass

    current_url = page.url
    print(f"  Current URL: {current_url[:80]}")

    # Check if already logged in (has DAM content)
    has_content = page.query_selector('[class*="asset"], [class*="category"], [class*="Card"]')
    if has_content:
        print("  Already logged in!")
        return True

    # Find ALL visible input fields on the page
    all_inputs = page.query_selector_all("input")
    visible_inputs = [inp for inp in all_inputs if inp.is_visible()]
    print(f"  Found {len(visible_inputs)} visible input fields")

    # Also check iframes for inputs
    if not visible_inputs:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            frame_inputs = frame.query_selector_all("input")
            visible_inputs = [inp for inp in frame_inputs if inp.is_visible()]
            if visible_inputs:
                print(f"  Found {len(visible_inputs)} inputs in iframe")
                break

    if len(visible_inputs) < 2:
        print(f"  ERROR: Expected at least 2 input fields, found {len(visible_inputs)}")
        debug_screenshot(page, "login_no_email")
        return False

    # The login form has email field first, then password field
    email_field = visible_inputs[0]
    pw_field = visible_inputs[1]

    # Detect if the second field is actually a password type
    pw_type = pw_field.get_attribute("type") or ""
    if pw_type != "password":
        # Try to find the password field explicitly
        for inp in visible_inputs[1:]:
            if (inp.get_attribute("type") or "") == "password":
                pw_field = inp
                break

    print(f"  Filling email: {USERNAME}")
    email_field.fill(USERNAME)
    time.sleep(0.5)

    print("  Filling password...")
    pw_field.fill(PASSWORD)
    time.sleep(0.5)

    # Find and click submit button
    submit_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Sign in")',
        'button:has-text("Log in")',
        'button:has-text("Submit")',
        'button:has-text("Login")',
    ]
    submitted = False
    for sel in submit_selectors:
        btn = page.query_selector(sel)
        if btn and btn.is_visible():
            btn.click()
            submitted = True
            break

    if not submitted:
        # Try any visible button near the inputs
        buttons = page.query_selector_all("button")
        for btn in buttons:
            if btn.is_visible():
                text = (btn.text_content() or "").strip().lower()
                # Skip obviously wrong buttons
                if text and text not in ["cancel", "back", "close"]:
                    btn.click()
                    submitted = True
                    break

    if not submitted:
        # Last resort: press Enter on the password field
        pw_field.press("Enter")

    # Wait for redirect back to DAM
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    time.sleep(5)

    # Handle "Stay signed in?" prompt (Azure AD B2C)
    try:
        stay_btn = page.query_selector('button:has-text("Yes")')
        if stay_btn and stay_btn.is_visible():
            stay_btn.click()
            time.sleep(3)
    except Exception:
        pass

    print(f"  Post-login URL: {page.url[:80]}")

    # Verify we're logged in — wait for DAM content to appear
    wait_for_dam_loaded(page, timeout=20000)

    # Check for DAM content
    has_content = page.query_selector('[class*="asset"], [class*="category"], [class*="Card"], img[alt]')
    if has_content:
        print("  Login successful!")
        return True

    # If still on the same URL without content, might need to navigate
    if page.url.rstrip("/") == LOGIN_URL.rstrip("/"):
        print("  Redirecting to browse page...")
        page.goto(LOGIN_URL + "/v5/browse/categories/most_viewed",
                  wait_until="networkidle", timeout=30000)
        time.sleep(5)
        wait_for_dam_loaded(page, timeout=20000)

    print("  Login completed.")
    return True


def collect_images_from_page(page) -> list[dict]:
    """Collect all vehicle image URLs from the current MediaValet page."""
    images = []

    # Method 1: Standard img tags
    for img in page.query_selector_all("img"):
        src = img.get_attribute("src") or img.get_attribute("data-src") or ""
        if not src or src.startswith("data:") or src.endswith(".svg"):
            continue
        full_src = urljoin(page.url, src)
        if is_mediavalet_image(full_src):
            alt = img.get_attribute("alt") or ""
            title = img.get_attribute("title") or ""
            images.append({"url": get_full_res_url(full_src), "alt": alt, "title": title})

    # Method 2: CSS background images (MediaValet uses these for asset thumbnails)
    for el in page.query_selector_all('[style*="background-image"], [style*="background:"]'):
        style = el.get_attribute("style") or ""
        match = re.search(r'url\(["\']?([^"\'()]+)["\']?\)', style)
        if match:
            url = urljoin(page.url, match.group(1))
            if is_mediavalet_image(url):
                images.append({"url": get_full_res_url(url), "alt": "", "title": ""})

    # Method 3: Data attributes (MediaValet may store asset URLs in data-*)
    for el in page.query_selector_all('[data-src], [data-url], [data-download-url], [data-asset-url]'):
        for attr in ["data-src", "data-url", "data-download-url", "data-asset-url"]:
            url = el.get_attribute(attr)
            if url and is_mediavalet_image(url):
                images.append({"url": get_full_res_url(url), "alt": "", "title": ""})

    return images


def select_best_images(all_images: list[dict], model_slug: str, max_images: int = 5) -> list[dict]:
    """Deduplicate and select best images, max 5 per model."""
    # Deduplicate by normalized URL
    seen = set()
    unique = []
    for img in all_images:
        normalized = img["url"].split("?")[0]
        if normalized not in seen:
            seen.add(normalized)
            unique.append(img)

    if not unique:
        return []

    # Classify and select one per type
    typed = {}
    for img in unique:
        if len(typed) >= max_images:
            break
        img_type = classify_image(
            img["url"],
            img.get("alt", "") + " " + img.get("title", ""),
            model_slug.replace("-", " ")
        )
        if img_type not in typed:
            typed[img_type] = img["url"]

    # Fill remaining slots
    for img in unique:
        if len(typed) >= max_images:
            break
        if img["url"] not in typed.values():
            for t in ["ExteriorFront", "ExteriorRear", "Interior", "Lifestyle", "Jellybean"]:
                if t not in typed:
                    typed[t] = img["url"]
                    break

    return [{"type": t, "url": u} for t, u in typed.items()]


def scroll_to_load_all(page, max_scrolls=10):
    """Scroll down to trigger lazy loading of assets."""
    for i in range(max_scrolls):
        prev_count = len(page.query_selector_all("img"))
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        new_count = len(page.query_selector_all("img"))
        if new_count == prev_count:
            break
    # Scroll back to top
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)


def explore_categories(page):
    """Dump category tree for mapping. Run once to understand DAM structure."""
    print("\n[EXPLORE] Dumping category tree...")
    print("=" * 60)

    # Wait for DAM to load
    wait_for_dam_loaded(page)
    time.sleep(3)

    # Take a screenshot for reference
    debug_screenshot(page, "explore_initial")

    # Try to find category/folder navigation elements
    # MediaValet uses various patterns for category trees
    cat_selectors = [
        '[class*="category"]',
        '[class*="tree"]',
        '[class*="folder"]',
        '[class*="nav"]',
        '[class*="sidebar"]',
        '[class*="panel"]',
        '[role="tree"]',
        '[role="treeitem"]',
        'nav a',
        'aside a',
    ]

    all_elements = set()
    for sel in cat_selectors:
        try:
            elements = page.query_selector_all(sel)
            for el in elements:
                text = (el.text_content() or "").strip()
                href = el.get_attribute("href") or ""
                if text and len(text) < 200:
                    all_elements.add((text[:80], href[:100]))
        except Exception:
            pass

    if all_elements:
        print(f"\nFound {len(all_elements)} navigation elements:")
        for text, href in sorted(all_elements):
            print(f"  {text:50s}  {href}")
    else:
        print("\nNo category elements found via selectors.")

    # Also dump all links on the page
    print(f"\n{'='*60}")
    print("All links on page:")
    links = page.query_selector_all("a")
    for link in links:
        text = (link.text_content() or "").strip()
        href = link.get_attribute("href") or ""
        if text and len(text) < 100 and href:
            print(f"  {text:50s}  {href[:80]}")

    # Dump all buttons
    print(f"\n{'='*60}")
    print("All buttons on page:")
    buttons = page.query_selector_all("button")
    for btn in buttons:
        text = (btn.text_content() or "").strip()
        if text and len(text) < 100:
            aria = btn.get_attribute("aria-label") or ""
            print(f"  {text:50s}  {aria}")

    # Dump page content summary
    print(f"\n{'='*60}")
    print("Page content summary:")
    body_text = (page.text_content("body") or "")[:5000]
    # Extract meaningful lines
    lines = [l.strip() for l in body_text.split("\n") if l.strip() and len(l.strip()) > 3]
    for line in lines[:100]:
        print(f"  {line[:100]}")

    # Count images on page
    img_count = len(page.query_selector_all("img"))
    bg_count = len(page.query_selector_all('[style*="background-image"]'))
    print(f"\n{'='*60}")
    print(f"Images: {img_count} img tags, {bg_count} background images")

    # Dump a sample of image URLs
    print("\nSample image URLs:")
    for img in page.query_selector_all("img")[:20]:
        src = img.get_attribute("src") or img.get_attribute("data-src") or ""
        alt = img.get_attribute("alt") or ""
        if src:
            print(f"  [{alt[:30]:30s}] {src[:100]}")

    debug_screenshot(page, "explore_final")
    print(f"\n{'='*60}")
    print("Explore complete. Check debug screenshots for visual reference.")


def find_and_click_category(page, target_keywords: list[str]) -> bool:
    """Find and click a category in the sidebar/tree that matches keywords."""
    # Try multiple approaches to find clickable categories
    clickable_selectors = [
        '[class*="category"] a',
        '[class*="tree"] a',
        '[role="treeitem"]',
        '[class*="folder"] a',
        'nav a',
        'aside a',
        '[class*="sidebar"] a',
        'a[href*="categor"]',
        'a[href*="folder"]',
        'button[class*="category"]',
        'span[class*="category"]',
    ]

    for sel in clickable_selectors:
        try:
            elements = page.query_selector_all(sel)
            for el in elements:
                text = (el.text_content() or "").strip().lower()
                for keyword in target_keywords:
                    if keyword in text:
                        print(f"    Found category: '{text}' (matched '{keyword}')")
                        el.click()
                        time.sleep(3)
                        page.wait_for_load_state("networkidle", timeout=15000)
                        time.sleep(2)
                        return True
        except Exception:
            continue

    return False


def match_model_slug(text: str) -> str | None:
    """Match text to a model slug based on TARGET_MODELS keywords."""
    text_lower = text.lower().strip()
    for slug, keywords in TARGET_MODELS.items():
        for kw in keywords:
            if kw in text_lower:
                return slug
    return None


def scrape_via_direct_urls(page, target_slugs: set[str]) -> dict[str, list[dict]]:
    """Navigate directly to known category URLs and collect images."""
    results = {slug: [] for slug in target_slugs}

    print("\n[3] Scraping model categories...")

    for slug in sorted(target_slugs):
        cat_urls = CATEGORY_URLS.get(slug, [])
        if not cat_urls:
            print(f"\n  {slug.upper()}: No category URLs configured, skipping")
            continue

        print(f"\n  === {slug.upper()} ({len(cat_urls)} categories) ===")

        for cat_url in cat_urls:
            full_url = LOGIN_URL + cat_url
            print(f"    Navigating to: {cat_url.split('/')[-1][:20]}...")

            if not safe_goto(page, full_url):
                continue

            wait_for_dam_loaded(page)
            scroll_to_load_all(page)

            # Collect images from the asset grid
            images = collect_images_from_page(page)
            if images:
                results[slug].extend(images)
                print(f"    Found {len(images)} images")

                # Log alt texts for debugging
                for img in images[:5]:
                    alt = img.get("alt", "")[:50]
                    if alt:
                        print(f"      - {alt}")
            else:
                print(f"    No images found on this page")
                debug_screenshot(page, f"no_images_{slug}")

            time.sleep(2)

    return results


def run(args):
    """Main scraper function."""
    # Check which models already have images
    existing = set()
    if RAW_DIR.exists():
        for f in RAW_DIR.glob("*_images.json"):
            with open(f) as fh:
                data = json.load(fh)
            if data.get("image_count", 0) >= 3:
                existing.add(data["model_slug"])

    # Determine which models to scrape
    if args.model:
        target_slugs = {args.model}
    else:
        target_slugs = set(TARGET_MODELS.keys())

    # Remove already-done models (unless --force)
    if not args.force and not args.explore:
        skipped = target_slugs & existing
        if skipped:
            print(f"Already have images for: {', '.join(sorted(skipped))}")
            print("Use --force to re-scrape.\n")
        target_slugs -= existing

    if not target_slugs and not args.explore:
        print("All models already have images!")
        return

    print("=" * 60)
    print("  Isuzu MediaValet DAM Image Scraper")
    print("=" * 60)
    if not args.explore:
        print(f"  Target models: {', '.join(sorted(target_slugs))}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = ctx.new_page()

        # Login
        if not login(page):
            print("\n  FATAL: Login failed!")
            debug_screenshot(page, "login_failed")
            browser.close()
            return

        # Wait for DAM to fully load
        wait_for_dam_loaded(page)
        time.sleep(3)

        if args.explore:
            explore_categories(page)
            browser.close()
            return

        # Scrape images via direct category URLs
        results = scrape_via_direct_urls(page, target_slugs)

        # Process and save results
        print(f"\n[4] Processing and saving...")
        total_images = 0
        models_done = 0

        for slug in sorted(target_slugs):
            model_images = results.get(slug, [])
            print(f"\n  === {slug.upper()} ===")

            if not model_images:
                print(f"    No images found")
                continue

            best = select_best_images(model_images, slug)
            if best:
                save_images(slug, best, LOGIN_URL)
                total_images += len(best)
                models_done += 1
                print(f"    -> {len(model_images)} collected, {len(best)} typed saved")
            else:
                print(f"    -> No usable images after filtering")

        # Summary
        print(f"\n{'='*60}")
        print(f"  Models scraped: {models_done}/{len(target_slugs)}")
        print(f"  Images saved: {total_images}")
        print(f"  Previously done: {len(existing)}")
        print(f"  Total models with images: {models_done + len(existing)}")
        print(f"{'='*60}")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Isuzu MediaValet DAM Image Scraper")
    parser.add_argument("--explore", action="store_true",
                        help="Dump category tree structure (first run)")
    parser.add_argument("--model", type=str, default=None,
                        help="Scrape single model (e.g., d-max, mu-x)")
    parser.add_argument("--force", action="store_true",
                        help="Re-scrape even if images already exist")
    parser.add_argument("--headless", action="store_true",
                        help="Run browser in headless mode")
    args = parser.parse_args()
    run(args)
