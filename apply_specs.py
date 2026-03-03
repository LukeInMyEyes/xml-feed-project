"""Apply scraped Suzuki SA specs to raw_data JSON files."""
import json
from pathlib import Path

RAW_DIR = Path(__file__).parent / "raw_data" / "suzuki"

# Key mapping: scraped key -> compiler-expected key
KEY_MAP = {
    "fuel_consumption": "fuel_consumption_l100km",
    "co2_emissions": "co2_emissions_gkm",
    "top_speed_kph": "top_speed_kmh",
}

# Load scraped specs
with open(RAW_DIR / "suzuki_scraped_specs.json", encoding="utf-8") as f:
    scraped = json.load(f)

models_to_update = ["grand-vitara", "swift", "swift-sport", "super-carry", "s-presso"]
total_updated = 0

for slug in models_to_update:
    if slug not in scraped:
        print(f"  SKIP {slug} (not in scraped data)")
        continue

    model_file = RAW_DIR / f"{slug}.json"
    if not model_file.exists():
        print(f"  SKIP {slug} (file not found)")
        continue

    with open(model_file, encoding="utf-8") as f:
        data = json.load(f)

    spec_data = scraped[slug]
    updated = 0

    for variant in data["variants"]:
        vname = variant["variant_name"]
        if vname in spec_data:
            # Remap keys to match compiler expectations
            new_specs = {}
            for k, v in spec_data[vname].items():
                mapped_key = KEY_MAP.get(k, k)
                new_specs[mapped_key] = v
            variant["specs"] = new_specs
            updated += 1
            print(f"  {slug}: {vname} -> {len(new_specs)} specs applied")

    if updated:
        with open(model_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        total_updated += updated

print(f"\nDone: {total_updated} variants updated across {len(models_to_update)} models.")
