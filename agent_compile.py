"""
Compiler Agent — reads all raw_data/ JSON files, merges specs + images,
calculates excl price, validates required fields, and outputs XML feed.
"""

import json
import sys
import time
import re
import math
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring, indent

RAW_DIR = Path(__file__).parent / "raw_data"
OUTPUT_DIR = Path(__file__).parent / "output"
VAT_RATE = 1.15

REQUIRED_FIELDS = ["brand", "model", "variant", "price_incl"]
RECOMMENDED_FIELDS = ["price_excl", "engine_capacity", "power_kw", "torque_nm",
                       "transmission", "fuel_type"]


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
                continue  # handled separately
            model_slug = json_file.stem
            with open(json_file) as f:
                spec_data = json.load(f)

            # Load matching images
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


def calc_excl_price(incl_price: int | None) -> int | None:
    """Calculate price excluding VAT (15%)."""
    if incl_price is None:
        return None
    return round(incl_price / VAT_RATE)


# Image type to priority mapping (Jellybean=hero shot gets priority 1)
IMAGE_TYPE_PRIORITY = {
    "Jellybean": 1,
    "ExteriorFront": 2,
    "ExteriorRear": 3,
    "Interior": 4,
    "Lifestyle": 5,
}


def build_vehicle_element(brand_key: str, brand_name: str, model_slug: str,
                          variant: dict, images: list[dict] | None,
                          model_name: str = "",
                          variant_index: int = 0) -> Element:
    """Build a single <StockFeedVehicle> XML element (EasyQuote-compatible)."""
    vehicle = Element("StockFeedVehicle")

    model_display = model_name or model_slug.replace("-", " ").replace("_", " ").title()
    variant_name = variant.get("variant_name", "")

    # Generate a stable stock number from brand + model + variant index
    stock_num = f"NEW-{brand_key.upper()}-{model_slug.upper()}-{variant_index:03d}"

    # EasyQuote-compatible fields
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

    # Pricing
    price_incl = variant.get("price_incl")
    _sub(vehicle, "VehicleRetailPriceIncl", str(price_incl) if price_incl else "")
    price_excl = calc_excl_price(price_incl)
    _sub(vehicle, "VehicleRetailPriceExcl", str(price_excl) if price_excl else "")

    # Specs as extras/comments
    specs = variant.get("specs", {})
    _sub(vehicle, "Transmission", specs.get("transmission", ""))
    _sub(vehicle, "Drivetrain", specs.get("drivetrain", ""))
    _sub(vehicle, "VehicleColour", "")
    _sub(vehicle, "VehicleFullServiceHistory", "")
    _sub(vehicle, "VehicleVIN", "")
    _sub(vehicle, "VehicleRegNo", "")
    _sub(vehicle, "VehicleEngine", specs.get("engine_capacity", ""))
    _sub(vehicle, "VehicleMMCode", "")

    # Build specs string for comments
    spec_parts = []
    spec_map = {
        "engine_capacity": "Engine", "power_kw": "Power (kW)",
        "torque_nm": "Torque (Nm)", "fuel_type": "Fuel",
        "fuel_consumption_l": "Consumption (L/100km)",
        "fuel_consumption_l100km": "Consumption (L/100km)",
        "airbags": "Airbags", "warranty": "Warranty",
        "service_plan": "Service Plan",
    }
    for key, label in spec_map.items():
        val = specs.get(key, "")
        if val:
            spec_parts.append(f"{label}: {val}")
    _sub(vehicle, "VehicleComments", " | ".join(spec_parts))
    _sub(vehicle, "VehicleExtras", "")

    # Images — EasyQuote format: ThumbnailUrl, FullImageUrl, Priority attributes
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


def _sub(parent: Element, tag: str, text: str) -> Element:
    """Add a subelement with text. Self-closing if empty."""
    el = SubElement(parent, tag)
    if text:
        el.text = text
    return el


def validate_vehicle(vehicle_data: dict) -> list[str]:
    """Validate a vehicle record, return list of issues."""
    issues = []
    if not vehicle_data.get("variant_name"):
        issues.append("Missing variant name")
    if not vehicle_data.get("price_incl"):
        issues.append("Missing price")
    specs = vehicle_data.get("specs", {})
    if not specs:
        issues.append("No specs found")
    return issues


def compile_feed(brands_filter: list[str] = None) -> str:
    """Compile all raw data into XML feed. Returns output file path."""
    raw = load_raw_data()
    if not raw:
        print("[Compile] No raw data found in raw_data/")
        return ""

    root = Element("StockFeedVehicles")

    total_vehicles = 0
    total_issues = 0
    brand_summaries = []

    # Load brand names from brand_urls.json
    brand_names = {}
    brand_urls_file = Path(__file__).parent / "brand_urls.json"
    if brand_urls_file.exists():
        with open(brand_urls_file) as f:
            brand_config = json.load(f)
        for tier in ("tier1", "tier2"):
            for key, cfg in brand_config[tier].items():
                brand_names[key] = cfg["name"]

    global_variant_index = 0

    for brand_key in sorted(raw.keys()):
        if brands_filter and brand_key not in brands_filter:
            continue

        brand_name = brand_names.get(brand_key, brand_key.upper())

        brand_vehicle_count = 0
        brand_issues = 0

        for model_slug, model_data in sorted(raw[brand_key].items()):
            spec_data = model_data["specs"]
            img_data = model_data.get("images")
            images = img_data.get("images", []) if img_data else []

            variants = spec_data.get("variants", [])
            for variant in variants:
                variant["source_url"] = spec_data.get("source_url", "")
                issues = validate_vehicle(variant)
                if issues:
                    brand_issues += len(issues)

                vehicle_el = build_vehicle_element(
                    brand_key, brand_name, model_slug, variant, images,
                    model_name=spec_data.get("model_name", ""),
                    variant_index=global_variant_index,
                )
                root.append(vehicle_el)
                brand_vehicle_count += 1
                global_variant_index += 1

        total_vehicles += brand_vehicle_count
        total_issues += brand_issues
        brand_summaries.append((brand_name, brand_vehicle_count, brand_issues))

    root.set("totalVehicles", str(total_vehicles))

    # Format XML
    indent(root, space="  ")
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += tostring(root, encoding="unicode", xml_declaration=False)

    # Ensure self-closing empty tags
    xml_str = re.sub(r'<(\w+)>\s*</\1>', r'<\1/>', xml_str)

    # Save
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_file = OUTPUT_DIR / f"sa_car_feed_{timestamp}.xml"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(xml_str)

    # Also save as latest
    latest_file = OUTPUT_DIR / "sa_car_feed_latest.xml"
    with open(latest_file, "w", encoding="utf-8") as f:
        f.write(xml_str)

    # Print report
    print(f"\n{'='*60}")
    print(f"  SA NEW CAR FEED — Compilation Report")
    print(f"{'='*60}")
    print(f"  Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Total Vehicles: {total_vehicles}")
    print(f"  Total Validation Issues: {total_issues}")
    print(f"  Output: {out_file}")
    print(f"{'='*60}")
    for brand_name, count, issues in brand_summaries:
        status = "OK" if issues == 0 else f"{issues} issues"
        print(f"  {brand_name:25s}  {count:3d} vehicles  [{status}]")
    print(f"{'='*60}\n")

    return str(out_file)


if __name__ == "__main__":
    brands = None
    if len(sys.argv) > 1:
        brands = [b.lower() for b in sys.argv[1:]]

    result = compile_feed(brands)
    if result:
        print(f"Feed saved to: {result}")
    else:
        print("No feed generated.")
