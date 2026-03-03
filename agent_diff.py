"""
Diff Agent — compares current feed vs previous feed.
Flags: NEW VEHICLE, PRICE CHANGE, DISCONTINUED, SPEC CHANGE.
Outputs changes XML.
"""

import sys
import time
import re
from pathlib import Path
from xml.etree.ElementTree import parse, Element, SubElement, tostring, indent

OUTPUT_DIR = Path(__file__).parent / "output"
PREV_DIR = Path(__file__).parent / "previous_feeds"

PRICE_CHANGE_THRESHOLD = 100  # Ignore price changes smaller than R100


def load_feed(xml_path: str) -> dict:
    """Parse XML feed into a dict keyed by Brand+Model+Variant."""
    vehicles = {}
    try:
        tree = parse(xml_path)
        root = tree.getroot()

        for brand_el in root.findall("Brand"):
            brand_name = brand_el.get("name", "")

            for vehicle_el in brand_el.findall("Vehicle"):
                model = vehicle_el.findtext("Model", "")
                variant = vehicle_el.findtext("Variant", "")
                key = f"{brand_name}|{model}|{variant}"

                price_text = vehicle_el.findtext("PriceIncl", "")
                price = int(price_text) if price_text and price_text.isdigit() else None

                specs = {}
                specs_el = vehicle_el.find("Specifications")
                if specs_el is not None:
                    for spec in specs_el:
                        if spec.text:
                            specs[spec.tag] = spec.text

                vehicles[key] = {
                    "brand": brand_name,
                    "model": model,
                    "variant": variant,
                    "price_incl": price,
                    "specs": specs,
                }
    except Exception as e:
        print(f"  Error parsing {xml_path}: {e}")

    return vehicles


def diff_feeds(current_path: str, previous_path: str) -> list[dict]:
    """Compare current vs previous feed, return list of changes."""
    current = load_feed(current_path)
    previous = load_feed(previous_path)

    changes = []

    # New vehicles
    for key in current:
        if key not in previous:
            v = current[key]
            changes.append({
                "type": "NEW VEHICLE",
                "brand": v["brand"],
                "model": v["model"],
                "variant": v["variant"],
                "price_incl": v["price_incl"],
                "details": "",
            })

    # Discontinued vehicles
    for key in previous:
        if key not in current:
            v = previous[key]
            changes.append({
                "type": "DISCONTINUED",
                "brand": v["brand"],
                "model": v["model"],
                "variant": v["variant"],
                "price_incl": v["price_incl"],
                "details": "",
            })

    # Price and spec changes
    for key in current:
        if key in previous:
            curr = current[key]
            prev = previous[key]

            # Price change
            if curr["price_incl"] and prev["price_incl"]:
                diff = curr["price_incl"] - prev["price_incl"]
                if abs(diff) >= PRICE_CHANGE_THRESHOLD:
                    direction = "UP" if diff > 0 else "DOWN"
                    changes.append({
                        "type": "PRICE CHANGE",
                        "brand": curr["brand"],
                        "model": curr["model"],
                        "variant": curr["variant"],
                        "price_incl": curr["price_incl"],
                        "details": f"{direction} R{abs(diff):,} (was R{prev['price_incl']:,})",
                    })

            # Spec changes
            curr_specs = curr.get("specs", {})
            prev_specs = prev.get("specs", {})
            changed_specs = []

            for spec_key in set(list(curr_specs.keys()) + list(prev_specs.keys())):
                curr_val = curr_specs.get(spec_key, "")
                prev_val = prev_specs.get(spec_key, "")
                if curr_val != prev_val and (curr_val or prev_val):
                    changed_specs.append(f"{spec_key}: {prev_val} -> {curr_val}")

            if changed_specs:
                changes.append({
                    "type": "SPEC CHANGE",
                    "brand": curr["brand"],
                    "model": curr["model"],
                    "variant": curr["variant"],
                    "price_incl": curr["price_incl"],
                    "details": "; ".join(changed_specs[:10]),
                })

    return changes


def build_changes_xml(changes: list[dict]) -> str:
    """Build XML output of changes."""
    root = Element("FeedChanges")
    root.set("generated", time.strftime("%Y-%m-%dT%H:%M:%S"))
    root.set("totalChanges", str(len(changes)))

    # Group by type
    type_counts = {}
    for c in changes:
        type_counts[c["type"]] = type_counts.get(c["type"], 0) + 1

    summary = SubElement(root, "Summary")
    for change_type, count in sorted(type_counts.items()):
        el = SubElement(summary, "ChangeType")
        el.set("type", change_type)
        el.set("count", str(count))

    changes_el = SubElement(root, "Changes")
    for c in sorted(changes, key=lambda x: (x["type"], x["brand"], x["model"])):
        change_el = SubElement(changes_el, "Change")
        change_el.set("type", c["type"])
        SubElement(change_el, "Brand").text = c["brand"]
        SubElement(change_el, "Model").text = c["model"]
        SubElement(change_el, "Variant").text = c["variant"]
        if c["price_incl"]:
            SubElement(change_el, "PriceIncl").text = str(c["price_incl"])
        if c["details"]:
            SubElement(change_el, "Details").text = c["details"]

    indent(root, space="  ")
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += tostring(root, encoding="unicode", xml_declaration=False)
    xml_str = re.sub(r'<(\w+)>\s*</\1>', r'<\1/>', xml_str)
    return xml_str


def run_diff(current_path: str = None, previous_path: str = None) -> str:
    """Run diff between current and previous feed."""
    if not current_path:
        current_path = str(OUTPUT_DIR / "sa_car_feed_latest.xml")

    if not previous_path:
        # Find most recent previous feed
        prev_files = sorted(PREV_DIR.glob("sa_car_feed_*.xml"))
        if not prev_files:
            print("[Diff] No previous feed found in previous_feeds/")
            return ""
        previous_path = str(prev_files[-1])

    if not Path(current_path).exists():
        print(f"[Diff] Current feed not found: {current_path}")
        return ""
    if not Path(previous_path).exists():
        print(f"[Diff] Previous feed not found: {previous_path}")
        return ""

    print(f"[Diff] Comparing:")
    print(f"  Current:  {current_path}")
    print(f"  Previous: {previous_path}")

    changes = diff_feeds(current_path, previous_path)

    if not changes:
        print("  No changes detected.")
        return ""

    xml = build_changes_xml(changes)

    # Save
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_file = OUTPUT_DIR / f"feed_changes_{timestamp}.xml"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(xml)

    # Print summary
    type_counts = {}
    for c in changes:
        type_counts[c["type"]] = type_counts.get(c["type"], 0) + 1

    print(f"\n  Changes detected: {len(changes)}")
    for t, count in sorted(type_counts.items()):
        print(f"    {t:20s} {count}")
    print(f"  Saved to: {out_file}")

    return str(out_file)


if __name__ == "__main__":
    current = sys.argv[1] if len(sys.argv) > 1 else None
    previous = sys.argv[2] if len(sys.argv) > 2 else None

    result = run_diff(current, previous)
    if not result:
        print("No diff output generated.")
