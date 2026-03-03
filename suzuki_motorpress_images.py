"""
Suzuki MotorPress Image Scraper
Logs into suzuki.motorpress.co.za, navigates model folders,
finds sub-folders with images, and saves to raw_data/suzuki/{model}_images.json

MotorPress structure:
  Home -> Model folders (02. BALENO, etc.)
    -> Sub-folders (Images, Deep Etched, Dynamic, etc.)
      -> Actual image thumbnails (URLs with ?thumb=1)
"""

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
RAW_DIR = BASE_DIR / "raw_data" / "suzuki"

LOGIN_URL = "https://suzuki.motorpress.co.za"
USERNAME = "admin@thedealersedge.co.za"
PASSWORD = "DogWithNoName!"

# Map MotorPress folder names to our model slugs
FOLDER_TO_SLUG = {
    "baleno": "baleno",
    "celerio": "celerio",
    "ciaz": "ciaz",
    "dzire": "dzire",
    "eeco": "eeco",
    "ertiga": "ertiga",
    "fronx": "fronx",
    "grand vitara": "grand-vitara",
    "ignis": "ignis",
    "jimny": "jimny",
    "jimny 5-door": "jimny",
    "s-presso": "s-presso",
    "super carry": "super-carry",
    "swift": "swift",
    "swift sport": "swift-sport",
    "vitara brezza": "vitara-brezza",
    "xl6": "xl6",
}

# URLs to skip (generic icons, not vehicle images)
SKIP_URLS = [
    "pdf.jpg", "logo", "icon", "favicon", "sprite", "placeholder",
    "spacer", "pixel", "tracking", "social", "facebook", "twitter",
    "instagram", "youtube", "linkedin", "arrow", "close", "menu",
    "search", "1x1", "blank", "transparent.gif",
    "storage/defaults",  # generic MotorPress default icons
]


def classify_image(url: str, alt: str = "", context: str = "") -> str:
    combined = f"{url} {alt} {context}".lower()
    if any(kw in combined for kw in ["interior", "cabin", "dashboard", "cockpit", "inside"]):
        return "Interior"
    if any(kw in combined for kw in ["rear", "back", "tail", "behind"]):
        return "ExteriorRear"
    if any(kw in combined for kw in ["front", "face", "headlight", "grille"]):
        return "ExteriorFront"
    if any(kw in combined for kw in ["lifestyle", "action", "driving", "road", "adventure"]):
        return "Lifestyle"
    if any(kw in combined for kw in [".png", "cutout", "silo", "jellybean", "packshot",
                                      "transparent", "deep etch", "deep-etch"]):
        return "Jellybean"
    return "ExteriorFront"


def is_vehicle_image(url: str) -> bool:
    """Check if URL is likely a real vehicle image."""
    url_lower = url.lower()
    # Must be from the motorpress images CDN
    if "motorpress.co.za/images/" not in url_lower:
        return False
    # Skip known non-vehicle URLs
    if any(skip in url_lower for skip in SKIP_URLS):
        return False
    return True


def save_images(model_slug: str, images: list[dict], source_url: str):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_file = RAW_DIR / f"{model_slug}_images.json"
    output = {
        "brand": "suzuki",
        "model_slug": model_slug,
        "source_url": source_url,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "image_count": len(images),
        "images": images,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"    Saved {len(images)} images -> {out_file.name}")


def safe_goto(page, url, timeout=20000, retries=3):
    """Navigate with retry on network errors."""
    for attempt in range(retries):
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout)
            time.sleep(1.5)
            return True
        except Exception as e:
            err = str(e)
            if "DISCONNECTED" in err or "ABORTED" in err or "FAILED" in err:
                wait = 5 * (attempt + 1)
                print(f"      Network error, waiting {wait}s... (attempt {attempt+1}/{retries})")
                time.sleep(wait)
            else:
                print(f"      Navigation error: {err[:80]}")
                return False
    return False


def collect_images_from_page(page) -> list[dict]:
    """Collect all vehicle image URLs from the current page."""
    images = []
    for img in page.query_selector_all("img"):
        src = img.get_attribute("src") or img.get_attribute("data-src") or ""
        if not src or src.startswith("data:") or src.endswith(".svg"):
            continue
        full_src = urljoin(page.url, src)
        if is_vehicle_image(full_src):
            alt = img.get_attribute("alt") or ""
            images.append({"url": full_src, "alt": alt})
    return images


def get_folder_links(page) -> list[dict]:
    """Get sub-folder links."""
    folders = []
    for link in page.query_selector_all("a"):
        href = link.get_attribute("href") or ""
        text = (link.text_content() or "").strip()
        if "/folders/" in href and text and len(text) < 100:
            folders.append({"href": href, "text": text})
    return folders


def run():
    # Check which models already have images
    existing = set()
    if RAW_DIR.exists():
        for f in RAW_DIR.glob("*_images.json"):
            with open(f) as fh:
                data = json.load(fh)
            if data.get("image_count", 0) >= 3:
                existing.add(data["model_slug"])

    if existing:
        print(f"Already have images for: {', '.join(sorted(existing))}")
        print(f"Skipping those models.\n")

    print("=" * 60)
    print("  Suzuki MotorPress Image Scraper")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = ctx.new_page()

        # Step 1: Login
        print("\n[1] Logging in...")
        page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        email_field = page.query_selector('input[type="text"]')
        if email_field and email_field.is_visible():
            email_field.fill(USERNAME)
            time.sleep(0.5)
            pw_field = page.query_selector('input[type="password"]')
            if pw_field:
                pw_field.fill(PASSWORD)
            time.sleep(0.5)
            btn = page.query_selector('button[type="submit"]')
            if btn:
                btn.click()
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(3)
            print(f"  Logged in -> {page.url}")
        else:
            print("  Login form not found!")
            browser.close()
            return

        # Accept cookies
        try:
            accept_btn = page.query_selector('button:has-text("ACCEPT")')
            if accept_btn and accept_btn.is_visible():
                accept_btn.click()
                time.sleep(1)
        except:
            pass

        # Step 2: Get model folder links
        print("\n[2] Finding model folders...")
        home_url = page.url
        folder_links = get_folder_links(page)

        model_folders = {}
        for fl in folder_links:
            text_clean = re.sub(r'^\d+\.?\s*', '', fl["text"]).strip().lower()
            for mp_name, slug in FOLDER_TO_SLUG.items():
                if mp_name in text_clean:
                    if slug in existing:
                        print(f"  SKIP {fl['text'][:35]:35s} (already done)")
                        continue
                    if slug not in model_folders:
                        model_folders[slug] = []
                    model_folders[slug].append(fl)
                    print(f"  {fl['text'][:35]:35s} -> {slug}")
                    break

        if not model_folders:
            print("  All models already have images!")
            browser.close()
            return

        # Step 3: Scrape each model
        print(f"\n[3] Scraping {len(model_folders)} models...")
        total_images = 0
        models_done = 0
        all_model_images = {}

        for slug, folders in model_folders.items():
            model_name = slug.replace("-", " ").title()
            print(f"\n  === {model_name} ===")
            all_model_images[slug] = []

            for folder_info in folders:
                folder_url = urljoin(home_url, folder_info["href"])
                print(f"    Folder: {folder_info['text'][:40]}")

                if not safe_goto(page, folder_url):
                    continue

                # Get sub-folders on this model page
                sub_folders = get_folder_links(page)
                page_images = collect_images_from_page(page)

                if page_images:
                    all_model_images[slug].extend(page_images)

                print(f"    Sub-folders: {len(sub_folders)}, Direct images: {len(page_images)}")

                # Navigate into each sub-folder
                visited = {folder_url}
                folders_queue = list(sub_folders)

                for sf in folders_queue:
                    sf_href = urljoin(home_url, sf["href"])
                    if sf_href in visited:
                        continue
                    visited.add(sf_href)

                    sf_text = sf["text"].lower()
                    # Skip non-image folders
                    if any(skip in sf_text for skip in [
                        "price", "spec", "brochure", "pdf", "video",
                        "press release", "document", "radio", "product video",
                    ]):
                        continue

                    if not safe_goto(page, sf_href):
                        continue

                    sf_images = collect_images_from_page(page)
                    sf_sub = get_folder_links(page)

                    if sf_images:
                        all_model_images[slug].extend(sf_images)
                        print(f"      [{sf['text'][:30]:30s}] {len(sf_images)} images")

                    # Go one level deeper
                    for ssf in sf_sub[:8]:
                        ssf_href = urljoin(home_url, ssf["href"])
                        if ssf_href in visited:
                            continue
                        visited.add(ssf_href)

                        ssf_text = ssf["text"].lower()
                        if any(skip in ssf_text for skip in [
                            "price", "spec", "brochure", "pdf", "video",
                            "press release", "document", "radio",
                        ]):
                            continue

                        if not safe_goto(page, ssf_href):
                            continue

                        ssf_images = collect_images_from_page(page)
                        if ssf_images:
                            all_model_images[slug].extend(ssf_images)
                            print(f"        [{ssf['text'][:28]:28s}] {len(ssf_images)} images")

                time.sleep(1)

            # Deduplicate, classify, save
            seen = set()
            unique = []
            for img in all_model_images[slug]:
                if img["url"] not in seen:
                    seen.add(img["url"])
                    unique.append(img)

            if unique:
                typed = {}
                for img in unique:
                    if len(typed) >= 5:
                        break
                    img_type = classify_image(img["url"], img.get("alt", ""),
                                             slug.replace("-", " "))
                    if img_type not in typed:
                        typed[img_type] = img["url"]

                # Fill remaining slots
                for img in unique:
                    if len(typed) >= 5:
                        break
                    if img["url"] not in typed.values():
                        for t in ["ExteriorFront", "ExteriorRear", "Interior",
                                  "Lifestyle", "Jellybean"]:
                            if t not in typed:
                                typed[t] = img["url"]
                                break

                images_list = [{"type": t, "url": u} for t, u in typed.items()]
                save_images(slug, images_list, LOGIN_URL)
                total_images += len(images_list)
                models_done += 1
                print(f"    -> {len(unique)} unique, {len(images_list)} typed saved")
            else:
                print(f"    -> No vehicle images found")

        # Summary
        print(f"\n{'='*60}")
        print(f"  New models scraped: {models_done}/{len(model_folders)}")
        print(f"  New images: {total_images}")
        print(f"  Previously done: {len(existing)}")
        print(f"  Total models with images: {models_done + len(existing)}")
        print(f"{'='*60}")

        browser.close()


if __name__ == "__main__":
    run()
