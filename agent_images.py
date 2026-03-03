"""
Image Agent — finds vehicle images from model pages.
Detects jellybean images (PNG, transparent/white bg, configurator URLs).
Collects up to 5 typed images per model.
"""

import json
import sys
import re
import time
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse

os.environ.setdefault("PYTHONUTF8", "1")
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
from bs4 import BeautifulSoup

RAW_DIR = Path(__file__).parent / "raw_data"
USER_AGENT = "SACarFeedBot/1.0 (+https://github.com/sa-car-feed; data aggregation)"
RATE_LIMIT = 2

IMAGE_TYPES = ["Jellybean", "ExteriorFront", "ExteriorRear", "Interior", "Lifestyle"]


def static_fetch(url: str) -> str | None:
    headers = {"User-Agent": USER_AGENT}
    try:
        r = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
        if r.status_code == 200:
            return r.text
    except httpx.RequestError:
        pass
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
            page.wait_for_timeout(5000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"  Playwright error: {e}")
        return None


def is_jellybean_candidate(img_url: str, alt: str = "", classes: str = "") -> float:
    """Score how likely an image URL is a jellybean (0-1)."""
    score = 0.0
    url_lower = img_url.lower()
    alt_lower = alt.lower()
    classes_lower = classes.lower()

    # Strong indicators
    if url_lower.endswith(".png"):
        score += 0.3
    if any(kw in url_lower for kw in ["jellybean", "jelly-bean", "jelly_bean"]):
        score += 0.5
    if any(kw in url_lower for kw in ["configurator", "config", "mediaservice"]):
        score += 0.3
    if any(kw in url_lower for kw in ["transparent", "cutout", "silo", "packshot"]):
        score += 0.3

    # Medium indicators
    if any(kw in url_lower for kw in ["hero", "main", "primary", "featured"]):
        score += 0.2
    if any(kw in url_lower for kw in ["exterior", "side", "profile", "34", "three-quarter"]):
        score += 0.2
    if any(kw in classes_lower for kw in ["hero", "main", "primary", "model-image", "vehicle-image"]):
        score += 0.2

    # Negative indicators
    if any(kw in url_lower for kw in ["icon", "logo", "badge", "thumb", "thumbnail"]):
        score -= 0.5
    if any(kw in url_lower for kw in ["banner", "promo", "offer", "dealer"]):
        score -= 0.3
    if "1x1" in url_lower or "pixel" in url_lower:
        score -= 1.0

    # Size hints in URL
    size_match = re.search(r'(\d{3,4})[x_](\d{3,4})', url_lower)
    if size_match:
        w, h = int(size_match.group(1)), int(size_match.group(2))
        if w >= 600 and h >= 300:
            score += 0.2
        if w < 100 or h < 100:
            score -= 0.5

    return min(max(score, 0), 1)


def classify_image(img_url: str, alt: str = "", context: str = "") -> str:
    """Classify image type based on URL and context."""
    combined = f"{img_url} {alt} {context}".lower()

    if any(kw in combined for kw in ["interior", "cabin", "dashboard", "cockpit", "inside"]):
        return "Interior"
    if any(kw in combined for kw in ["rear", "back", "tail", "behind"]):
        return "ExteriorRear"
    if any(kw in combined for kw in ["front", "face", "headlight", "grille"]):
        return "ExteriorFront"
    if any(kw in combined for kw in ["lifestyle", "action", "driving", "road", "adventure", "scenic"]):
        return "Lifestyle"

    return "ExteriorFront"  # default for unclassified


def extract_images(html: str, base_url: str) -> list[dict]:
    """Extract and classify vehicle images from HTML."""
    soup = BeautifulSoup(html, "lxml")
    candidates = []

    # Collect all images
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "") or img.get("data-lazy", "")
        srcset = img.get("srcset", "")

        if not src:
            # Check srcset
            if srcset:
                parts = srcset.split(",")
                # Pick highest resolution
                best = parts[-1].strip().split()[0] if parts else ""
                src = best
            else:
                continue

        full_url = urljoin(base_url, src)

        # Skip tiny/tracking images
        width = img.get("width", "")
        height = img.get("height", "")
        if width and height:
            try:
                if int(width) < 50 or int(height) < 50:
                    continue
            except ValueError:
                pass

        # Skip data URIs and SVGs
        if src.startswith("data:") or src.endswith(".svg"):
            continue

        alt = img.get("alt", "")
        classes = " ".join(img.get("class", []))
        parent_classes = ""
        parent = img.parent
        if parent:
            parent_classes = " ".join(parent.get("class", []))

        jelly_score = is_jellybean_candidate(full_url, alt, f"{classes} {parent_classes}")

        candidates.append({
            "url": full_url,
            "alt": alt,
            "classes": classes,
            "parent_classes": parent_classes,
            "jellybean_score": jelly_score,
        })

    # Also check CSS background images in style attributes
    for el in soup.select("[style*='background']"):
        style = el.get("style", "")
        bg_match = re.search(r"url\(['\"]?([^)'\"]]+)['\"]?\)", style)
        if bg_match:
            bg_url = urljoin(base_url, bg_match.group(1))
            classes = " ".join(el.get("class", []))
            jelly_score = is_jellybean_candidate(bg_url, "", classes)
            candidates.append({
                "url": bg_url,
                "alt": "",
                "classes": classes,
                "parent_classes": "",
                "jellybean_score": jelly_score,
            })

    # Also check <source> tags in <picture> elements
    for source in soup.find_all("source"):
        srcset = source.get("srcset", "")
        if srcset:
            src = srcset.split(",")[-1].strip().split()[0]
            full_url = urljoin(base_url, src)
            parent = source.parent
            img_tag = parent.find("img") if parent else None
            alt = img_tag.get("alt", "") if img_tag else ""
            jelly_score = is_jellybean_candidate(full_url, alt, "")
            candidates.append({
                "url": full_url,
                "alt": alt,
                "classes": "",
                "parent_classes": "",
                "jellybean_score": jelly_score,
            })

    # Deduplicate by URL
    seen = set()
    unique = []
    for c in candidates:
        if c["url"] not in seen:
            seen.add(c["url"])
            unique.append(c)

    # Sort by jellybean score
    unique.sort(key=lambda x: x["jellybean_score"], reverse=True)

    # Build typed image list
    typed_images = {}

    # Best jellybean candidate
    for c in unique:
        if c["jellybean_score"] >= 0.3:
            typed_images["Jellybean"] = c["url"]
            break

    # Classify remaining images
    for c in unique:
        if len(typed_images) >= 5:
            break
        if c["url"] == typed_images.get("Jellybean"):
            continue

        img_type = classify_image(c["url"], c["alt"], c["parent_classes"])
        if img_type not in typed_images:
            typed_images[img_type] = c["url"]

    # Fill gaps
    for c in unique:
        if len(typed_images) >= 5:
            break
        for img_type in IMAGE_TYPES:
            if img_type not in typed_images and c["url"] not in typed_images.values():
                typed_images[img_type] = c["url"]
                break

    return [{"type": t, "url": u} for t, u in typed_images.items()]


def scrape_images(url: str, brand_key: str, model_slug: str = None) -> list[dict]:
    """Main image scraping function."""
    if not model_slug:
        path = urlparse(url).path
        parts = [p for p in path.strip("/").split("/") if p]
        model_slug = parts[-1] if parts else "unknown"
        model_slug = re.sub(r'[^\w\-]', '_', model_slug)

    print(f"[Images] Scraping {url}")

    # Try static first
    html = static_fetch(url)
    images = []

    if html:
        images = extract_images(html, url)
        print(f"  Static: found {len(images)} typed images")

    # Playwright fallback if no jellybean found
    has_jelly = any(i["type"] == "Jellybean" for i in images)
    if not has_jelly or len(images) < 3:
        print("  Falling back to Playwright for more images...")
        time.sleep(RATE_LIMIT)
        pw_html = playwright_fetch(url)
        if pw_html:
            pw_images = extract_images(pw_html, url)
            pw_has_jelly = any(i["type"] == "Jellybean" for i in pw_images)
            print(f"  Playwright: found {len(pw_images)} typed images")
            if len(pw_images) > len(images) or (pw_has_jelly and not has_jelly):
                images = pw_images

    # Save to raw_data
    brand_dir = RAW_DIR / brand_key
    brand_dir.mkdir(parents=True, exist_ok=True)
    out_file = brand_dir / f"{model_slug}_images.json"

    output = {
        "brand": brand_key,
        "model_slug": model_slug,
        "source_url": url,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "image_count": len(images),
        "images": images,
    }

    with open(out_file, "w") as f:
        json.dump(output, f, indent=2)

    print(f"  Saved {len(images)} images to {out_file}")
    time.sleep(RATE_LIMIT)
    return images


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent_images.py <model_url> [brand_key] [model_slug]")
        print("Example: python agent_images.py https://www.vw.co.za/en/models/polo.html vw polo")
        sys.exit(1)

    url = sys.argv[1]
    brand = sys.argv[2] if len(sys.argv) > 2 else "unknown"
    slug = sys.argv[3] if len(sys.argv) > 3 else None

    results = scrape_images(url, brand, slug)
    if results:
        print(f"\nFound {len(results)} images:")
        for img in results:
            print(f"  [{img['type']:15s}] {img['url']}")
    else:
        print("\nNo images found.")
