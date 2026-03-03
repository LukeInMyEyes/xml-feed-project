"""
Fix Suzuki feed to match suzukiauto.co.za official data.
- Remove discontinued: Ciaz, Vitara Brezza
- Add missing: Swift, Swift Sport
- Update prices and remove phantom variants
- Add missing variant: S-Presso GL+ AMT S-Edition
"""

import json
import os
import time
from pathlib import Path

RAW_DIR = Path(__file__).parent / "raw_data" / "suzuki"
NOW = time.strftime("%Y-%m-%dT%H:%M:%S")


def slugify(name):
    import re
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9\-]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s


# === STEP 1: Remove discontinued models ===
for discontinued in ["ciaz", "vitara-brezza"]:
    for suffix in ["", "_images"]:
        f = RAW_DIR / f"{discontinued}{suffix}.json"
        if f.exists():
            f.unlink()
            print(f"  Removed {f.name}")

# === STEP 2: Price fixes per model (SA website prices as of Feb 2026) ===
# Format: {variant_name: new_price} or None to remove
FIXES = {
    "baleno": {
        "update": {
            "1.5 GL 5-dr": 267900,
            "1.5 GL 5-dr AT": 289900,
        }
    },
    "ertiga": {
        "update": {
            "1.5 GA MPV": 304900,
            "1.5 GL MPV": 344900,
            "1.5 GL MPV AT": 363900,
        }
    },
    "fronx": {
        "update": {
            "1.5 GL": 299900,
            "1.5 GL AT": 324900,
            "1.5 GLX": 348900,
            "1.5 GLX AT": 368900,
        }
    },
    "grand-vitara": {
        "update": {
            "1.5 GL": 359900,
        },
        "remove": ["1.5 GLX", "1.5 GLX 6AT Hybrid AllGrip"],
    },
    "jimny": {
        "update": {
            "1.5 GLX 4x4": 436900,
            "1.5 GLX 4x4 AT": 458900,
        },
        "remove": ["1.5 GL 4x4 AT", "1.5 GL MT"],
    },
    "s-presso": {
        "remove": ["1.0 Edition AT"],
        "add": [
            {"variant_name": "1.0 GL+ AMT S-Edition", "price_incl": 219900, "specs": {}},
        ],
    },
    "xl6": {
        "update": {
            "GL": 359900,
            "GL AT": 379900,
            "GLX AT": 400350,
        },
        "remove": ["GLX"],
    },
}

for model_slug, fixes in FIXES.items():
    model_file = RAW_DIR / f"{model_slug}.json"
    if not model_file.exists():
        print(f"  SKIP {model_slug} (file not found)")
        continue

    with open(model_file, encoding="utf-8") as f:
        data = json.load(f)

    variants = data.get("variants", [])

    # Remove variants
    remove_names = set(fixes.get("remove", []))
    if remove_names:
        before = len(variants)
        variants = [v for v in variants if v["variant_name"] not in remove_names]
        removed = before - len(variants)
        if removed:
            print(f"  {model_slug}: removed {removed} variants ({', '.join(remove_names)})")

    # Update prices
    updates = fixes.get("update", {})
    for v in variants:
        if v["variant_name"] in updates:
            old = v["price_incl"]
            new = updates[v["variant_name"]]
            if old != new:
                v["price_incl"] = new
                print(f"  {model_slug}: {v['variant_name']} R{old:,} -> R{new:,}")

    # Add new variants
    for new_v in fixes.get("add", []):
        variants.append(new_v)
        print(f"  {model_slug}: added {new_v['variant_name']} R{new_v['price_incl']:,}")

    data["variants"] = variants
    data["variant_count"] = len(variants)
    data["scraped_at"] = NOW

    with open(model_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# === STEP 3: Add Swift and Swift Sport ===
new_models = {
    "swift": {
        "brand": "suzuki",
        "model_slug": "swift",
        "model_name": "Swift",
        "source": "suzukiauto.co.za",
        "source_url": "https://www.suzukiauto.co.za/cars/swift",
        "scraped_at": NOW,
        "variants": [
            {"variant_name": "1.2 GL MT", "price_incl": 227900, "specs": {}},
            {"variant_name": "1.2 GL+ MT", "price_incl": 249900, "specs": {}},
            {"variant_name": "1.2 GL+ CVT", "price_incl": 269900, "specs": {}},
            {"variant_name": "1.2 GLX MT", "price_incl": 275900, "specs": {}},
            {"variant_name": "1.2 GLX CVT", "price_incl": 295900, "specs": {}},
        ],
    },
    "swift-sport": {
        "brand": "suzuki",
        "model_slug": "swift-sport",
        "model_name": "Swift Sport",
        "source": "suzukiauto.co.za",
        "source_url": "https://www.suzukiauto.co.za/cars/swift-sport",
        "scraped_at": NOW,
        "variants": [
            {"variant_name": "1.4 Turbo MT", "price_incl": 469900, "specs": {}},
            {"variant_name": "1.4 Turbo AT", "price_incl": 493900, "specs": {}},
        ],
    },
}

for slug, model_data in new_models.items():
    model_data["variant_count"] = len(model_data["variants"])
    out = RAW_DIR / f"{slug}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(model_data, f, indent=2, ensure_ascii=False)
    print(f"  Added {slug}: {len(model_data['variants'])} variants")

# === SUMMARY ===
print(f"\nDone. Run 'python run_feed.py --quickpic --brands suzuki' to recompile.")
