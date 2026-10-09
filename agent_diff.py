"""
Diff Agent — compares current JSON feed vs previous JSON feed.
Flags: NEW MODEL, NEW VARIANT, PRICE CHANGE, DISCONTINUED MODEL,
       DISCONTINUED VARIANT, SPEC CHANGE.
Outputs changes as JSON.
Falls back to XML if no JSON previous feed exists.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
PREV_DIR = Path(__file__).parent / "previous_feeds"

PRICE_CHANGE_THRESHOLD = 100  # Ignore price changes smaller than R100


# ─── Load helpers ────────────────────────────────────────────────────

def load_json_feed(path: str) -> dict:
    """Parse JSON feed into a flat dict keyed by brand|model|variant."""
    vehicles = {}
    try:
        with open(path) as f:
            feed = json.load(f)

        for brand in feed.get("brands", []):
            brand_name = brand.get("name", "")
            brand_key = brand.get("key", "")

            for model in brand.get("models", []):
                model_name = model.get("name", "")
                model_slug = model.get("slug", "")

                for variant in model.get("variants", []):
                    vname = variant.get("name", "")
                    key = f"{brand_key}|{model_slug}|{vname}"

                    vehicles[key] = {
                        "brand": brand_name,
                        "brand_key": brand_key,
                        "model": model_name,
                        "model_slug": model_slug,
                        "variant": vname,
                        "price_incl": variant.get("price_incl"),
                        "price_display": variant.get("price_display", ""),
                        "monthly_estimate": variant.get("monthly_estimate"),
                        "specs": variant.get("specs", {}),
                    }
    except Exception as e:
        print(f"  Error parsing {path}: {e}")

    return vehicles


def load_xml_feed(path: str) -> dict:
    """Legacy: parse our StockFeedVehicles XML into same flat dict format."""
    from xml.etree.ElementTree import parse
    vehicles = {}
    try:
        tree = parse(path)
        root = tree.getroot()

        for vehicle_el in root.findall("StockFeedVehicle"):
            brand_name = vehicle_el.findtext("MMMake", "")
            model = vehicle_el.findtext("MMModel", "")
            variant = vehicle_el.findtext("MMDerivative", "")

            # Build key compatible with JSON loader: brand_key|model_slug|variant_name
            brand_key = brand_name.lower()
            # model slug: lowercase, spaces→hyphens (matches our slug convention)
            model_slug = model.lower().replace(" ", "-")

            key = f"{brand_key}|{model_slug}|{variant}"

            price_text = vehicle_el.findtext("VehicleRetailPriceIncl", "")
            price = int(price_text) if price_text and price_text.isdigit() else None

            # Pull specs from XML fields
            specs = {}
            spec_fields = {
                "Transmission": "transmission",
                "FuelType": "fuel_type",
                "Drivetrain": "drivetrain",
                "BodyType": "body_type",
                "VehicleEngine": "engine_capacity",
                "PowerKW": "power_kw",
                "TorqueNM": "torque_nm",
            }
            for xml_tag, spec_key in spec_fields.items():
                val = vehicle_el.findtext(xml_tag, "")
                if val:
                    specs[spec_key] = val

            vehicles[key] = {
                "brand": brand_name,
                "brand_key": brand_key,
                "model": model,
                "model_slug": model_slug,
                "variant": variant,
                "price_incl": price,
                "price_display": "",
                "monthly_estimate": None,
                "specs": specs,
            }
    except Exception as e:
        print(f"  Error parsing XML {path}: {e}")
    return vehicles


def load_feed(path: str) -> dict:
    """Auto-detect JSON or XML and load."""
    if path.endswith(".json"):
        return load_json_feed(path)
    return load_xml_feed(path)


# ─── Diff logic ──────────────────────────────────────────────────────

def diff_feeds(current: dict, previous: dict) -> list[dict]:
    """Compare current vs previous feed, return list of changes."""
    changes = []

    # Track model-level changes (not just variant)
    current_models = {f"{v['brand_key']}|{v['model_slug']}" for v in current.values()}
    previous_models = {f"{v['brand_key']}|{v['model_slug']}" for v in previous.values()}

    new_models = current_models - previous_models
    dropped_models = previous_models - current_models

    # Flag new models (pick first variant as representative)
    for model_key in new_models:
        rep = next((v for v in current.values()
                    if f"{v['brand_key']}|{v['model_slug']}" == model_key), None)
        if rep:
            changes.append({
                "type": "NEW MODEL",
                "brand": rep["brand"],
                "model": rep["model"],
                "variant": "",
                "price_incl": None,
                "details": f"New model added with variants in current feed",
            })

    # Flag discontinued models
    for model_key in dropped_models:
        rep = next((v for v in previous.values()
                    if f"{v['brand_key']}|{v['model_slug']}" == model_key), None)
        if rep:
            changes.append({
                "type": "DISCONTINUED MODEL",
                "brand": rep["brand"],
                "model": rep["model"],
                "variant": "",
                "price_incl": None,
                "details": f"Model removed from feed",
            })

    # New variants (within existing models)
    for key in current:
        if key not in previous:
            v = current[key]
            model_key = f"{v['brand_key']}|{v['model_slug']}"
            if model_key not in new_models:
                changes.append({
                    "type": "NEW VARIANT",
                    "brand": v["brand"],
                    "model": v["model"],
                    "variant": v["variant"],
                    "price_incl": v["price_incl"],
                    "details": f"Added at {v.get('price_display', '')}",
                })

    # Discontinued variants (within models that still exist)
    for key in previous:
        if key not in current:
            v = previous[key]
            model_key = f"{v['brand_key']}|{v['model_slug']}"
            if model_key not in dropped_models:
                changes.append({
                    "type": "DISCONTINUED VARIANT",
                    "brand": v["brand"],
                    "model": v["model"],
                    "variant": v["variant"],
                    "price_incl": v["price_incl"],
                    "details": "",
                })

    # Price and spec changes on surviving variants
    for key in current:
        if key in previous:
            curr = current[key]
            prev = previous[key]

            # Price change
            if curr["price_incl"] and prev["price_incl"]:
                diff = curr["price_incl"] - prev["price_incl"]
                if abs(diff) >= PRICE_CHANGE_THRESHOLD:
                    direction = "UP" if diff > 0 else "DOWN"
                    pct = abs(diff) / prev["price_incl"] * 100
                    changes.append({
                        "type": "PRICE CHANGE",
                        "brand": curr["brand"],
                        "model": curr["model"],
                        "variant": curr["variant"],
                        "price_incl": curr["price_incl"],
                        "details": (
                            f"{direction} R{abs(diff):,} ({pct:.1f}%) — "
                            f"was R{prev['price_incl']:,}, now R{curr['price_incl']:,}"
                        ),
                    })

            # Spec changes
            curr_specs = curr.get("specs", {})
            prev_specs = prev.get("specs", {})
            changed_specs = []

            all_keys = set(list(curr_specs.keys()) + list(prev_specs.keys()))
            for spec_key in sorted(all_keys):
                curr_val = curr_specs.get(spec_key, "")
                prev_val = prev_specs.get(spec_key, "")
                if str(curr_val) != str(prev_val) and (curr_val or prev_val):
                    changed_specs.append({
                        "field": spec_key,
                        "was": str(prev_val) if prev_val else "(empty)",
                        "now": str(curr_val) if curr_val else "(removed)",
                    })

            if changed_specs:
                summary = "; ".join(
                    f"{s['field']}: {s['was']} → {s['now']}"
                    for s in changed_specs[:10]
                )
                changes.append({
                    "type": "SPEC CHANGE",
                    "brand": curr["brand"],
                    "model": curr["model"],
                    "variant": curr["variant"],
                    "price_incl": curr["price_incl"],
                    "details": summary,
                    "spec_changes": changed_specs,
                })

    return changes


# ─── Output ──────────────────────────────────────────────────────────

def build_changes_json(changes: list[dict], current_path: str,
                       previous_path: str) -> dict:
    """Build JSON diff report."""
    type_counts = {}
    for c in changes:
        type_counts[c["type"]] = type_counts.get(c["type"], 0) + 1

    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "compared": {
            "current": current_path,
            "previous": previous_path,
        },
        "summary": {
            "total_changes": len(changes),
            "by_type": type_counts,
        },
        "changes": sorted(
            changes,
            key=lambda x: (x["type"], x["brand"], x["model"], x.get("variant", "")),
        ),
    }


# ─── Entry point ─────────────────────────────────────────────────────

def run_diff(current_path: str = None, previous_path: str = None) -> str:
    """Run diff between current and previous feed."""
    # Current: prefer JSON
    if not current_path:
        json_path = OUTPUT_DIR / "sa_car_feed_latest.json"
        xml_path = OUTPUT_DIR / "sa_car_feed_latest.xml"
        if json_path.exists():
            current_path = str(json_path)
        elif xml_path.exists():
            current_path = str(xml_path)

    # Previous: prefer JSON, fall back to XML
    if not previous_path:
        prev_json = sorted(PREV_DIR.glob("sa_car_feed_*.json"))
        prev_xml = sorted(PREV_DIR.glob("sa_car_feed_*.xml"))
        if prev_json:
            previous_path = str(prev_json[-1])
        elif prev_xml:
            previous_path = str(prev_xml[-1])

    if not current_path or not Path(current_path).exists():
        print(f"[Diff] Current feed not found: {current_path}")
        return ""
    if not previous_path or not Path(previous_path).exists():
        print("[Diff] No previous feed found in previous_feeds/")
        return ""

    print(f"[Diff] Comparing:")
    print(f"  Current:  {current_path}")
    print(f"  Previous: {previous_path}")

    current = load_feed(current_path)
    previous = load_feed(previous_path)

    changes = diff_feeds(current, previous)

    if not changes:
        print("  No changes detected.")
        return ""

    report = build_changes_json(changes, current_path, previous_path)

    # Save
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_file = OUTPUT_DIR / f"feed_changes_{timestamp}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Print summary
    print(f"\n  Changes detected: {len(changes)}")
    for t, count in sorted(report["summary"]["by_type"].items()):
        print(f"    {t:25s} {count}")
    print(f"  Saved to: {out_file}")

    return str(out_file)


if __name__ == "__main__":
    current = sys.argv[1] if len(sys.argv) > 1 else None
    previous = sys.argv[2] if len(sys.argv) > 2 else None

    result = run_diff(current, previous)
    if not result:
        print("No diff output generated.")
