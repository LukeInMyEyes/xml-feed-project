"""
Scrape cars.co.za __NEXT_DATA__ for detailed vehicle specs.
Updates raw_data/{brand}/{model}.json with real spec data.
"""
from __future__ import annotations

import httpx
import json
import re
import sys
import time
from pathlib import Path

RAW_DIR = Path(__file__).parent / "raw_data"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# Maps our model slugs to cars.co.za URL model names
MODEL_URL_MAP = {
    ("baic", "b30"): ("BAIC", "B30"),
    ("baic", "b40-plus"): ("BAIC", "B40-Plus"),
    ("baic", "beijing-x55"): ("BAIC", "Beijing-X55"),
    ("changan", "alsvin"): ("Changan", "Alsvin"),
    ("changan", "cs75-pro"): ("Changan", "CS75-Pro"),
    ("changan", "deepal-s07"): ("Changan", "Deepal-S07"),
    ("changan", "hunter"): ("Changan", "Hunter"),
    ("changan", "uni-s"): ("Changan", "Uni-S"),
    ("citroen", "c3"): ("Citroen", "C3"),
    ("citroen", "c3-aircross"): ("Citroen", "C3-Aircross"),
    ("fiat", "500"): ("Fiat", "500"),
    ("foton", "asambe"): ("Foton", "Asambe"),
    ("foton", "tunland-g7"): ("Foton", "Tunland-G7"),
    ("foton", "tunland-v7"): ("Foton", "Tunland-V7"),
    ("foton", "tunland-v9"): ("Foton", "Tunland-V9"),
    ("foton", "view"): ("Foton", "View"),
    ("jac", "t6"): ("JAC", "T6"),
    ("jac", "t8"): ("JAC", "T8"),
    ("jeep", "gladiator"): ("Jeep", "Gladiator"),
    ("jeep", "wrangler"): ("Jeep", "Wrangler"),
    ("opel", "corsa"): ("Opel", "Corsa"),
    ("opel", "grandland"): ("Opel", "Grandland"),
    ("opel", "mokka"): ("Opel", "Mokka"),
    ("peugeot", "2008"): ("Peugeot", "2008"),
    ("peugeot", "landtrek"): ("Peugeot", "Landtrek"),
}


def fetch_carsza_specs(make: str, model: str) -> list[dict] | None:
    """Fetch variant specs from cars.co.za __NEXT_DATA__."""
    url = f"https://www.cars.co.za/newcars/{make}/{model}/"
    try:
        r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=15)
        if r.status_code != 200:
            return None

        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r.text, re.DOTALL,
        )
        if not match:
            return None

        data = json.loads(match.group(1))
        variants = data.get("props", {}).get("pageProps", {}).get("variants", [])
        if not variants:
            return None

        return variants
    except Exception as e:
        print(f"  ⚠️  Error fetching {make}/{model}: {e}")
        return None


def extract_specs(carsza_variant: dict) -> dict:
    """Extract clean specs dict from cars.co.za variant data."""
    attrs = carsza_variant.get("attributes", {})
    cats = attrs.get("categories", {})

    engine = cats.get("Engine", {})
    summary = cats.get("Summary", {})
    economy = cats.get("Economy", {})
    general = cats.get("General", {})
    dimensions = cats.get("Dimensions", {})
    safety = cats.get("Safety", {})

    specs = {}

    # Engine
    ec = engine.get("Engine Capacity", "")
    if ec:
        specs["engine_capacity"] = ec.strip()

    # Power
    pw = engine.get("Power Maximum Total", "") or engine.get("Power Max", "")
    if pw:
        # Extract just the number: "120 kW" → "120"
        pw_match = re.search(r"(\d+)\s*kW", pw)
        if pw_match:
            specs["power_kw"] = pw_match.group(1)

    # Torque
    tq = engine.get("Torque Max Total", "") or engine.get("Torque Max", "")
    if tq:
        tq_match = re.search(r"(\d+)\s*Nm", tq)
        if tq_match:
            specs["torque_nm"] = tq_match.group(1)

    # Fuel type
    ft = engine.get("Fuel Type", "")
    if ft:
        ft_lower = ft.lower()
        if "diesel" in ft_lower and "hybrid" in ft_lower:
            specs["fuel_type"] = "Diesel Hybrid"
        elif "diesel" in ft_lower:
            specs["fuel_type"] = "Diesel"
        elif "petrol" in ft_lower and "hybrid" in ft_lower:
            specs["fuel_type"] = "Petrol Hybrid"
        elif "petrol" in ft_lower:
            specs["fuel_type"] = "Petrol"
        elif "electric" in ft_lower:
            specs["fuel_type"] = "Electric"
        else:
            specs["fuel_type"] = ft.strip()

    # Transmission
    trans = engine.get("Transmission type", "") or engine.get("Gearshift", "")
    gears = engine.get("Gear ratios quantity", "")
    if trans:
        t = trans.strip().lower()
        if t in ("automatic", "auto"):
            specs["transmission"] = f"{gears}-speed Automatic" if gears else "Automatic"
        elif t in ("manual",):
            specs["transmission"] = f"{gears}-speed Manual" if gears else "Manual"
        elif t == "cvt":
            specs["transmission"] = "CVT"
        else:
            specs["transmission"] = trans.strip()

    # Drivetrain
    driven = engine.get("Driven Wheels", "")
    awd = engine.get("All-wheel-drive", "")
    if awd and awd.lower() not in ("", "n/a"):
        specs["drivetrain"] = "AWD"
    elif driven:
        dw = driven.lower()
        if dw == "rear":
            specs["drivetrain"] = "RWD"
        elif dw == "front":
            specs["drivetrain"] = "FWD"
        elif dw in ("all", "four"):
            specs["drivetrain"] = "4WD"

    # Fuel consumption
    avg = economy.get("Average", "")
    if avg:
        fc_match = re.search(r"([\d.]+)\s*l/100km", avg)
        if fc_match:
            specs["fuel_consumption_l100km"] = fc_match.group(1)

    # CO2
    co2 = economy.get("Co2", "")
    if co2:
        co2_match = re.search(r"(\d+)\s*g/km", co2)
        if co2_match:
            specs["co2_gkm"] = co2_match.group(1)

    # Dimensions
    for dim_key, spec_key in [
        ("Length", "length_mm"), ("Width", "width_mm"),
        ("Height", "height_mm"), ("Wheelbase", "wheelbase_mm"),
        ("Ground clearance (laden)", "ground_clearance_mm"),
        ("Ground clearance", "ground_clearance_mm"),
        ("Kerb Weight", "kerb_weight_kg"),
    ]:
        val = dimensions.get(dim_key, "")
        if val and spec_key not in specs:
            specs[spec_key] = val.strip()

    # Seats
    seats = summary.get("Seats quantity", "")
    if seats:
        specs["seats"] = seats.strip()

    # Safety — airbags
    airbags = safety.get("Airbags quantity", "") or safety.get("Airbags", "")
    if airbags:
        specs["airbags"] = airbags.strip()

    # Warranty from general (if present)
    warranty = general.get("Warranty", "")
    if warranty:
        specs["warranty"] = warranty.strip()

    # Price from general
    price_str = general.get("Price", "")
    if price_str:
        price_match = re.search(r"R\s*([\d\s,]+)", price_str)
        if price_match:
            price_clean = price_match.group(1).replace(" ", "").replace(",", "")
            try:
                specs["_carsza_price"] = int(float(price_clean))
            except ValueError:
                pass

    return specs


def match_variant(carsza_variant: dict, our_variants: list[dict]) -> dict | None:
    """Match a cars.co.za variant to one of our variants by price or name."""
    attrs = carsza_variant.get("attributes", {})
    cats = attrs.get("categories", {})
    cz_price_str = cats.get("General", {}).get("Price", "")
    cz_variant_name = attrs.get("Variant", "") or attrs.get("MM variant", "")

    cz_price = None
    if cz_price_str:
        pm = re.search(r"R\s*([\d\s,]+)", cz_price_str)
        if pm:
            try:
                cz_price = int(float(pm.group(1).replace(" ", "").replace(",", "")))
            except ValueError:
                pass

    # Try to match by price (exact match)
    if cz_price:
        for v in our_variants:
            if v.get("price_incl") == cz_price:
                return v

    # Try to match by name similarity
    if cz_variant_name:
        cz_words = set(cz_variant_name.upper().split())
        best_match = None
        best_score = 0
        for v in our_variants:
            our_words = set(v.get("variant_name", "").upper().split())
            overlap = len(cz_words & our_words)
            if overlap > best_score:
                best_score = overlap
                best_match = v
        if best_match and best_score >= 1:
            return best_match

    return None


def scrape_and_update(brands_filter: list[str] = None):
    """Scrape cars.co.za and merge specs into raw_data."""
    total_updated = 0
    total_specs = 0

    for (brand, model_slug), (make, model_url) in sorted(MODEL_URL_MAP.items()):
        if brands_filter and brand not in brands_filter:
            continue

        # Load our data
        json_path = RAW_DIR / brand / f"{model_slug}.json"
        if not json_path.exists():
            print(f"  ⚠️  {brand}/{model_slug} — no spec file")
            continue

        with open(json_path) as f:
            our_data = json.load(f)

        our_variants = our_data.get("variants", [])

        # Fetch from cars.co.za
        print(f"  🔍 {brand}/{model_slug} — fetching from cars.co.za...", end=" ", flush=True)
        cz_variants = fetch_carsza_specs(make, model_url)

        if not cz_variants:
            print("no data")
            time.sleep(1)
            continue

        print(f"got {len(cz_variants)} variants")

        model_updated = False
        for cz_var in cz_variants:
            cz_specs = extract_specs(cz_var)
            matched = match_variant(cz_var, our_variants)

            if matched:
                existing = matched.get("specs", {})
                new_fields = 0

                # Merge — cars.co.za data fills gaps, doesn't override
                # EXCEPT for key fields where cars.co.za is more accurate
                CARSZA_WINS = {"power_kw", "torque_nm", "fuel_consumption_l100km",
                               "co2_gkm", "seats", "airbags"}

                for k, v in cz_specs.items():
                    if k.startswith("_"):
                        continue
                    old_val = existing.get(k, "")
                    if not old_val or (k in CARSZA_WINS and v):
                        if v and str(v).strip():
                            existing[k] = v
                            new_fields += 1

                if new_fields > 0:
                    matched["specs"] = existing
                    model_updated = True
                    total_specs += new_fields

                cz_name = cz_var.get("attributes", {}).get("Variant", "?")
                our_name = matched.get("variant_name", "?")
                if new_fields > 0:
                    print(f"    ✅ matched: \"{our_name}\" ← +{new_fields} fields")

        if model_updated:
            total_updated += 1
            # Update source URL
            our_data["source_url"] = f"https://www.cars.co.za/newcars/{make}/{model_url}/"

            with open(json_path, "w") as f:
                json.dump(our_data, f, indent=2, ensure_ascii=False)
                f.write("\n")

        time.sleep(1)  # Be polite to cars.co.za

    print(f"\n{'='*50}")
    print(f"  Updated {total_updated} model files")
    print(f"  Added {total_specs} spec fields from cars.co.za")
    print(f"{'='*50}")


if __name__ == "__main__":
    brands = None
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        brands = [b.lower() for b in args]
    scrape_and_update(brands)
