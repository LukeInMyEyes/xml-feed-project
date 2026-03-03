"""
MotorPress — explore VEHICLES/brands section and Suzuki pricelist.
"""
import asyncio
import random
import os
from playwright.async_api import async_playwright

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "motopress_screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

FULL_USER = "dealerdigitalza@gmail.com"
FULL_PASS = "D34l3r!"

SUZUKI_USER = "admin@thedealersedge.co.za"
SUZUKI_PASS = "DogWithNoName!"

async def human_delay(min_s=1.5, max_s=4.0):
    await asyncio.sleep(random.uniform(min_s, max_s))

async def human_type(locator, text):
    await locator.click()
    await asyncio.sleep(random.uniform(0.3, 0.8))
    for ch in text:
        await locator.press_sequentially(ch, delay=random.randint(60, 200))
        if random.random() < 0.08:
            await asyncio.sleep(random.uniform(0.3, 0.7))

async def screenshot(page, name):
    path = os.path.join(SCREENSHOTS_DIR, f"{name}.png")
    await page.screenshot(path=path, full_page=False)
    print(f"  Screenshot: {path}")

async def login_motorpress(page, url, user, pw):
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await human_delay(3, 5)
    inputs = page.locator("input:visible")
    await human_type(inputs.nth(0), user)
    await human_delay(0.8, 1.5)
    await human_type(inputs.nth(1), pw)
    await human_delay(1, 2)
    await page.locator("button:has-text('LOGIN')").first.click()
    await human_delay(8, 12)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="en-ZA",
            timezone_id="Africa/Johannesburg",
            accept_downloads=True,
        )

        # === Part 1: Main MotorPress — VEHICLES/brands ===
        page = await context.new_page()
        print("="*60)
        print("  Part 1: MotorPress VEHICLES section")
        print("="*60)

        print("\n[1] Logging in to motorpress.co.za...")
        await login_motorpress(page, "https://motorpress.co.za", FULL_USER, FULL_PASS)
        print(f"  URL: {page.url}")

        print("\n[2] Navigating to /brands (VEHICLES)...")
        await page.goto("https://motorpress.co.za/brands", wait_until="networkidle", timeout=30000)
        await human_delay(5, 8)
        await screenshot(page, "brands_01_page")
        print(f"  URL: {page.url}")

        body_text = await page.locator("body").inner_text()
        print(f"\n  Brands page text (first 3000 chars):\n{body_text[:3000]}")

        # List all brand links
        links = page.locator("a:visible")
        link_count = await links.count()
        seen = set()
        print(f"\n  Links ({link_count}):")
        for i in range(min(link_count, 60)):
            try:
                link = links.nth(i)
                text = (await link.inner_text()).strip()[:60]
                href = await link.get_attribute("href") or ""
                if href and href not in seen and text:
                    seen.add(href)
                    print(f"    '{text}' -> {href}")
            except:
                pass

        # Scroll to see more
        await page.evaluate("window.scrollTo(0, 800)")
        await human_delay(2, 3)
        await screenshot(page, "brands_02_scrolled")

        # Click on a brand (e.g., Toyota or Nissan)
        print("\n[3] Looking for a specific brand to explore...")
        nissan_link = page.locator("a:has-text('Nissan'):visible")
        nissan_cnt = await nissan_link.count()
        if nissan_cnt > 0:
            print(f"  Found {nissan_cnt} Nissan links, clicking first...")
            await human_delay(2, 3)
            await nissan_link.first.click()
            await human_delay(5, 8)
            await screenshot(page, "brands_03_nissan")
            print(f"  URL: {page.url}")

            body_text = await page.locator("body").inner_text()
            print(f"\n  Nissan page text (first 3000 chars):\n{body_text[:3000]}")

            # Look for model links
            links = page.locator("a:visible")
            link_count = await links.count()
            seen = set()
            print(f"\n  Nissan links:")
            for i in range(min(link_count, 40)):
                try:
                    link = links.nth(i)
                    text = (await link.inner_text()).strip()[:80]
                    href = await link.get_attribute("href") or ""
                    if href and href not in seen and text and ('diskdrive' in href or 'brand' in href or 'vehicle' in href):
                        seen.add(href)
                        print(f"    '{text}' -> {href}")
                except:
                    pass

            # Scroll for more
            await page.evaluate("window.scrollTo(0, 600)")
            await human_delay(2, 3)
            await screenshot(page, "brands_04_nissan_scrolled")

        # Try the diskdrive feature
        print("\n[4] Checking diskdrive feature...")
        diskdrive_links = page.locator("a[href*='diskdrive']:visible")
        dd_cnt = await diskdrive_links.count()
        print(f"  Diskdrive links found: {dd_cnt}")
        if dd_cnt > 0:
            href = await diskdrive_links.first.get_attribute("href")
            text = (await diskdrive_links.first.inner_text()).strip()[:60]
            print(f"  First diskdrive: '{text}' -> {href}")
            await human_delay(2, 4)
            await diskdrive_links.first.click()
            await human_delay(5, 8)
            await screenshot(page, "brands_05_diskdrive")
            print(f"  URL: {page.url}")

            body_text = await page.locator("body").inner_text()
            print(f"\n  Diskdrive text (first 2000 chars):\n{body_text[:2000]}")

            # Look for images on diskdrive
            images = page.locator("img:visible")
            img_count = await images.count()
            print(f"\n  Images: {img_count}")
            for i in range(min(img_count, 15)):
                try:
                    src = await images.nth(i).get_attribute("src") or ""
                    alt = await images.nth(i).get_attribute("alt") or ""
                    if src and not src.startswith("data:"):
                        print(f"    [{i}] alt='{alt}' src={src[:120]}")
                except:
                    pass

        # === Part 2: Suzuki MotorPress — Pricelist folder ===
        page2 = await context.new_page()
        print("\n\n" + "="*60)
        print("  Part 2: Suzuki MotorPress — Pricelist & Model Images")
        print("="*60)

        print("\n[5] Logging in to suzuki.motorpress.co.za...")
        await login_motorpress(page2, "https://suzuki.motorpress.co.za", SUZUKI_USER, SUZUKI_PASS)
        print(f"  URL: {page2.url}")

        # Navigate to the pricelist folder
        print("\n[6] Opening WEBSITE PRICELIST folder...")
        await human_delay(2, 4)
        await page2.goto("https://suzuki.motorpress.co.za/folders/suzuki/6d0eeb16-f8e0-402a-86b2-e42843c1cc7b",
                         wait_until="networkidle", timeout=30000)
        await human_delay(5, 8)
        await screenshot(page2, "suzuki_pricelist_01")
        print(f"  URL: {page2.url}")

        body_text = await page2.locator("body").inner_text()
        print(f"\n  Pricelist folder text (first 2000 chars):\n{body_text[:2000]}")

        # Look for downloadable files
        links = page2.locator("a:visible")
        link_count = await links.count()
        seen = set()
        print(f"\n  Pricelist links ({link_count}):")
        for i in range(min(link_count, 30)):
            try:
                link = links.nth(i)
                text = (await link.inner_text()).strip()[:80]
                href = await link.get_attribute("href") or ""
                if href and href not in seen and text:
                    seen.add(href)
                    print(f"    '{text}' -> {href}")
            except:
                pass

        # Also check one model folder for images (e.g., Jimny 5-Door)
        print("\n[7] Opening Jimny 5-Door folder for images...")
        await human_delay(3, 5)
        await page2.goto("https://suzuki.motorpress.co.za/folders/suzuki/58a55f93-57e6-4bcf-9c09-3b0fd77baf86",
                         wait_until="networkidle", timeout=30000)
        await human_delay(5, 8)
        await screenshot(page2, "suzuki_jimny5_01")
        print(f"  URL: {page2.url}")

        body_text = await page2.locator("body").inner_text()
        print(f"\n  Jimny 5-Door folder text (first 2000 chars):\n{body_text[:2000]}")

        # Look for images
        images = page2.locator("img:visible")
        img_count = await images.count()
        print(f"\n  Images: {img_count}")
        for i in range(min(img_count, 20)):
            try:
                src = await images.nth(i).get_attribute("src") or ""
                alt = await images.nth(i).get_attribute("alt") or ""
                if src and not src.startswith("data:") and len(src) > 20:
                    print(f"    [{i}] alt='{alt}' src={src[:150]}")
            except:
                pass

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
