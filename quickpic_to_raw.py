"""
QuickPic Catalogue → raw_data converter.
Reads quickpic_catalogue.json and generates raw_data/{brand}/{model_slug}.json
files in the format the compiler expects.

Usage:
  python quickpic_to_raw.py                # All 22 target brands
  python quickpic_to_raw.py --brand vw     # Single brand
  python quickpic_to_raw.py --keep-oem     # Don't clear existing raw_data
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

BASE_DIR = Path(__file__).parent
CATALOGUE_FILE = BASE_DIR / "quickpic_catalogue.json"
SPECS_DIR = BASE_DIR / "quickpic_specs"
RAW_DIR = BASE_DIR / "raw_data"

# Map QuickPic spec keys (PascalCase) to compiler keys (snake_case)
SPEC_KEY_MAP = {
    "EngineCapacity": "engine_capacity",
    "PowerKW": "power_kw",
    "TorqueNM": "torque_nm",
    "FuelType": "fuel_type",
    "Cylinders": "cylinders",
    "Transmission": "transmission",
    "Drivetrain": "drivetrain",
    "TopSpeedKMH": "top_speed_kmh",
    "Acceleration0to100": "acceleration_0_100",
    "FuelConsumptionL100KM": "fuel_consumption_l100km",
    "CO2EmissionsGKM": "co2_emissions_gkm",
    "LengthMM": "length_mm",
    "WidthMM": "width_mm",
    "HeightMM": "height_mm",
    "WheelbaseMM": "wheelbase_mm",
    "BootCapacityL": "boot_capacity_l",
    "KerbWeightKG": "kerb_weight_kg",
    "FuelTankL": "fuel_tank_l",
    "GroundClearanceMM": "ground_clearance_mm",
    "TurningCircleM": "turning_circle_m",
    "Airbags": "airbags",
    "ABS": "abs",
    "StabilityControl": "stability_control",
    "Warranty": "warranty",
    "ServicePlan": "service_plan",
}


def load_specs_for_variant(brand: str, model: str, variant_name: str) -> dict:
    """Load specs from quickpic_specs/ for a specific variant."""
    # Build filename matching how quickpic_fetch_specs.py saves them:
    # spaces -> _, keep dots and hyphens
    safe_variant = variant_name.replace(' ', '_')
    filename = f"{brand}_{model}_{safe_variant}.json"
    spec_file = SPECS_DIR / filename
    if not spec_file.exists():
        # Try alternative: also replace special chars
        safe_variant2 = re.sub(r'[^\w\.\-]', '_', variant_name)
        filename2 = f"{brand}_{model}_{safe_variant2}.json"
        spec_file = SPECS_DIR / filename2
    if not spec_file.exists():
        return {}
    with open(spec_file, encoding="utf-8") as f:
        data = json.load(f)
    raw_specs = data.get("specifications", {})
    # Map to snake_case keys
    mapped = {}
    for pascal_key, snake_key in SPEC_KEY_MAP.items():
        val = raw_specs.get(pascal_key, "")
        if val:
            mapped[snake_key] = val
    return mapped

# 22 target brands (everything except nissan)
TARGET_BRANDS = {
    "vw", "toyota", "ford", "hyundai", "kia", "bmw", "mercedes", "audi",
    "mazda", "honda", "renault", "volvo", "jeep", "mitsubishi", "mg",
    "suzuki", "isuzu", "subaru", "gwm", "haval", "chery", "baic",
}


def slugify(name: str) -> str:
    """Convert model name to clean slug: lowercase, dash-separated."""
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9\-]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s


def parse_price(price_str: str) -> int | None:
    """Parse price string like '373800' or 'R 373 800' to integer."""
    if not price_str:
        return None
    cleaned = re.sub(r'[^\d]', '', str(price_str))
    if not cleaned:
        return None
    return int(cleaned)


def convert_catalogue(brands_filter: set[str] | None = None, keep_oem: bool = False):
    """Convert QuickPic catalogue to raw_data files."""
    with open(CATALOGUE_FILE) as f:
        catalogue = json.load(f)

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    total_vehicles = 0
    total_models = 0
    brand_summaries = []

    brands_to_process = brands_filter or TARGET_BRANDS

    for brand_key, brand_data in catalogue.items():
        # Skip _extra_ brands
        if brand_key.startswith("_extra_"):
            continue
        # Skip brands not in our target set
        if brand_key not in brands_to_process:
            continue

        brand_dir = RAW_DIR / brand_key

        # Clear existing raw_data for this brand (preserves _images.json files)
        if not keep_oem and brand_dir.exists():
            for f in brand_dir.glob("*.json"):
                if not f.name.endswith("_images.json"):
                    f.unlink()

        brand_dir.mkdir(parents=True, exist_ok=True)

        brand_vehicle_count = 0
        brand_model_count = 0

        models = brand_data.get("models", {})
        for model_name, model_data in models.items():
            model_slug = slugify(model_name)
            variants_raw = model_data.get("variants", [])

            if not variants_raw:
                continue

            variants = []
            for v in variants_raw:
                price = parse_price(v.get("price", ""))
                specs = load_specs_for_variant(brand_key, model_name, v["name"])
                variants.append({
                    "variant_name": v["name"],
                    "price_incl": price,
                    "specs": specs,
                })

            raw_entry = {
                "brand": brand_key,
                "model_slug": model_slug,
                "model_name": model_name,
                "source": "quickpic",
                "source_url": "",
                "scraped_at": now,
                "variant_count": len(variants),
                "variants": variants,
            }

            out_file = brand_dir / f"{model_slug}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(raw_entry, f, indent=2, ensure_ascii=False)

            brand_vehicle_count += len(variants)
            brand_model_count += 1

        total_vehicles += brand_vehicle_count
        total_models += brand_model_count
        brand_summaries.append((brand_key, brand_data["qp_name"], brand_model_count, brand_vehicle_count))

    # Clear Nissan raw_data (empty specs, skipping it)
    nissan_dir = RAW_DIR / "nissan"
    if nissan_dir.exists() and "nissan" not in brands_to_process:
        shutil.rmtree(nissan_dir)
        print("  Cleared nissan raw_data (skipped)")

    # Report
    print(f"\n{'='*60}")
    print(f"  QuickPic -> raw_data Conversion")
    print(f"{'='*60}")
    print(f"  Brands: {len(brand_summaries)}")
    print(f"  Models: {total_models}")
    print(f"  Vehicles: {total_vehicles}")
    print(f"{'='*60}")
    for brand_key, qp_name, models, vehicles in sorted(brand_summaries, key=lambda x: x[1]):
        print(f"  {qp_name:25s}  {models:3d} models  {vehicles:3d} variants")
    print(f"{'='*60}\n")

    return total_vehicles


def main():
    parser = argparse.ArgumentParser(description="Convert QuickPic catalogue to raw_data")
    parser.add_argument("--brand", help="Single brand key to process")
    parser.add_argument("--keep-oem", action="store_true",
                        help="Don't clear existing raw_data before writing")
    args = parser.parse_args()

    brands_filter = None
    if args.brand:
        brands_filter = {args.brand.lower()}

    total = convert_catalogue(brands_filter=brands_filter, keep_oem=args.keep_oem)
    if total:
        print(f"Done — {total} vehicles written to raw_data/")
    else:
        print("No vehicles written.")


if __name__ == "__main__":
    main()
