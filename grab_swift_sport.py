"""Quick scrape: Swift Sport images from Suzuki MotorPress."""
import json, time, re, sys, os
from pathlib import Path
from urllib.parse import urljoin
os.environ.setdefault("PYTHONUTF8", "1")
from playwright.sync_api import sync_playwright

RAW_DIR = Path(__file__).parent / "raw_data" / "suzuki"
LOGIN_URL = "https://suzuki.motorpress.co.za"
SKIP = ["pdf.jpg","logo","icon","favicon","sprite","placeholder","spacer","pixel",
        "tracking","social","facebook","twitter","instagram","youtube","linkedin",
        "arrow","close","menu","search","1x1","blank","storage/defaults"]

def is_ok(url):
    u = url.lower()
    return "motorpress.co.za/images/" in u and not any(s in u for s in SKIP)

def classify(url, alt=""):
    c = f"{url} {alt}".lower()
    if any(k in c for k in ["interior","cabin","dashboard"]): return "Interior"
    if any(k in c for k in ["rear","back","tail"]): return "ExteriorRear"
    if any(k in c for k in ["front","face","headlight","grille"]): return "ExteriorFront"
    if any(k in c for k in ["lifestyle","action","driving"]): return "Lifestyle"
    if any(k in c for k in [".png","cutout","deep etch","jellybean"]): return "Jellybean"
    return "ExteriorFront"

def get_links(page):
    """Collect all folder links as plain dicts before navigating."""
    links = []
    for a in page.query_selector_all("a"):
        try:
            href = a.get_attribute("href") or ""
            text = (a.text_content() or "").strip()
            if "/folders/" in href and text:
                links.append({"href": href, "text": text})
        except:
            pass
    return links

def get_imgs(page):
    imgs = []
    for img in page.query_selector_all("img"):
        try:
            src = img.get_attribute("src") or img.get_attribute("data-src") or ""
            if not src or src.startswith("data:") or src.endswith(".svg"): continue
            full = urljoin(page.url, src)
            if is_ok(full):
                imgs.append({"url": full, "alt": img.get_attribute("alt") or ""})
        except:
            pass
    return imgs

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_context(viewport={"width":1280,"height":900}).new_page()

    # Login
    page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
    time.sleep(2)
    page.query_selector('input[type="text"]').fill("admin@thedealersedge.co.za")
    page.query_selector('input[type="password"]').fill("DogWithNoName!")
    page.query_selector('button[type="submit"]').click()
    page.wait_for_load_state("networkidle", timeout=30000)
    time.sleep(2)
    try:
        page.query_selector('button:has-text("ACCEPT")').click()
        time.sleep(1)
    except: pass
    print("Logged in")

    # Find Swift Sport folder URL from home
    home = page.url
    sport_url = None
    for link in get_links(page):
        if "swift sport" in link["text"].lower():
            sport_url = urljoin(home, link["href"])
            print(f"Found: {link['text'][:40]} -> {sport_url[:60]}")
            break

    if not sport_url:
        print("Swift Sport folder not found!")
        browser.close()
        sys.exit(1)

    # Navigate to Swift Sport folder
    page.goto(sport_url, wait_until="networkidle", timeout=20000)
    time.sleep(2)

    # Collect sub-folder links (as plain data, before navigating away)
    sub_links = get_links(page)
    print(f"Sub-folders: {len(sub_links)}")

    all_imgs = []
    visited = {sport_url}

    for sf in sub_links:
        sf_url = urljoin(home, sf["href"])
        if sf_url in visited: continue
        visited.add(sf_url)
        sf_t = sf["text"].lower()
        if any(s in sf_t for s in ["price","spec","brochure","pdf","video","radio","press release"]): continue

        try:
            page.goto(sf_url, wait_until="networkidle", timeout=15000)
            time.sleep(1.5)
        except:
            continue

        imgs = get_imgs(page)
        if imgs:
            all_imgs.extend(imgs)
            print(f"  [{sf['text'][:30]:30s}] {len(imgs)} images")

        # Collect deeper links before navigating
        deeper = get_links(page)
        for ssf in deeper[:8]:
            ssf_url = urljoin(home, ssf["href"])
            if ssf_url in visited: continue
            visited.add(ssf_url)
            ssf_t = ssf["text"].lower()
            if any(s in ssf_t for s in ["price","spec","brochure","pdf","video","radio"]): continue
            try:
                page.goto(ssf_url, wait_until="networkidle", timeout=15000)
                time.sleep(1.5)
            except:
                continue
            imgs = get_imgs(page)
            if imgs:
                all_imgs.extend(imgs)
                print(f"    [{ssf['text'][:28]:28s}] {len(imgs)} images")

    # Deduplicate
    seen = set()
    unique = [i for i in all_imgs if i["url"] not in seen and not seen.add(i["url"])]

    # Classify top 5
    typed = {}
    for img in unique:
        if len(typed) >= 5: break
        t = classify(img["url"], img.get("alt",""))
        if t not in typed: typed[t] = img["url"]
    for img in unique:
        if len(typed) >= 5: break
        if img["url"] not in typed.values():
            for t in ["ExteriorFront","ExteriorRear","Interior","Lifestyle","Jellybean"]:
                if t not in typed:
                    typed[t] = img["url"]
                    break

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    imgs_list = [{"type": t, "url": u} for t, u in typed.items()]
    out = RAW_DIR / "swift-sport_images.json"
    with open(out, "w") as f:
        json.dump({
            "brand": "suzuki", "model_slug": "swift-sport",
            "source_url": LOGIN_URL,
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "image_count": len(imgs_list), "images": imgs_list
        }, f, indent=2)

    print(f"\nSaved {len(imgs_list)} images -> {out.name} (from {len(unique)} unique)")
    browser.close()
