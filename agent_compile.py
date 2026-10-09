"""
Compiler Agent — reads all raw_data/ JSON files, merges specs + images,
calculates excl price, validates, and outputs:
  1. Per-brand JSON files  (output/brands/{brand}.json)
  2. Combined JSON feed    (output/sa_car_feed_latest.json)
  3. Legacy XML feed       (output/sa_car_feed_latest.xml)  — kept for backward compat
"""
from __future__ import annotations

import json
import sys
import time
import re
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring, indent

RAW_DIR = Path(__file__).parent / "raw_data"
OUTPUT_DIR = Path(__file__).parent / "output"
DEALERS_FILE = Path(__file__).parent / "dealers.json"
VAT_RATE = 1.15


def load_raw_data() -> dict:
    """Load all raw JSON data, organized by brand/model."""
    data = {}
    if not RAW_DIR.exists():
        return data

    for brand_dir in RAW_DIR.iterdir():
        if not brand_dir.is_dir():
            continue
        brand_key = brand_dir.name
        data[brand_key] = {}

        for json_file in brand_dir.glob("*.json"):
            if json_file.name.endswith("_images.json"):
                continue
            model_slug = json_file.stem
            with open(json_file) as f:
                spec_data = json.load(f)

            img_file = brand_dir / f"{model_slug}_images.json"
            img_data = None
            if img_file.exists():
                with open(img_file) as f:
                    img_data = json.load(f)

            data[brand_key][model_slug] = {
                "specs": spec_data,
                "images": img_data,
            }

    return data


def calc_excl_price(incl_price):
    """Calculate price excluding VAT (15%)."""
    if incl_price is None:
        return None
    return round(incl_price / VAT_RATE)


def format_price(price) -> str:
    """R 238,000 display format."""
    if price is None:
        return ""
    return f"R{price:,.0f}".replace(",", " ")


def estimate_monthly(price_incl, rate=0.115, term=72, balloon=0, deposit_pct=0):
    """Simple installment estimate. Default: 11.5% over 72 months, no balloon/deposit."""
    if not price_incl:
        return None
    deposit = price_incl * deposit_pct
    finance_amount = price_incl - deposit
    monthly_rate = rate / 12
    if monthly_rate == 0:
        return round(finance_amount / term)
    pmt = finance_amount * (monthly_rate * (1 + monthly_rate) ** term) / ((1 + monthly_rate) ** term - 1)
    return round(pmt)


def slugify(text: str) -> str:
    """Turn 'MAX 1.2T AT (7-seater)' into 'max-1-2t-at-7-seater'."""
    import re as _re
    s = text.lower().strip()
    s = _re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


# ─── Brand display names ─────────────────────────────────────────────

def load_brand_names() -> dict:
    brand_names = {}
    brand_urls_file = Path(__file__).parent / "brand_urls.json"
    if brand_urls_file.exists():
        with open(brand_urls_file) as f:
            brand_config = json.load(f)
        for tier in ("tier1", "tier2"):
            for key, cfg in brand_config.get(tier, {}).items():
                brand_names[key] = cfg["name"]
    return brand_names


# ─── Image priority ───────────────────────────────────────────────────

IMAGE_TYPE_PRIORITY = {
    "Jellybean": 1,
    "ExteriorFront": 2,
    "ExteriorRear": 3,
    "Interior": 4,
    "Lifestyle": 5,
}


# ─── JSON Feed Builder ───────────────────────────────────────────────

def build_json_model(brand_key: str, brand_name: str, model_slug: str,
                     spec_data: dict, images: list[dict]) -> dict:
    """Build a clean JSON model object with all variants and images."""
    model_name = spec_data.get("model_name", model_slug.replace("-", " ").title())

    # Sort images by priority
    sorted_images = sorted(images, key=lambda i: IMAGE_TYPE_PRIORITY.get(i.get("type", ""), 99))

    # Pick hero image (first jellybean, else first image)
    hero_image = ""
    for img in sorted_images:
        if img.get("type") == "Jellybean":
            hero_image = img["url"]
            break
    if not hero_image and sorted_images:
        hero_image = sorted_images[0]["url"]

    model_obj = {
        "slug": model_slug,
        "name": model_name,
        "brand": brand_name,
        "brand_key": brand_key,
        "hero_image": hero_image,
        "source_url": spec_data.get("source_url", ""),
        "images": [
            {
                "url": img["url"],
                "type": img.get("type", ""),
                "priority": IMAGE_TYPE_PRIORITY.get(img.get("type", ""), 99),
            }
            for img in sorted_images
        ],
        "variants": [],
    }

    # Price range across variants
    prices = [v["price_incl"] for v in spec_data.get("variants", []) if v.get("price_incl")]
    if prices:
        model_obj["price_from"] = min(prices)
        model_obj["price_to"] = max(prices)
        model_obj["price_range"] = format_price(min(prices))
        if min(prices) != max(prices):
            model_obj["price_range"] += f" – {format_price(max(prices))}"

    # Grab shared model-level info from the first variant (body type, fuel, warranty)
    first_specs = {}
    if spec_data.get("variants"):
        first_specs = spec_data["variants"][0].get("specs", {})
    model_obj["body_type"] = first_specs.get("body_type", "")
    model_obj["fuel_type"] = first_specs.get("fuel_type", "")

    for variant in spec_data.get("variants", []):
        price_incl = variant.get("price_incl")
        price_excl = calc_excl_price(price_incl)
        specs = variant.get("specs", {})

        v_obj = {
            "name": variant.get("variant_name", ""),
            "slug": slugify(variant.get("variant_name", "")),
            "price_incl": price_incl,
            "price_excl": price_excl,
            "price_display": format_price(price_incl),
            "monthly_estimate": estimate_monthly(price_incl),
            "specs": {
                "engine_capacity": specs.get("engine_capacity", ""),
                "power_kw": specs.get("power_kw", ""),
                "torque_nm": specs.get("torque_nm", ""),
                "fuel_type": specs.get("fuel_type", ""),
                "transmission": specs.get("transmission", ""),
                "drivetrain": specs.get("drivetrain", ""),
                "body_type": specs.get("body_type", ""),
                "fuel_consumption_l100km": specs.get("fuel_consumption_l100km", ""),
                "co2_gkm": specs.get("co2_gkm", ""),
                "seats": specs.get("seats", ""),
                "airbags": specs.get("airbags", ""),
                "fuel_tank_l": specs.get("fuel_tank_l", ""),
                "warranty": specs.get("warranty", ""),
                "service_plan": specs.get("service_plan", ""),
            },
        }

        # MM code (SA MotorManufacturer code) — used by dealer DMS / finance systems
        mm_code = variant.get("mm_code") or specs.get("mm_code")
        if mm_code:
            v_obj["mm_code"] = mm_code

        # Include dimensions if present (not all models have them)
        dims = {}
        for dim_key in ("length_mm", "width_mm", "height_mm", "wheelbase_mm",
                        "ground_clearance_mm", "kerb_weight_kg"):
            val = specs.get(dim_key, "")
            if val:
                dims[dim_key] = val
        if dims:
            v_obj["dimensions"] = dims

        # Strip empty strings from specs to keep it clean
        v_obj["specs"] = {k: v for k, v in v_obj["specs"].items() if v}

        model_obj["variants"].append(v_obj)

    model_obj["variant_count"] = len(model_obj["variants"])
    return model_obj


def build_json_brand(brand_key: str, brand_name: str,
                     models_data: dict) -> dict:
    """Build a complete brand JSON object."""
    brand_obj = {
        "key": brand_key,
        "name": brand_name,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "models": [],
        "total_variants": 0,
    }

    for model_slug in sorted(models_data.keys()):
        md = models_data[model_slug]
        spec_data = md["specs"]
        img_data = md.get("images")
        images = img_data.get("images", []) if img_data else []

        model_obj = build_json_model(brand_key, brand_name, model_slug,
                                     spec_data, images)
        brand_obj["models"].append(model_obj)
        brand_obj["total_variants"] += model_obj["variant_count"]

    brand_obj["model_count"] = len(brand_obj["models"])

    # Brand-level price range
    all_prices = []
    for m in brand_obj["models"]:
        for v in m["variants"]:
            if v.get("price_incl"):
                all_prices.append(v["price_incl"])
    if all_prices:
        brand_obj["price_from"] = min(all_prices)
        brand_obj["price_to"] = max(all_prices)

    return brand_obj


# ─── Dealer bundles ──────────────────────────────────────────────────

def load_dealers() -> dict:
    """Load dealers.json → {dealer_key: {name, brands[], ...}}."""
    if not DEALERS_FILE.exists():
        return {}
    with open(DEALERS_FILE) as f:
        data = json.load(f)
    return data.get("dealers", {})


def build_dealer_bundles(brand_objects: dict[str, dict]):
    """Write output/dealers/{dealer_key}.json for each dealer in dealers.json.

    Each bundle is a self-contained feed: dealer info + its brands' data,
    ready for a website session to import as-is.
    """
    dealers = load_dealers()
    if not dealers:
        return

    dealers_dir = OUTPUT_DIR / "dealers"
    dealers_dir.mkdir(exist_ok=True)

    for dealer_key, dealer_cfg in dealers.items():
        dealer_brands = dealer_cfg.get("brands", [])
        bundle = {
            "dealer": dealer_key,
            "dealer_name": dealer_cfg.get("name", dealer_key),
            "dealership_id": dealer_cfg.get("dealership_id", ""),
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "brands": [],
            "total_models": 0,
            "total_vehicles": 0,
        }

        for bk in dealer_brands:
            if bk in brand_objects:
                brand_obj = brand_objects[bk]
                bundle["brands"].append(brand_obj)
                bundle["total_models"] += brand_obj.get("model_count", 0)
                bundle["total_vehicles"] += brand_obj.get("total_variants", 0)

        # Price range across all dealer's brands
        all_prices = []
        for b in bundle["brands"]:
            if b.get("price_from"):
                all_prices.append(b["price_from"])
            if b.get("price_to"):
                all_prices.append(b["price_to"])
        if all_prices:
            bundle["price_from"] = min(all_prices)
            bundle["price_to"] = max(all_prices)

        bundle_file = dealers_dir / f"{dealer_key}.json"
        with open(bundle_file, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False)
            f.write("\n")

        print(f"  Dealer bundle: {dealer_key} — "
              f"{len(bundle['brands'])} brands, "
              f"{bundle['total_vehicles']} vehicles → {bundle_file.name}")


# ─── Legacy XML Builder (kept for backward compat) ────────────────────

def build_vehicle_element(brand_key, brand_name, model_slug, variant,
                          images, model_name="", variant_index=0):
    """Build a single <StockFeedVehicle> XML element."""
    vehicle = Element("StockFeedVehicle")
    model_display = model_name or model_slug.replace("-", " ").replace("_", " ").title()
    variant_name = variant.get("variant_name", "")
    stock_num = f"NEW-{brand_key.upper()}-{model_slug.upper()}-{variant_index:03d}"

    _sub(vehicle, "StockNumber", stock_num)
    _sub(vehicle, "DealershipID", "EMOND")
    _sub(vehicle, "Department", "New")
    _sub(vehicle, "MMMake", brand_name)
    _sub(vehicle, "MMModel", model_display)
    _sub(vehicle, "MMDerivative", variant_name)
    _sub(vehicle, "VehicleModel", f"{model_display} {variant_name}".strip())
    _sub(vehicle, "VehicleCategory", "New")
    _sub(vehicle, "VehicleYear", time.strftime("%Y"))
    _sub(vehicle, "Condition", "New")
    _sub(vehicle, "VehicleMileage", "0")

    price_incl = variant.get("price_incl")
    _sub(vehicle, "VehicleRetailPriceIncl", str(price_incl) if price_incl else "")
    price_excl = calc_excl_price(price_incl)
    _sub(vehicle, "VehicleRetailPriceExcl", str(price_excl) if price_excl else "")

    specs = variant.get("specs", {})
    _sub(vehicle, "Transmission", specs.get("transmission", ""))
    _sub(vehicle, "FuelType", specs.get("fuel_type", ""))
    _sub(vehicle, "Drivetrain", specs.get("drivetrain", ""))
    _sub(vehicle, "BodyType", specs.get("body_type", ""))
    _sub(vehicle, "VehicleColour", "")
    _sub(vehicle, "VehicleFullServiceHistory", "")
    _sub(vehicle, "VehicleVIN", "")
    _sub(vehicle, "VehicleRegNo", "")
    _sub(vehicle, "VehicleEngine", specs.get("engine_capacity", ""))
    _sub(vehicle, "PowerKW", specs.get("power_kw", ""))
    _sub(vehicle, "TorqueNM", specs.get("torque_nm", ""))
    _sub(vehicle, "VehicleMMCode", "")

    spec_parts = []
    spec_map = {
        "engine_capacity": "Engine", "power_kw": "Power (kW)",
        "torque_nm": "Torque (Nm)", "fuel_type": "Fuel",
        "body_type": "Body", "drivetrain": "Drive",
        "fuel_consumption_l100km": "Consumption (L/100km)",
        "airbags": "Airbags", "warranty": "Warranty",
        "service_plan": "Service Plan",
        "length_mm": "Length", "width_mm": "Width",
        "height_mm": "Height", "wheelbase_mm": "Wheelbase",
        "kerb_weight_kg": "Kerb Weight",
        "ground_clearance_mm": "Ground Clearance",
    }
    for key, label in spec_map.items():
        val = specs.get(key, "")
        if val:
            spec_parts.append(f"{label}: {val}")
    _sub(vehicle, "VehicleComments", " | ".join(spec_parts))
    _sub(vehicle, "VehicleExtras", "")

    images_el = SubElement(vehicle, "Images")
    if images:
        for img in images:
            img_el = SubElement(images_el, "Image")
            url = img.get("url", "")
            img_type = img.get("type", "")
            priority = IMAGE_TYPE_PRIORITY.get(img_type, 99)
            img_el.set("ThumbnailUrl", url)
            img_el.set("FullImageUrl", url)
            img_el.set("Priority", str(priority))

    return vehicle


def _sub(parent, tag, text):
    el = SubElement(parent, tag)
    if text:
        el.text = text
    return el


# ─── Main Compiler ────────────────────────────────────────────────────

def compile_feed(brands_filter: list[str] = None) -> str:
    """Compile all raw data into JSON + XML feeds. Returns output path."""
    raw = load_raw_data()
    if not raw:
        print("[Compile] No raw data found in raw_data/")
        return ""

    brand_names = load_brand_names()
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR.mkdir(exist_ok=True)
    brands_dir = OUTPUT_DIR / "brands"
    brands_dir.mkdir(exist_ok=True)

    # ── Build JSON feed ──
    feed = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "brands": [],
        "total_vehicles": 0,
        "total_models": 0,
    }

    total_vehicles = 0
    total_issues = 0
    brand_summaries = []

    # Also build legacy XML
    xml_root = Element("StockFeedVehicles")
    global_variant_index = 0

    for brand_key in sorted(raw.keys()):
        if brands_filter and brand_key not in brands_filter:
            continue

        brand_name = brand_names.get(brand_key, brand_key.upper())
        models_data = raw[brand_key]

        # JSON brand
        brand_obj = build_json_brand(brand_key, brand_name, models_data)
        feed["brands"].append(brand_obj)

        # Per-brand JSON file
        brand_file = brands_dir / f"{brand_key}.json"
        with open(brand_file, "w", encoding="utf-8") as f:
            json.dump(brand_obj, f, indent=2, ensure_ascii=False)
            f.write("\n")

        # XML legacy
        brand_vehicle_count = 0
        brand_issues = 0

        for model_slug in sorted(models_data.keys()):
            md = models_data[model_slug]
            spec_data = md["specs"]
            img_data = md.get("images")
            images = img_data.get("images", []) if img_data else []

            for variant in spec_data.get("variants", []):
                variant["source_url"] = spec_data.get("source_url", "")

                # Validate
                issues = []
                if not variant.get("variant_name"):
                    issues.append("Missing variant name")
                if not variant.get("price_incl"):
                    issues.append("Missing price")
                specs = variant.get("specs", {})
                if not specs.get("fuel_type"):
                    issues.append("Missing fuel_type")
                if not specs.get("body_type"):
                    issues.append("Missing body_type")
                brand_issues += len(issues)

                vehicle_el = build_vehicle_element(
                    brand_key, brand_name, model_slug, variant, images,
                    model_name=spec_data.get("model_name", ""),
                    variant_index=global_variant_index,
                )
                xml_root.append(vehicle_el)
                brand_vehicle_count += 1
                global_variant_index += 1

        total_vehicles += brand_vehicle_count
        total_issues += brand_issues
        brand_summaries.append((brand_name, brand_key, brand_vehicle_count, brand_issues))

    feed["total_vehicles"] = total_vehicles
    feed["total_models"] = sum(b["model_count"] for b in feed["brands"])

    # ── Dealer bundles ──
    brand_objects = {b["key"]: b for b in feed["brands"]}
    build_dealer_bundles(brand_objects)

    # ── Write JSON feeds ──
    json_file = OUTPUT_DIR / f"sa_car_feed_{timestamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2, ensure_ascii=False)
        f.write("\n")

    json_latest = OUTPUT_DIR / "sa_car_feed_latest.json"
    with open(json_latest, "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # ── Write legacy XML ──
    xml_root.set("totalVehicles", str(total_vehicles))
    indent(xml_root, space="  ")
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += tostring(xml_root, encoding="unicode", xml_declaration=False)
    xml_str = re.sub(r'<(\w+)>\s*</\1>', r'<\1/>', xml_str)

    xml_file = OUTPUT_DIR / f"sa_car_feed_{timestamp}.xml"
    with open(xml_file, "w", encoding="utf-8") as f:
        f.write(xml_str)

    xml_latest = OUTPUT_DIR / "sa_car_feed_latest.xml"
    with open(xml_latest, "w", encoding="utf-8") as f:
        f.write(xml_str)

    # ── Report ──
    print(f"\n{'='*60}")
    print(f"  SA NEW CAR FEED — Compilation Report")
    print(f"{'='*60}")
    print(f"  Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Total Vehicles: {total_vehicles}")
    print(f"  Total Models:   {feed['total_models']}")
    print(f"  Validation Issues: {total_issues}")
    print(f"{'='*60}")
    for brand_name, brand_key, count, issues in brand_summaries:
        status = "OK" if issues == 0 else f"{issues} issues"
        print(f"  {brand_name:25s}  {count:3d} vehicles  [{status}]")
    print(f"{'='*60}")
    print(f"  JSON: {json_file}")
    print(f"  XML:  {xml_file}")
    print(f"  Per-brand: {brands_dir}/")
    dealers_dir = OUTPUT_DIR / "dealers"
    if dealers_dir.exists() and list(dealers_dir.glob("*.json")):
        print(f"  Per-dealer: {dealers_dir}/")
    print(f"{'='*60}\n")

    return str(json_file)


if __name__ == "__main__":
    brands = None
    if len(sys.argv) > 1:
        brands = [b.lower() for b in sys.argv[1:]]

    result = compile_feed(brands)
    if result:
        print(f"Feed saved to: {result}")
    else:
        print("No feed generated.")
