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


def build_vehicle_element(brand_key: str, brand_name: str, model_slug: str,
                          variant: dict, images: list[dict] | None,
                          model_name: str = "") -> Element:
    """Build a single <Vehicle> XML element."""
    vehicle = Element("Vehicle")

    # Core fields
    _sub(vehicle, "Brand", brand_name)
    # Use model_name from data if available (QuickPic), otherwise derive from slug
    model_display = model_name or model_slug.replace("-", " ").replace("_", " ").title()
    _sub(vehicle, "Model", model_display)
    _sub(vehicle, "Variant", variant.get("variant_name", ""))

    # Pricing
    price_incl = variant.get("price_incl")
    _sub(vehicle, "PriceIncl", str(price_incl) if price_incl else "")
    price_excl = calc_excl_price(price_incl)
    _sub(vehicle, "PriceExcl", str(price_excl) if price_excl else "")

    # Source URL
    _sub(vehicle, "SourceURL", variant.get("source_url", ""))

    # Specs
    specs = variant.get("specs", {})
    specs_el = SubElement(vehicle, "Specifications")

    spec_fields = [
        ("EngineCapacity", "engine_capacity"),
        ("PowerKW", "power_kw"),
        ("TorqueNM", "torque_nm"),
        ("FuelType", "fuel_type"),
        ("Cylinders", "cylinders"),
        ("Transmission", "transmission"),
        ("Drivetrain", "drivetrain"),
        ("TopSpeedKMH", "top_speed_kmh"),
        ("Acceleration0to100", "acceleration_0_100"),
        ("FuelConsumptionL100KM", "fuel_consumption_l100km"),
        ("CO2EmissionsGKM", "co2_emissions_gkm"),
        ("LengthMM", "length_mm"),
        ("WidthMM", "width_mm"),
        ("HeightMM", "height_mm"),
        ("WheelbaseMM", "wheelbase_mm"),
        ("BootCapacityL", "boot_capacity_l"),
        ("KerbWeightKG", "kerb_weight_kg"),
        ("FuelTankL", "fuel_tank_l"),
        ("GroundClearanceMM", "ground_clearance_mm"),
        ("TurningCircleM", "turning_circle_m"),
        ("Airbags", "airbags"),
        ("ABS", "abs"),
        ("StabilityControl", "stability_control"),
        ("Warranty", "warranty"),
        ("ServicePlan", "service_plan"),
    ]

    for xml_name, spec_key in spec_fields:
        _sub(specs_el, xml_name, specs.get(spec_key, ""))

    # Images
    images_el = SubElement(vehicle, "Images")
    if images:
        for img in images:
            img_el = SubElement(images_el, "Image")
            img_el.set("type", img.get("type", ""))
            img_el.text = img.get("url", "")

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

    root = Element("VehicleFeed")
    root.set("generated", time.strftime("%Y-%m-%dT%H:%M:%S"))
    root.set("generator", "SACarFeedBot/1.0")

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

    for brand_key in sorted(raw.keys()):
        if brands_filter and brand_key not in brands_filter:
            continue

        brand_name = brand_names.get(brand_key, brand_key.upper())
        brand_el = SubElement(root, "Brand")
        brand_el.set("name", brand_name)
        brand_el.set("key", brand_key)

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
                    model_name=spec_data.get("model_name", "")
                )
                brand_el.append(vehicle_el)
                brand_vehicle_count += 1

        brand_el.set("vehicleCount", str(brand_vehicle_count))
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
