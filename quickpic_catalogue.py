"""
QuickPic AutoSpec — Dump catalogue by searching each brand.
Reloads page between brands to avoid modal issues.
Ultra-random human delays.
"""
import asyncio
import random
import os
import json
import re
from playwright.async_api import async_playwright

CATALOGUE_FILE = os.path.join(os.path.dirname(__file__), "quickpic_catalogue.json")

USERNAME = "dealerdigitalza@gmail.com"
PASSWORD = "LukeJason#1"

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


async def wild_delay():
    """Ultra-random — Luke style. Sometimes 5s, sometimes 35s."""
    r = random.random()
    if r < 0.20:
        d = random.uniform(4, 8)
    elif r < 0.55:
        d = random.uniform(9, 16)
    elif r < 0.80:
        d = random.uniform(17, 25)
    elif r < 0.92:
        d = random.uniform(26, 42)
    else:
        d = random.uniform(50, 85)
    print(f"    ... {d:.0f}s pause")
    await asyncio.sleep(d)


async def human_type(locator, text):
    await locator.click()
    await asyncio.sleep(random.uniform(0.4, 1.2))
    for ch in text:
        ms = random.randint(45, 230)
        if random.random() < 0.10:
            ms = random.randint(350, 800)
        await locator.press_sequentially(ch, delay=ms)
    await asyncio.sleep(random.uniform(0.5, 2))


def parse_brand_tree(full_text, qp_brand_name):
    """Extract models and variants from the dialog text for one brand."""
    models = {}

    # Find the brand line e.g. "Volkswagen (94)"
    pattern = re.escape(qp_brand_name) + r'\s*\((\d+)\)'
    brand_match = re.search(pattern, full_text)
    if not brand_match:
        return models, 0

    brand_count = int(brand_match.group(1))
    # Get text after brand match
    after_brand = full_text[brand_match.end():]

    # Split into lines
    lines = after_brand.split('\n')

    current_model = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Stop if we hit another top-level brand (e.g. "Audi (96)")
        if re.match(r'^[A-Z][a-zA-Z\-]+(?: [A-Z][a-zA-Z\-]+)* \(\d+\)$', line):
            # Check it's not a model under our brand
            if current_model is None and line != f"{qp_brand_name} ({brand_count})":
                break

        # Model line: "Polo (9)" or "Hilux (27)"
        model_match = re.match(r'^(.+?)\s*\((\d+)\)$', line)
        if model_match:
            candidate = model_match.group(1).strip()
            count = int(model_match.group(2))
            # Is this a model under our brand or a different brand?
            if count <= brand_count and candidate != qp_brand_name:
                current_model = candidate
                models[current_model] = {"count": count, "variants": []}
                i += 1
                continue
            elif candidate != qp_brand_name:
                # Probably hit next brand
                break

        # Variant: next line should be "(dd Mon yyyy)" then "R xxx xxx"
        if current_model and line and not re.match(r'^\(', line):
            # Check if it looks like a variant name (not a UI element)
            skip_words = {"Reset Filters", "Show", "Compare", "More", "Latest",
                         "Launch Timeline", "Latest Models Specs", "Intro Date",
                         "Compare Vehicles", "Body Shape", "Min Price", "Max Price",
                         "Fuel Type", "Gearbox Type", "Spec Type"}
            if line in skip_words or line.startswith("R ") or line.startswith("R\u00a0"):
                i += 1
                continue

            variant_name = line
            date_str = ""
            price_str = ""

            # Next line: date in parens
            if i + 1 < len(lines):
                next_l = lines[i + 1].strip()
                date_m = re.match(r'^\((.+?)\)$', next_l)
                if date_m:
                    date_str = date_m.group(1)
                    i += 1
                    # Next: price
                    if i + 1 < len(lines):
                        price_l = lines[i + 1].strip()
                        price_m = re.match(r'^R\s*([\d\s,]+)', price_l)
                        if price_m:
                            price_str = price_m.group(1).replace(" ", "").replace(",", "")
                            i += 1

            if date_str or price_str:
                models[current_model]["variants"].append({
                    "name": variant_name,
                    "date": date_str,
                    "price": price_str,
                })
            elif not re.match(r'^(Search|Clear|All|Vehicle|\+)', variant_name):
                # Might be a variant without date/price visible
                models[current_model]["variants"].append({
                    "name": variant_name,
                    "date": "",
                    "price": "",
                })

        i += 1

    total = sum(len(m["variants"]) for m in models.values())
    return models, total


async def main():
    catalogue = {}
    if os.path.exists(CATALOGUE_FILE):
        with open(CATALOGUE_FILE, "r") as f:
            catalogue = json.load(f)
        print(f"Resuming: {len(catalogue)} brands already done")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="en-ZA",
            timezone_id="Africa/Johannesburg",
        )
        page = await context.new_page()

        # Login
        print("[LOGIN]")
        await page.goto("https://www.quickpic.co.za", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(random.uniform(4, 7))
        await page.locator("button:has-text('LOGIN')").first.click()
        await asyncio.sleep(random.uniform(2, 4))
        await human_type(page.locator("input[name='email']").first, USERNAME)
        await asyncio.sleep(random.uniform(1, 2))
        await human_type(page.locator("input[type='password']").first, PASSWORD)
        await asyncio.sleep(random.uniform(1.5, 3))
        await page.locator("button:has-text('Login')").last.click()
        await asyncio.sleep(random.uniform(10, 15))
        print(f"  Logged in: {page.url}")

        brand_keys = list(BRAND_MAP.keys())
        random.shuffle(brand_keys)

        for idx, brand_key in enumerate(brand_keys):
            qp_name = BRAND_MAP[brand_key]

            if brand_key in catalogue and catalogue[brand_key].get("total_variants", 0) > 0:
                print(f"\n[{idx+1}/{len(brand_keys)}] {qp_name} — already done ({catalogue[brand_key]['total_variants']} variants)")
                continue

            print(f"\n[{idx+1}/{len(brand_keys)}] {qp_name}...")
            await wild_delay()

            # Navigate fresh to AutoSpec each time (avoids modal issues)
            await page.goto("https://www.quickpic.co.za/autospec", wait_until="networkidle", timeout=60000)
            await asyncio.sleep(random.uniform(4, 8))

            # Click +Vehicle to open dialog
            try:
                vehicle_label = page.locator("#SelectVehicleLabel").first
                if await vehicle_label.count() == 0:
                    vehicle_label = page.locator("text='Vehicle'").first
                await vehicle_label.click(timeout=10000)
            except:
                # Force-click via JS if intercepted
                try:
                    await page.evaluate("""
                        document.getElementById('SelectVehicleLabel')?.click()
                    """)
                except:
                    pass
            await asyncio.sleep(random.uniform(3, 6))

            # Search for brand
            search = page.locator("input[placeholder*='Search']").first
            if await search.count() == 0:
                print("  ERROR: No search input found after opening dialog")
                continue

            await human_type(search, qp_name)
            await asyncio.sleep(random.uniform(4, 8))

            # Get full page text
            body_text = await page.locator("body").inner_text()

            # Save raw text for debugging
            raw_path = os.path.join(os.path.dirname(__file__), "quickpic_screenshots", f"raw_{brand_key}.txt")
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(body_text)

            # Parse
            models, total = parse_brand_tree(body_text, qp_name)
            print(f"  Found {len(models)} models, {total} variants")
            for mname, mdata in models.items():
                print(f"    {mname} ({mdata['count']}): {len(mdata['variants'])} variants")
                for v in mdata['variants'][:2]:
                    print(f"      - {v['name']} {v.get('date','')} R{v.get('price','?')}")
                if len(mdata['variants']) > 2:
                    print(f"      ... +{len(mdata['variants'])-2} more")

            catalogue[brand_key] = {
                "qp_name": qp_name,
                "models": models,
                "total_variants": total,
            }

            # Checkpoint save
            with open(CATALOGUE_FILE, "w") as f:
                json.dump(catalogue, f, indent=2)

        await browser.close()

    # Summary
    print("\n" + "="*60)
    print("  CATALOGUE COMPLETE")
    print("="*60)
    grand_total = 0
    for key in sorted(catalogue.keys()):
        data = catalogue[key]
        tv = data.get("total_variants", 0)
        grand_total += tv
        nm = len(data.get("models", {}))
        print(f"  {data.get('qp_name', key):20s} {nm:3d} models  {tv:4d} variants")
    print(f"\n  TOTAL: {grand_total} variants across {len(catalogue)} brands")
    print(f"  Saved: {CATALOGUE_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
