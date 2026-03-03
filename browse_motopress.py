"""
MotorPress browser — login and explore both the main site and Suzuki portal.
"""
import asyncio
import random
import os
from playwright.async_api import async_playwright

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "motopress_screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

SUZUKI_USER = "admin@thedealersedge.co.za"
SUZUKI_PASS = "DogWithNoName!"

FULL_USER = "dealerdigitalza@gmail.com"
FULL_PASS = "D34l3r!"

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

async def login_and_explore(page, site_name, url, username, password):
    print(f"\n{'='*60}")
    print(f"  {site_name}: {url}")
    print(f"{'='*60}")

    print(f"\n[1] Visiting {url}...")
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)
    await human_delay(3, 5)

    # The form has: first input = email (type=text), second = password
    all_inputs = page.locator("input:visible")
    inp_count = await all_inputs.count()
    print(f"  Visible inputs: {inp_count}")

    if inp_count >= 2:
        print(f"[2] Logging in as {username}...")
        email_field = all_inputs.nth(0)
        pass_field = all_inputs.nth(1)

        await human_type(email_field, username)
        await human_delay(0.8, 1.5)
        await human_type(pass_field, password)
        await human_delay(1, 2)
        await screenshot(page, f"{site_name}_02_filled")

        # Click LOGIN button
        login_btn = page.locator("button:has-text('LOGIN'), button:has-text('Log'), input[type='submit']").first
        await human_delay(0.5, 1.5)
        await login_btn.click()
        await human_delay(8, 12)
        await screenshot(page, f"{site_name}_03_after_login")
        print(f"  URL: {page.url}")
        title = await page.title()
        print(f"  Title: {title}")

        # Check for errors
        body_text = await page.locator("body").inner_text()
        if "invalid" in body_text.lower()[:500] or "incorrect" in body_text.lower()[:500] or "failed" in body_text.lower()[:500]:
            print(f"  LOGIN ISSUE: {body_text[:500]}")
            return

        print(f"  Login successful!")
        print(f"\n  Page text (first 3000 chars):\n{body_text[:3000]}")

        # List all visible links
        links = page.locator("a:visible")
        link_count = await links.count()
        seen = set()
        print(f"\n  Dashboard links ({link_count}):")
        for i in range(min(link_count, 50)):
            try:
                link = links.nth(i)
                text = (await link.inner_text()).strip()[:60]
                href = await link.get_attribute("href") or ""
                if href and href not in seen and text:
                    seen.add(href)
                    print(f"    '{text}' -> {href}")
            except:
                pass

        # Search for vehicle/price related content
        print(f"\n  Searching for vehicle/image/price content...")
        for kw in ["vehicle", "car", "price", "spec", "image", "gallery", "download", "brand", "model", "press", "release"]:
            els = page.locator(f"a:visible:has-text('{kw}')")
            cnt = await els.count()
            if cnt > 0:
                for j in range(min(cnt, 3)):
                    try:
                        text = (await els.nth(j).inner_text()).strip()[:80]
                        href = await els.nth(j).get_attribute("href") or ""
                        print(f"    [{kw}] '{text}' -> {href}")
                    except:
                        pass

        # Scroll and screenshot
        await page.evaluate("window.scrollTo(0, 500)")
        await human_delay(2, 3)
        await screenshot(page, f"{site_name}_04_scrolled")

    return page.url

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale="en-ZA",
            timezone_id="Africa/Johannesburg",
        )

        # Try full MotorPress first
        page1 = await context.new_page()
        await login_and_explore(page1, "motorpress_full", "https://motorpress.co.za", FULL_USER, FULL_PASS)

        # Check the API page
        print(f"\n\n[API] Checking MotorPress API...")
        await human_delay(3, 5)
        await page1.goto("https://motorpress.co.za/api", wait_until="domcontentloaded", timeout=30000)
        await human_delay(5, 8)
        await screenshot(page1, "motorpress_api")
        body_text = await page1.locator("body").inner_text()
        print(f"  API page text (first 2000 chars):\n{body_text[:2000]}")

        # Now try Suzuki-specific MotorPress
        page2 = await context.new_page()
        await login_and_explore(page2, "suzuki_mp", "https://suzuki.motorpress.co.za", SUZUKI_USER, SUZUKI_PASS)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
