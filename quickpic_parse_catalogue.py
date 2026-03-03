"""
Parse the complete QuickPic AutoSpec catalogue from the raw_audi.txt dump.
Uses known brand names to correctly split the tree.
"""
import re
import json
import os

RAW_FILE = os.path.join(os.path.dirname(__file__), "quickpic_screenshots", "raw_audi.txt")
OUT_FILE = os.path.join(os.path.dirname(__file__), "quickpic_catalogue.json")

# All QuickPic brand names (from the compare dialog)
QP_BRANDS = [
    "Alfa Romeo", "Aston Martin", "Audi", "BAIC", "Bentley", "BMW", "BYD",
    "Changan", "Chery", "Citroen", "DFSK", "Ferrari", "Fiat", "Ford",
    "Foton", "GAC", "Geely", "GWM", "Haval", "Honda", "Hyundai", "Ineos",
    "Isuzu", "JAC", "Jaecoo", "Jaguar", "Jeep", "Jetour", "Kia",
    "Lamborghini", "Land Rover", "LDV", "Leapmotor", "Lexus", "Mahindra",
    "Maserati", "Mazda", "McLaren", "Mercedes-AMG", "Mercedes-Benz",
    "Mercedes-Maybach", "MG", "MINI", "Mitsubishi", "Nissan", "Omoda",
    "Opel", "Peugeot", "Porsche", "Proton", "Renault", "Rolls-Royce",
    "Subaru", "Suzuki", "TATA", "Toyota", "Volkswagen", "Volvo",
]

# Map to our feed keys
BRAND_MAP = {
    "vw": "Volkswagen", "toyota": "Toyota", "ford": "Ford",
    "hyundai": "Hyundai", "kia": "Kia", "bmw": "BMW",
    "mercedes": "Mercedes-Benz", "nissan": "Nissan", "suzuki": "Suzuki",
    "mazda": "Mazda", "haval": "Haval", "chery": "Chery",
    "renault": "Renault", "isuzu": "Isuzu", "subaru": "Subaru",
    "mitsubishi": "Mitsubishi", "volvo": "Volvo", "audi": "Audi",
    "mg": "MG", "gwm": "GWM", "baic": "BAIC", "honda": "Honda",
    "jeep": "Jeep",
}
QP_TO_KEY = {v: k for k, v in BRAND_MAP.items()}

# Build regex set for brand detection
BRAND_SET = set(QP_BRANDS)


def is_brand_line(line):
    """Check if a line matches 'BrandName (N)' for a known brand."""
    m = re.match(r'^(.+?)\s*\((\d+)\)$', line)
    if m:
        name = m.group(1).strip()
        return name in BRAND_SET, name, int(m.group(2))
    return False, "", 0


def parse():
    with open(RAW_FILE, "r", encoding="utf-8") as f:
        raw = f.read()

    # Find start of brand tree
    start_marker = "Compare Vehicles (Max 4)"
    start_idx = raw.find(start_marker)
    if start_idx < 0:
        print("ERROR: No start marker")
        return
    tree_text = raw[start_idx + len(start_marker):]
    lines = tree_text.strip().split("\n")

    # Parse
    catalogue = {}
    current_brand = None
    current_model = None

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line or line == "\t":
            i += 1
            continue

        if line in ("Reset Filters", "Show"):
            i += 1
            continue

        # Check if this is a brand line
        is_brand, brand_name, brand_count = is_brand_line(line)

        if is_brand:
            current_brand = brand_name
            current_model = None
            catalogue[current_brand] = {"count": brand_count, "models": {}}
            i += 1
            continue

        # Check if this is a model line (Name (N) but NOT a known brand)
        m = re.match(r'^(.+?)\s*\((\d+)\)$', line)
        if m and current_brand:
            model_name = m.group(1).strip()
            model_count = int(m.group(2))
            current_model = model_name
            catalogue[current_brand]["models"][current_model] = {
                "count": model_count,
                "variants": []
            }
            i += 1
            continue

        # Date line
        if re.match(r'^\(\d{2}\s+\w+\s+\d{4}\)$', line):
            i += 1
            continue

        # Price line
        if re.match(r'^R\s+[\d\s]+$', line) or line == "POA/TBA":
            i += 1
            continue

        # Must be a variant line
        if current_model and current_brand:
            variant_name = line
            date_str = ""
            price_str = ""

            # Peek for date
            if i + 1 < len(lines):
                next_l = lines[i + 1].strip()
                date_m = re.match(r'^\((\d{2}\s+\w+\s+\d{4})\)$', next_l)
                if date_m:
                    date_str = date_m.group(1)
                    i += 1
                    # Peek for price
                    if i + 1 < len(lines):
                        price_l = lines[i + 1].strip()
                        price_m = re.match(r'^R\s+([\d\s]+)$', price_l)
                        if price_m:
                            price_str = price_m.group(1).replace(" ", "")
                            i += 1
                        elif price_l == "POA/TBA":
                            price_str = "POA"
                            i += 1

            catalogue[current_brand]["models"][current_model]["variants"].append({
                "name": variant_name,
                "date": date_str,
                "price": price_str,
            })

        i += 1

    # Convert to output format
    result = {}
    for brand_name, brand_data in catalogue.items():
        key = QP_TO_KEY.get(brand_name, f"_extra_{brand_name.lower().replace(' ', '_').replace('-', '_')}")
        models = brand_data["models"]
        total_v = sum(len(m["variants"]) for m in models.values())

        result[key] = {
            "qp_name": brand_name,
            "qp_count": brand_data["count"],
            "models": models,
            "total_variants": total_v,
        }

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Summary
    print("=" * 60)
    print("  QuickPic AutoSpec Catalogue")
    print("=" * 60)
    grand_total = 0
    our_total = 0
    for key in sorted(result.keys()):
        data = result[key]
        tv = data["total_variants"]
        nm = len(data["models"])
        grand_total += tv
        is_ours = key in BRAND_MAP
        if is_ours:
            our_total += tv
        marker = " *" if is_ours else ""
        print(f"  {data['qp_name']:25s} {nm:3d} models  {tv:4d} variants{marker}")

    print(f"\n  Grand total: {grand_total} variants across {len(result)} brands")
    print(f"  Our 23 brands: {our_total} variants")
    print(f"  Saved: {OUT_FILE}")


if __name__ == "__main__":
    parse()
