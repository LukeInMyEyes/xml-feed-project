"""
Compiler Agent — reads all raw_data/ JSON files, merges specs + images,
calculates excl price, validates, and outputs:
  1. Per-brand JSON files  (output/brands/{brand}.json)
  2. Combined JSON feed    (output/sa_car_feed_latest.json)
  3. Legacy XML feed       (output/sa_car_feed_latest.xml)  — kept for backward compat
"""
from __future__ import annotations

import json
import os
import sys
import time
import re
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring, indent

RAW_DIR = Path(__file__).parent / "raw_data"
OUTPUT_DIR = Path(__file__).parent / "output"
DEALERS_FILE = Path(__file__).parent / "dealers.json"
VAT_RATE = 1.15


# A catalogue may shrink a little between runs: a manufacturer really does
# discontinue things. One derivative in ten is a plausible pruning. More than
# that, in a single automated run, has so far always been a broken scrape.
#
# Deliberately strict, because the two outcomes are not symmetric. A false
# refusal costs somebody a look at the log and one environment variable. A
# false pass puts missing vehicles and wrong prices on a live dealer site,
# where the first person to notice is a customer. BAIC slipped through at a
# third and silently lost three of the four B30 derivatives.
MAX_MODEL_LOSS = 0.10

MANGLED_NAME = re.compile(r'_co_za|_com_|^(www|http|https)_|_(co|org|net)_', re.I)


OVERRIDES_DIR = Path(__file__).parent / "overrides"


def load_overrides(brand_key: str) -> dict:
    """Verified corrections that must survive a recompile.

    Scraped data is not always the best data we have. Changan publishes no cash
    prices on its own site at all, so the only figures in raw_data come from a
    May catalogue scrape, while the prices actually on the dealer sites have
    since been corrected by hand against price lists and the manufacturer.
    Before this existed those corrections lived nowhere but the compiled output,
    so the next compile silently reverted them: recompiling Changan pulled the
    Alsvin back from R249 900 to a five month old R238 000.

    An override is a human saying "I checked this, and it beats the scrape".
    Each one carries a note and a date so the next person knows what was
    checked and when it is worth re-checking.

    overrides/<brand>.json:
      {"<model-slug>": {
         "model_name": "...",                       # optional
         "variants": {"<variant name>": {"price_incl": 249900,
                                          "note": "...", "checked": "2026-10-13"}}}}
    """
    f = OVERRIDES_DIR / f"{brand_key}.json"
    if not f.exists():
        return {}
    try:
        with open(f) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  [compile] {brand_key}: overrides file unreadable, ignoring ({e})")
        return {}


def apply_overrides(brand_obj: dict, overrides: dict) -> int:
    """Apply verified corrections onto a compiled brand. Returns how many landed."""
    if not overrides:
        return 0

    applied = 0
    for model in brand_obj.get("models", []):
        rule = overrides.get(model.get("slug"))
        if not rule:
            continue
        if rule.get("model_name"):
            model["name"] = rule["model_name"]
            applied += 1
        variant_rules = rule.get("variants", {})
        for variant in model.get("variants", []):
            vr = variant_rules.get(variant.get("name"))
            if not vr or vr.get("price_incl") is None:
                continue
            price = vr["price_incl"]
            variant["price_incl"] = price
            variant["price_excl"] = calc_excl_price(price)
            variant["price_display"] = f"R{price:,}".replace(",", " ")
            variant["monthly_estimate"] = estimate_monthly(price)
            applied += 1

        prices = [v["price_incl"] for v in model.get("variants", [])
                  if v.get("price_incl")]
        if prices:
            model["price_from"], model["price_to"] = min(prices), max(prices)
            lo = f"R{model['price_from']:,}".replace(",", " ")
            hi = f"R{model['price_to']:,}".replace(",", " ")
            model["price_range"] = lo if lo == hi else f"{lo} – {hi}"

    all_prices = [v["price_incl"] for m in brand_obj.get("models", [])
                  for v in m.get("variants", []) if v.get("price_incl")]
    if all_prices:
        brand_obj["price_from"], brand_obj["price_to"] = min(all_prices), max(all_prices)

    # An override that matches nothing is a silent lie: the model or variant was
    # renamed, so the correction is no longer being applied and nobody knows.
    expected = sum(1 for r in overrides.values()
                   for _ in r.get("variants", {})) + \
               sum(1 for r in overrides.values() if r.get("model_name"))
    if applied < expected:
        print(f"  [compile] {brand_obj.get('key')}: {expected - applied} override(s) "
              f"matched nothing, check the model and variant names")

    return applied


def check_brand_regression(brand_file: Path, new_brand: dict) -> list[str]:
    """Reasons this brand catalogue must not overwrite the one already on disk.

    These feeds publish straight onto live dealer websites, so a bad scrape is
    not an inconvenience, it is wrong prices and missing vehicles in front of
    customers. On 9 October a run wrote mangled model names into Changan, Foton,
    JAC, MG, Mitsubishi and Nissan, and dropped JAC's N56, N140 and both EVs
    entirely. Nothing checked, nothing complained, and the only reason it never
    reached a customer is that nobody happened to run the sync afterwards.

    Returns an empty list when the new catalogue is safe to write. Set
    FEED_ALLOW_REGRESSION=1 to override, which is the right move when a brand
    genuinely has pruned its range and you have confirmed it on their site.
    """
    if os.environ.get("FEED_ALLOW_REGRESSION"):
        return []

    problems = []

    # A name carrying a hostname means the slug fell back to the URL. These are
    # unreadable on a dealer site, so they are refused whether or not anything
    # else regressed.
    mangled = [m["name"] for m in new_brand.get("models", [])
               if MANGLED_NAME.search(m.get("name", ""))]
    if mangled:
        problems.append(f"{len(mangled)} model name(s) built from a URL, "
                        f"e.g. {mangled[0]!r}")

    if not brand_file.exists():
        return problems

    try:
        with open(brand_file) as f:
            old = json.load(f)
    except (OSError, json.JSONDecodeError):
        return problems  # nothing trustworthy to compare against

    # Identify models by source_url where we have one, because a model that was
    # merged with its own duplicate has not been lost, it has been deduplicated,
    # and its slug legitimately changes. Comparing slugs alone flagged Jeep and
    # GAC as regressions for exactly that reason. Fall back to the slug for old
    # entries that predate source_url being recorded.
    def identity(models):
        out = {}
        for m in models:
            url = (m.get("source_url") or "").strip().rstrip("/")
            url = url.replace("://www.", "://").lower()
            out[url or f"slug:{m.get('slug')}"] = m.get("slug")
        return out

    old_models = identity(old.get("models", []))
    new_models = identity(new_brand.get("models", []))
    if old_models:
        lost = set(old_models) - set(new_models)
        if len(lost) / len(old_models) > MAX_MODEL_LOSS:
            sample = ", ".join(sorted(old_models[k] or k for k in lost)[:4])
            problems.append(f"{len(lost)} of {len(old_models)} models would "
                            f"disappear ({sample}...)")

    # Model count alone is not enough. BAIC kept all three model families while
    # quietly dropping two of its eight derivatives, which on a dealer site is
    # two bakkies a customer can no longer find.
    old_priced = sum(1 for m in old.get("models", [])
                     for v in m.get("variants", []) if v.get("price_incl"))
    new_priced = sum(1 for m in new_brand.get("models", [])
                     for v in m.get("variants", []) if v.get("price_incl"))
    if old_priced and new_priced == 0:
        problems.append(f"every price would be lost ({old_priced} priced "
                        f"variants before, none now)")
    elif old_priced and (old_priced - new_priced) / old_priced > MAX_MODEL_LOSS:
        problems.append(f"priced variants would fall from {old_priced} to "
                        f"{new_priced}")

    return problems


def load_raw_data() -> dict:
    """Load all raw JSON data, organized by brand/model.

    A model is identified by its source_url, not by its filename. Raw files are
    never deleted, so when a model's slug changes the old file stays behind and
    used to compile as a second, separate model: the JAC catalogue carried both
    "T6" and "Jacmotors_Co_Za_Jac T6 Single Cab", two entries for one bakkie,
    and the same happened across Changan, Foton, MG, Mitsubishi and Nissan.
    Keying on the URL collapses them without deleting anything, which matters
    because a half-finished scrape must never be able to destroy good data.

    When two files describe the same URL the RICHER one wins, not the newer.
    Recency is the obvious rule and it is the wrong one here: the October
    manufacturer-site scrape is consistently thinner than the catalogue it sits
    beside, because it reads prices off a marketing page rather than a spec
    table. BAIC's x55.json (October) holds one variant and no model name where
    x55-plus.json (June) holds four with full specs. Preferring the newer file
    would have thrown away three real derivatives and the model's display name
    to gain nothing. Files with no source_url fall back to the filename.
    """
    data = {}
    if not RAW_DIR.exists():
        return data

    def richness(spec: dict) -> tuple:
        variants = spec.get("variants") or []
        return (
            sum(1 for v in variants if v.get("price_incl")),
            sum(len(v.get("specs") or {}) for v in variants),
            1 if spec.get("model_name") else 0,
            spec.get("scraped_at", ""),
        )

    for brand_dir in RAW_DIR.iterdir():
        if not brand_dir.is_dir():
            continue
        brand_key = brand_dir.name
        data[brand_key] = {}
        seen: dict[str, tuple[str, tuple]] = {}  # url -> (slug, richness)

        for json_file in sorted(brand_dir.glob("*.json")):
            if json_file.name.endswith("_images.json"):
                continue
            model_slug = json_file.stem
            with open(json_file) as f:
                spec_data = json.load(f)

            # Trailing slashes and www. are not a difference worth splitting a
            # model over.
            url = (spec_data.get("source_url") or "").strip().rstrip("/")
            url = url.replace("://www.", "://").lower()
            if url:
                score = richness(spec_data)
                previous = seen.get(url)
                if previous:
                    prev_slug, prev_score = previous
                    keep_this = score > prev_score
                    winner, loser = ((model_slug, prev_slug) if keep_this
                                     else (prev_slug, model_slug))
                    print(f"  [compile] {brand_key}: '{loser}' and '{winner}' are the "
                          f"same model ({url}), keeping the fuller '{winner}'")
                    # The display name is the one field where the thinner file
                    # is often the better one, because the richer scrape reads
                    # specs off the page but never learns what the model is
                    # called. BAIC's b40.json carries more specs and no name,
                    # so without this the model would render as "B40" instead
                    # of "B40 Plus".
                    if keep_this:
                        if not spec_data.get("model_name"):
                            inherited = (data[brand_key].get(prev_slug, {})
                                         .get("specs", {}).get("model_name"))
                            if inherited:
                                spec_data["model_name"] = inherited
                        data[brand_key].pop(prev_slug, None)
                    else:
                        kept = data[brand_key].get(prev_slug, {}).get("specs", {})
                        if not kept.get("model_name") and spec_data.get("model_name"):
                            kept["model_name"] = spec_data["model_name"]
                        continue
                seen[url] = (model_slug, score)

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
        n_over = apply_overrides(brand_obj, load_overrides(brand_key))
        if n_over:
            print(f"  [compile] {brand_key}: applied {n_over} verified override(s)")
        feed["brands"].append(brand_obj)

        # Per-brand JSON file
        brand_file = brands_dir / f"{brand_key}.json"
        regressions = check_brand_regression(brand_file, brand_obj)
        if regressions:
            total_issues += len(regressions)
            print(f"  ✗ {brand_key}: REFUSED, kept the previous catalogue")
            for r in regressions:
                print(f"      {r}")
            print(f"      To publish anyway: FEED_ALLOW_REGRESSION=1")
            continue

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
