"""
Orchestrator — ties all agents together.
CLI args: --brands, --tier, --diff-only
Runs: discovery -> specs -> images -> compile -> diff
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent_discovery import discover
from agent_specs import scrape_specs
from agent_images import scrape_images
from agent_compile import compile_feed
from agent_diff import run_diff
from quickpic_to_raw import convert_catalogue, TARGET_BRANDS

BRAND_URLS = Path(__file__).parent / "brand_urls.json"
OUTPUT_DIR = Path(__file__).parent / "output"
PREV_DIR = Path(__file__).parent / "previous_feeds"
DISCOVERY_CACHE = Path(__file__).parent / "discovery_cache"


def load_brands(tier: str = None, brand_keys: list[str] = None) -> list[str]:
    """Get list of brand keys to process."""
    with open(BRAND_URLS) as f:
        data = json.load(f)

    all_brands = []
    if tier in (None, "all", "1", "tier1"):
        all_brands.extend(data["tier1"].keys())
    if tier in (None, "all", "2", "tier2"):
        all_brands.extend(data["tier2"].keys())

    if brand_keys:
        return [b for b in brand_keys if b in all_brands or b in data.get("tier1", {}) or b in data.get("tier2", {})]

    return all_brands


GENERIC_SLUGS = {"overview", "index", "default", "home", "main", "amg", "plug-in",
                  "plug_in", "petrol", "diesel", "hybrid", "electric"}


def url_to_slug(url: str, model_name: str = "") -> str:
    """Derive a unique slug from a URL, falling back to parent segments for generic filenames."""
    parts = url.rstrip("/").split("?")[0].split("/")
    # Strip file extensions from the last segment
    parts[-1] = re.sub(r'\.(html?|php|aspx?)$', '', parts[-1])

    # Walk backwards to find a non-generic segment
    slug = ""
    for i in range(len(parts) - 1, -1, -1):
        candidate = re.sub(r'[^\w\-]', '_', parts[i]).lower()
        if candidate and candidate not in GENERIC_SLUGS:
            slug = candidate
            # If the next segment is also meaningful (e.g., "suv/glc"), combine them
            # to avoid collisions between e.g. "saloon/a-class" and "hatchback/a-class"
            if i > 0:
                parent = re.sub(r'[^\w\-]', '_', parts[i - 1]).lower()
                if parent in GENERIC_SLUGS or parent in ("models", "passengercars",
                    "all-models", "en", "za", "vehicles", "cars", "showroom",
                    "new-vehicles", "new", "range"):
                    pass  # parent is too generic, use just the model slug
                else:
                    slug = f"{parent}_{slug}"
            break

    if not slug:
        slug = model_name.lower().replace(" ", "_") if model_name else "unknown"
        slug = re.sub(r'[^\w\-]', '_', slug)

    return slug


def archive_previous_feed():
    """Move latest feed to previous_feeds/ before new run."""
    latest = OUTPUT_DIR / "sa_car_feed_latest.xml"
    if latest.exists():
        PREV_DIR.mkdir(exist_ok=True)
        # Read the generated timestamp from the XML
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        dest = PREV_DIR / f"sa_car_feed_{timestamp}.xml"
        shutil.copy2(latest, dest)
        print(f"[Orchestrator] Archived previous feed to {dest}")


def run(brands: list[str], skip_discovery: bool = False, diff_only: bool = False):
    """Main orchestrator run."""
    start_time = time.time()

    print(f"\n{'='*60}")
    print(f"  SA NEW CAR FEED — Pipeline Run")
    print(f"  Brands: {', '.join(brands)}")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    if diff_only:
        print("[Orchestrator] Diff-only mode")
        run_diff()
        return

    # Archive previous feed
    archive_previous_feed()

    # Phase 1: Discovery
    all_models = {}
    if not skip_discovery:
        print("\n--- Phase 1: Discovery ---\n")
        for brand in brands:
            try:
                models = discover(brand)
                all_models[brand] = models
                print(f"  {brand}: {len(models)} models found")
            except Exception as e:
                print(f"  {brand}: ERROR - {e}")
                # Try loading from cache
                cache_file = DISCOVERY_CACHE / f"{brand}.json"
                if cache_file.exists():
                    with open(cache_file) as f:
                        cached = json.load(f)
                    all_models[brand] = cached.get("models", [])
                    print(f"  {brand}: loaded {len(all_models[brand])} from cache")
    else:
        # Load from cache
        print("\n--- Phase 1: Loading from cache ---\n")
        for brand in brands:
            cache_file = DISCOVERY_CACHE / f"{brand}.json"
            if cache_file.exists():
                with open(cache_file) as f:
                    cached = json.load(f)
                all_models[brand] = cached.get("models", [])
                print(f"  {brand}: {len(all_models[brand])} models from cache")
            else:
                print(f"  {brand}: no cache found, running discovery...")
                models = discover(brand)
                all_models[brand] = models

    # Phase 2: Spec Scraping
    print("\n--- Phase 2: Spec Scraping ---\n")
    spec_results = {}
    for brand, models in all_models.items():
        spec_results[brand] = []
        for model in models:
            url = model["url"]
            slug = url_to_slug(url, model.get("model_name", ""))
            try:
                variants = scrape_specs(url, brand, slug)
                spec_results[brand].append({
                    "model": model["model_name"],
                    "slug": slug,
                    "variants": len(variants),
                })
            except Exception as e:
                print(f"  ERROR scraping specs for {brand}/{slug}: {e}")

    # Phase 3: Image Scraping
    print("\n--- Phase 3: Image Scraping ---\n")
    img_results = {}
    for brand, models in all_models.items():
        img_results[brand] = []
        for model in models:
            url = model["url"]
            slug = url_to_slug(url, model.get("model_name", ""))
            try:
                images = scrape_images(url, brand, slug)
                img_results[brand].append({
                    "model": model["model_name"],
                    "slug": slug,
                    "images": len(images),
                })
            except Exception as e:
                print(f"  ERROR scraping images for {brand}/{slug}: {e}")

    # Phase 4: Compile
    print("\n--- Phase 4: Compile ---\n")
    feed_file = compile_feed(brands)

    # Phase 5: Diff
    print("\n--- Phase 5: Diff ---\n")
    diff_file = run_diff()

    # Summary
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Elapsed: {elapsed:.0f}s")
    print(f"{'='*60}")
    print(f"  Brands processed: {len(brands)}")
    total_models = sum(len(m) for m in all_models.values())
    print(f"  Models discovered: {total_models}")
    total_variants = sum(
        sum(s["variants"] for s in brand_specs)
        for brand_specs in spec_results.values()
    )
    print(f"  Variants scraped: {total_variants}")
    if feed_file:
        print(f"  Feed: {feed_file}")
    if diff_file:
        print(f"  Changes: {diff_file}")
    print(f"{'='*60}\n")


def run_quickpic(brands: list[str] | None = None, compile_only: bool = False):
    """QuickPic pipeline: convert catalogue → compile feed."""
    start_time = time.time()
    brand_set = set(brands) if brands else None

    print(f"\n{'='*60}")
    print(f"  SA NEW CAR FEED — QuickPic Pipeline")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # Archive previous feed
    archive_previous_feed()

    # Phase 1: Convert QuickPic catalogue → raw_data
    if not compile_only:
        print("\n--- Phase 1: QuickPic → raw_data ---\n")
        total = convert_catalogue(brands_filter=brand_set)
        print(f"  Converted {total} vehicles to raw_data/")

    # Phase 2: Compile
    print("\n--- Phase 2: Compile ---\n")
    feed_brands = list(brand_set) if brand_set else sorted(TARGET_BRANDS)
    feed_file = compile_feed(feed_brands)

    # Phase 3: Diff
    print("\n--- Phase 3: Diff ---\n")
    diff_file = run_diff()

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  QUICKPIC PIPELINE COMPLETE")
    print(f"  Elapsed: {elapsed:.0f}s")
    if feed_file:
        print(f"  Feed: {feed_file}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="SA New Car Data Feed Builder")
    parser.add_argument("--brands", nargs="+", help="Specific brands to process (e.g., vw toyota)")
    parser.add_argument("--tier", choices=["1", "2", "all"], default=None,
                       help="Process all brands in tier (1, 2, or all)")
    parser.add_argument("--diff-only", action="store_true",
                       help="Only run diff against previous feed")
    parser.add_argument("--skip-discovery", action="store_true",
                       help="Skip discovery, use cached model URLs")
    parser.add_argument("--quickpic", action="store_true",
                       help="Use QuickPic catalogue as source (skip OEM scraping)")
    parser.add_argument("--compile-only", action="store_true",
                       help="Skip conversion, just compile existing raw_data")
    args = parser.parse_args()

    if args.quickpic:
        brand_keys = [b.lower() for b in args.brands] if args.brands else None
        run_quickpic(brands=brand_keys, compile_only=args.compile_only)
        return

    brand_keys = args.brands
    if brand_keys:
        brand_keys = [b.lower() for b in brand_keys]
    else:
        brand_keys = load_brands(args.tier)

    if not brand_keys:
        print("No brands to process. Use --brands or --tier")
        sys.exit(1)

    run(brand_keys, skip_discovery=args.skip_discovery, diff_only=args.diff_only)


if __name__ == "__main__":
    main()
