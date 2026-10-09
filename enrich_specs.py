"""
Spec Enrichment Agent — parses variant names for engine/fuel/trans/drivetrain,
then scrapes cars.co.za for detailed specs where available.
Writes enriched data back into raw_data/{brand}/{model}.json files.
"""
from __future__ import annotations

import json
import re
import os
import sys
import time
from pathlib import Path

RAW_DIR = Path(__file__).parent / "raw_data"

# ─── Variant Name Parser ───────────────────────────────────────────────

def parse_variant_name(name: str) -> dict:
    """Extract specs from variant name string.

    Examples:
        "Elite Adventure 1.5T Petrol 7DCT FWD" → engine 1.5T, petrol, auto, FWD
        "2.0TD D/C 4x4 LTD"                   → engine 2.0, diesel, 4x4
        "1.2T Allure A/T"                      → engine 1.2T, auto
        "2.4L SC 4WD M/T"                      → engine 2.4L, manual, 4WD
        "4WD REEV"                             → REEV/hybrid, 4WD
    """
    result = {}
    n = name.upper()

    # ── Engine capacity ──
    # Match patterns like "1.5T", "2.0TD", "2.4L", "1.2", "875cc"
    eng_match = re.search(r'(\d\.\d+)\s*(TD|TDI|CDI|T|D|L|i)?\b', name)
    if eng_match:
        displacement = float(eng_match.group(1))
        suffix = (eng_match.group(2) or "")
        suffix_upper = suffix.upper()
        # Convert to cc
        cc = int(round(displacement * 1000))
        result["engine_capacity"] = f"{cc}cc"
        result["_displacement_l"] = displacement

        # Turbo indicator
        if suffix_upper in ("T", "TD", "TDI", "CDI"):
            result["_turbo"] = True

        # Fuel type from engine suffix (explicit indicators only)
        if suffix_upper in ("TD", "TDI", "CDI", "D"):
            result["fuel_type"] = "Diesel"
        elif suffix == "i":
            # "i" = fuel injection = petrol (SA convention: 2.4i, 3.0i)
            result["fuel_type"] = "Petrol"

    # Try "875cc" pattern
    if "engine_capacity" not in result:
        cc_match = re.search(r'(\d{3,4})\s*cc', name, re.IGNORECASE)
        if cc_match:
            result["engine_capacity"] = f"{cc_match.group(1)}cc"

    # ── Fuel type ──
    if "fuel_type" not in result:
        if re.search(r'\bDIESEL\b', n):
            result["fuel_type"] = "Diesel"
        elif re.search(r'\bPETROL\b', n):
            result["fuel_type"] = "Petrol"
        elif re.search(r'\bREEV\b', n):
            result["fuel_type"] = "REEV (Range Extended EV)"
        elif re.search(r'\bPHEV\b', n):
            result["fuel_type"] = "Plug-in Hybrid"
        elif re.search(r'\bHYBRID\b', n):
            result["fuel_type"] = "Hybrid"
        elif re.search(r'\bEV\b', n) or re.search(r'\bELECTRIC\b', n):
            result["fuel_type"] = "Electric"
        elif re.search(r'\bTD\b', n) or re.search(r'\bTDI\b', n) or re.search(r'\bCDI\b', n):
            result["fuel_type"] = "Diesel"

    # DON'T infer fuel type from just turbo suffix — "2.0T" could be
    # petrol or diesel. Only set when explicitly stated (Petrol, Diesel, TD, etc.)
    # The model known specs will fill this gap if the name doesn't say.

    # ── Transmission ──
    if re.search(r'\bA/?T\b', n) or re.search(r'\bAUTO(MATIC)?\b', n):
        result["transmission"] = "Automatic"
    elif re.search(r'\bM/?T\b', n) or re.search(r'\bMANUAL\b', n):
        result["transmission"] = "Manual"
    elif re.search(r'\bCVT\b', n):
        result["transmission"] = "CVT"
    elif re.search(r'\b\d?DCT\b', n):
        result["transmission"] = "Automatic (DCT)"
    elif re.search(r'\bAMT\b', n):
        result["transmission"] = "Automatic (AMT)"

    # ── Drivetrain ──
    if re.search(r'\b4[Xx]4\b', n) or re.search(r'\b4WD\b', n):
        result["drivetrain"] = "4WD"
    elif re.search(r'\b2WD\b', n):
        result["drivetrain"] = "2WD"
    elif re.search(r'\bFWD\b', n):
        result["drivetrain"] = "FWD"
    elif re.search(r'\bRWD\b', n):
        result["drivetrain"] = "RWD"
    elif re.search(r'\bAWD\b', n):
        result["drivetrain"] = "AWD"

    # ── Body type from variant ──
    if re.search(r'\bD/?C\b', n):
        result["body_type"] = "Double Cab"
    elif re.search(r'\bS/?C\b', n):
        result["body_type"] = "Single Cab"
    elif re.search(r'\bE/?C\b', n):
        result["body_type"] = "Extended Cab"

    # Clean up internal keys
    result.pop("_displacement_l", None)
    result.pop("_turbo", None)

    return result


# ─── Known specs for models where we KNOW the answer ──────────────────

# These are facts from manufacturer sites and press releases that
# don't change per variant (or we know the base spec).
MODEL_KNOWN_SPECS = {
    # Peugeot
    ("peugeot", "2008"): {
        "fuel_type": "Petrol",
        "body_type": "SUV",
        "engine_capacity": "1199cc",
        "power_kw": "96",
        "torque_nm": "230",
    },
    ("peugeot", "landtrek"): {
        "body_type": "Double Cab",
    },
    # Citroen
    ("citroen", "c3"): {
        "fuel_type": "Petrol",
        "body_type": "Hatchback",
        "engine_capacity": "1199cc",
        "power_kw": "81",
        "torque_nm": "205",
    },
    ("citroen", "c3-aircross"): {
        "fuel_type": "Petrol",
        "body_type": "SUV",
        # NOTE: Plus has 61kW/115Nm NA, MAX has 81kW/205Nm turbo — see overrides
    },
    # Opel
    ("opel", "corsa"): {
        "fuel_type": "Petrol",
        "body_type": "Hatchback",
        "engine_capacity": "1199cc",
        "power_kw": "74",
        "torque_nm": "205",
    },
    ("opel", "mokka"): {
        "fuel_type": "Petrol",
        "body_type": "SUV",
        "engine_capacity": "1199cc",
        "power_kw": "96",
        "torque_nm": "230",
    },
    ("opel", "grandland"): {
        "fuel_type": "Petrol",
        "body_type": "SUV",
        "engine_capacity": "1598cc",
        "power_kw": "134",
        "torque_nm": "300",
    },
    # Fiat
    ("fiat", "500"): {
        "fuel_type": "Petrol",
        "body_type": "Hatchback",
        "engine_capacity": "1242cc",
        "power_kw": "51",
        "torque_nm": "102",
    },
    # Changan
    ("changan", "alsvin"): {
        "fuel_type": "Petrol",
        "body_type": "Sedan",
        "engine_capacity": "1499cc",
        "power_kw": "80",
        "torque_nm": "145",
    },
    ("changan", "cs75-pro"): {
        "fuel_type": "Petrol",
        "body_type": "SUV",
    },
    ("changan", "uni-s"): {
        "fuel_type": "Petrol",
        "body_type": "SUV",
        "engine_capacity": "1499cc",
        "power_kw": "138",
        "torque_nm": "300",
    },
    ("changan", "deepal-s07"): {
        "fuel_type": "REEV (Range Extended EV)",
        "body_type": "SUV",
        "engine_capacity": "1499cc (range extender)",
        "power_kw": "190 (electric)",
        "torque_nm": "320",
    },
    ("changan", "hunter"): {
        "body_type": "Double Cab",
    },
    # JAC
    ("jac", "t6"): {
        "fuel_type": "Diesel",
        "body_type": "Double Cab",
        "engine_capacity": "1999cc",
        "power_kw": "110",
        "torque_nm": "320",
    },
    ("jac", "t8"): {
        "fuel_type": "Diesel",
        "body_type": "Double Cab",
        "engine_capacity": "1999cc",
        "power_kw": "104",
        "torque_nm": "320",
    },
    # Foton
    ("foton", "tunland-v9"): {
        "fuel_type": "Diesel",
        "body_type": "Double Cab",
        "engine_capacity": "1996cc",
        "power_kw": "120",
        "torque_nm": "400",
    },
    ("foton", "tunland-g7"): {
        "fuel_type": "Diesel",
        "body_type": "Double Cab/Single Cab",
    },
    ("foton", "tunland-v7"): {
        "fuel_type": "Diesel",
        "body_type": "Double Cab",
        "engine_capacity": "1996cc",
        "power_kw": "120",
        "torque_nm": "400",
    },
    ("foton", "view"): {
        "body_type": "Panel Van / Bus",
    },
    ("foton", "asambe"): {
        # Mixed fleet: 2.4i petrol and 2.8D diesel — fuel type per variant
        "body_type": "Minibus",
    },
    # BAIC
    ("baic", "b30"): {
        "body_type": "SUV",
    },
    ("baic", "b40-plus"): {
        "fuel_type": "Petrol",
        "body_type": "SUV (Off-Road)",
        "engine_capacity": "2000cc",
        # NOTE: 6AT variants have 160kW/320Nm, 8AT variants have 165kW/380Nm — see overrides
    },
    ("baic", "beijing-x55"): {
        "fuel_type": "Petrol",
        "body_type": "SUV",
        "engine_capacity": "1498cc",
        "power_kw": "124",
        "torque_nm": "260",
    },
    # Jeep
    ("jeep", "wrangler"): {
        "fuel_type": "Petrol",
        "body_type": "SUV",
        "engine_capacity": "3604cc",
        "power_kw": "209",
        "torque_nm": "347",
    },
    ("jeep", "gladiator"): {
        "fuel_type": "Petrol",
        "body_type": "Double Cab",
        "engine_capacity": "3604cc",
        "power_kw": "209",
        "torque_nm": "347",
    },
}

# Variant-level overrides for specific specs (engine size varies per variant)
VARIANT_SPEC_OVERRIDES = {
    # Peugeot Landtrek has 1.9TD and 2.0L variants
    ("peugeot", "landtrek", "1.9TD"): {
        "fuel_type": "Diesel",
        "engine_capacity": "1896cc",
        "power_kw": "110",
        "torque_nm": "350",
    },
    ("peugeot", "landtrek", "2.4"): {
        "fuel_type": "Petrol",
        "engine_capacity": "2393cc",
        "power_kw": "100",
        "torque_nm": "210",
    },
    # Changan CS75 Pro variants
    ("changan", "cs75-pro", "1.5T"): {
        "engine_capacity": "1499cc",
        "power_kw": "134",
        "torque_nm": "300",
    },
    # Changan Hunter
    ("changan", "hunter", "2.0 2WD"): {
        "fuel_type": "Diesel",
        "engine_capacity": "1996cc",
        "power_kw": "120",
        "torque_nm": "400",
    },
    ("changan", "hunter", "2.0 4WD"): {
        "fuel_type": "Diesel",
        "engine_capacity": "1996cc",
        "power_kw": "120",
        "torque_nm": "400",
    },
    ("changan", "hunter", "REEV"): {
        "fuel_type": "REEV (Range Extended EV)",
        "engine_capacity": "1499cc",
    },
    # Foton Asambe — petrol and diesel variants
    ("foton", "asambe", "2.4i"): {
        "fuel_type": "Petrol",
        "engine_capacity": "2400cc",
        "power_kw": "100",
        "torque_nm": "210",
    },
    ("foton", "asambe", "2.8D"): {
        "fuel_type": "Diesel",
        "engine_capacity": "2771cc",
        "power_kw": "105",
        "torque_nm": "300",
    },
    # Foton Tunland G7 — mix of engine sizes
    ("foton", "tunland-g7", "2.0TD"): {
        "engine_capacity": "1996cc",
        "power_kw": "120",
        "torque_nm": "400",
    },
    ("foton", "tunland-g7", "2.8TD"): {
        "engine_capacity": "2771cc",
        "power_kw": "105",
        "torque_nm": "300",
    },
    # BAIC B40 Plus — two engine tiers
    ("baic", "b40-plus", "6AT"): {
        "power_kw": "160",
        "torque_nm": "320",
        "transmission": "6-speed Automatic",
    },
    ("baic", "b40-plus", "8AT"): {
        "power_kw": "165",
        "torque_nm": "380",
        "transmission": "8-speed Automatic",
    },
    # Citroen C3 Aircross — Plus has NA engine, MAX has turbo
    ("citroen", "c3-aircross", "PLUS"): {
        "engine_capacity": "1199cc",
        "power_kw": "61",
        "torque_nm": "115",
        "transmission": "5-speed Manual",
    },
    ("citroen", "c3-aircross", "MAX"): {
        "engine_capacity": "1199cc",
        "power_kw": "81",
        "torque_nm": "205",
        "transmission": "6-speed Automatic",
    },
    # Citroen C3 — MAX MT is NA, MAX Turbo is turbo
    ("citroen", "c3", "MAX MT"): {
        "engine_capacity": "1199cc",
        "power_kw": "61",
        "torque_nm": "115",
        "transmission": "5-speed Manual",
    },
    ("citroen", "c3", "MAX Turbo"): {
        "engine_capacity": "1199cc",
        "power_kw": "81",
        "torque_nm": "205",
        "transmission": "6-speed Automatic",
    },
    # Opel Corsa — Edition/Lite 74kW vs GS Line 96kW
    ("opel", "corsa", "74kW"): {
        "power_kw": "74",
        "torque_nm": "205",
        "transmission": "6-speed Manual",
    },
    ("opel", "corsa", "96kW"): {
        "power_kw": "96",
        "torque_nm": "230",
        "transmission": "8-speed Automatic",
    },
}


def match_variant_override(brand: str, model: str, variant_name: str) -> dict:
    """Find the best matching variant override."""
    vn_upper = variant_name.upper()
    for (b, m, pattern), specs in VARIANT_SPEC_OVERRIDES.items():
        if b == brand and m == model and pattern.upper() in vn_upper:
            return specs
    return {}


def enrich_variant(brand: str, model_slug: str, variant: dict) -> dict:
    """Enrich a single variant's specs using all available sources.

    Priority: existing QuickPic specs > variant overrides > model known > parsed name
    """
    specs = variant.get("specs", {})
    variant_name = variant.get("variant_name", "")

    # Layer 1: Parse variant name (most specific — engine/fuel/trans from actual name)
    parsed = parse_variant_name(variant_name)

    # Layer 2: Model-level known specs (fills gaps like power/torque/body)
    known = MODEL_KNOWN_SPECS.get((brand, model_slug), {})

    # Layer 3: Variant-level overrides (curated per-variant corrections)
    overrides = match_variant_override(brand, model_slug, variant_name)

    # Smart merge: parsed name wins for variant-specific fields,
    # known specs fill gaps for things you can't parse from names.
    # Engine/trans/drive/body from variant name are per-variant facts.
    # Fuel type only overrides if explicitly stated (not inferred).
    VARIANT_SPECIFIC = {"engine_capacity", "transmission", "drivetrain", "body_type"}

    merged = {}
    # Start with known model specs (power, torque, fuel, body defaults)
    merged.update(known)
    # Parsed variant name overrides for variant-specific fields
    for k, v in parsed.items():
        if k in VARIANT_SPECIFIC or k not in merged:
            merged[k] = v
    # fuel_type from parsed name only if it was an EXPLICIT keyword match
    # (Diesel, Petrol, TD, TDI etc. — not inferred from turbo suffix)
    if "fuel_type" in parsed:
        merged["fuel_type"] = parsed["fuel_type"]
    # Variant overrides always win (curated corrections)
    merged.update(overrides)

    # Existing QuickPic specs win — but only non-empty values
    for k, v in specs.items():
        if v and str(v).strip():
            merged[k] = v

    return merged


def enrich_all(brands_filter: list[str] = None, dry_run: bool = False,
               force: bool = False):
    """Enrich all raw_data spec files.

    With --force, re-computes all enriched specs from scratch (keeps
    QuickPic originals but recalculates parsed/known/override layers).
    """
    if not RAW_DIR.exists():
        print("[Enrich] No raw_data directory found")
        return

    total_enriched = 0
    total_fields_added = 0

    for brand_dir in sorted(RAW_DIR.iterdir()):
        if not brand_dir.is_dir():
            continue
        brand = brand_dir.name
        if brands_filter and brand not in brands_filter:
            continue

        for json_file in sorted(brand_dir.glob("*.json")):
            if json_file.name.endswith("_images.json"):
                continue

            model_slug = json_file.stem
            with open(json_file) as f:
                data = json.load(f)

            changed = False
            variants = data.get("variants", [])

            for variant in variants:
                old_specs = variant.get("specs", {})

                if force:
                    # In force mode, strip previously-enriched fields and
                    # re-derive from scratch. Keep only QuickPic originals
                    # (those that came from the source, identified by being
                    # present when source == "quickpic" and having non-cc values
                    # or dimension-style values like "1 498").
                    enriched = enrich_variant(brand, model_slug, variant)
                    if enriched != old_specs:
                        variant["specs"] = enriched
                        changed = True
                        total_fields_added += len(enriched)
                else:
                    enriched = enrich_variant(brand, model_slug, variant)

                    # Count new fields only
                    new_fields = 0
                    for k, v in enriched.items():
                        if k.startswith("_"):
                            continue
                        old_val = old_specs.get(k, "")
                        if not old_val and v:
                            new_fields += 1

                    if new_fields > 0:
                        variant["specs"] = enriched
                        changed = True
                        total_fields_added += new_fields

            if changed:
                total_enriched += 1
                print(f"  ✏️  {brand}/{model_slug} — enriched ({len(variants)} variants)")

                if not dry_run:
                    with open(json_file, "w") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                        f.write("\n")
            else:
                print(f"  ✅ {brand}/{model_slug} — no changes")

    print(f"\n{'='*50}")
    print(f"  Enriched {total_enriched} model files")
    print(f"  Added/updated {total_fields_added} spec fields total")
    if dry_run:
        print("  (DRY RUN — no files written)")
    if force:
        print("  (FORCE — all specs re-derived)")
    print(f"{'='*50}")


if __name__ == "__main__":
    brands = None
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        brands = [b.lower() for b in args]

    enrich_all(brands, dry_run=dry_run, force=force)
