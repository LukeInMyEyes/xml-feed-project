"""
QuickPic AutoSpec — intercept API calls to find the data endpoint.
Also export a multi-vehicle Excel to see the batch format.
"""
import asyncio
import random
import os
import json
from playwright.async_api import async_playwright

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "quickpic_screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

USERNAME = "dealerdigitalza@gmail.com"
PASSWORD = "LukeJason#1"

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

# Store intercepted API calls
api_calls = []

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
        page = await context.new_page()

        # Intercept network requests to find API endpoints
        async def on_response(response):
            url = response.url
            if ("api" in url.lower() or "autospec" in url.lower() or
                "spec" in url.lower() or "vehicle" in url.lower()) and \
                "quickpic" in url and \
                not url.endswith(('.js', '.css', '.png', '.jpg', '.svg', '.woff', '.woff2')):
                try:
                    content_type = response.headers.get("content-type", "")
                    status = response.status
                    api_calls.append({
                        "url": url,
                        "status": status,
                        "content_type": content_type,
                        "method": response.request.method,
                    })
                except:
                    pass

        page.on("response", on_response)

        # --- Login ---
        print("[1] Logging in...")
        await page.goto("https://www.quickpic.co.za", wait_until="networkidle", timeout=60000)
        await human_delay(3, 5)
        await page.locator("button:has-text('LOGIN')").first.click()
        await human_delay(2, 3)
        await human_type(page.locator("input[name='email']").first, USERNAME)
        await human_delay(0.8, 1.5)
        await human_type(page.locator("input[type='password']").first, PASSWORD)
        await human_delay(1, 2)
        await page.locator("button:has-text('Login')").last.click()
        await human_delay(8, 12)
        print(f"  Logged in. URL: {page.url}")

        # Clear captured calls from login
        api_calls.clear()

        # --- Go to AutoSpec ---
        print("\n[2] Going to AutoSpec...")
        await page.goto("https://www.quickpic.co.za/autospec", wait_until="networkidle", timeout=60000)
        await human_delay(3, 5)

        print(f"\n  API calls captured during AutoSpec load ({len(api_calls)}):")
        for call in api_calls:
            print(f"    {call['method']} {call['url']} [{call['status']}] {call['content_type'][:50]}")

        # Clear and open vehicle selector
        api_calls.clear()

        # Click +Vehicle to open dialog
        print("\n[3] Opening vehicle selector...")
        vehicle_text = page.locator("text='Vehicle'").first
        await human_delay(1, 2)
        await vehicle_text.click()
        await human_delay(3, 5)

        print(f"\n  API calls during dialog open ({len(api_calls)}):")
        for call in api_calls:
            print(f"    {call['method']} {call['url']} [{call['status']}] {call['content_type'][:50]}")

        # Search for a vehicle
        api_calls.clear()
        search_input = page.locator("input[placeholder*='Search']").first
        await human_type(search_input, "Toyota Hilux")
        await human_delay(3, 5)

        print(f"\n  API calls during search ({len(api_calls)}):")
        for call in api_calls:
            print(f"    {call['method']} {call['url']} [{call['status']}] {call['content_type'][:50]}")

        # Try to get the response body of the last API call
        if api_calls:
            last_url = api_calls[-1]['url']
            print(f"\n  Last API URL: {last_url}")

        # Click on a Toyota Hilux variant
        await screenshot(page, "40_hilux_search")
        body_text = await page.locator("body").inner_text()
        if "Hilux" in body_text:
            idx = body_text.index("Hilux")
            print(f"\n  Hilux results:\n{body_text[idx:idx+2000]}")

        # Select the first Hilux variant by checking its checkbox
        hilux_variant = page.locator("text=/Hilux.*2\\.4/").first
        if await hilux_variant.count() > 0:
            api_calls.clear()
            await human_delay(1, 2)
            await hilux_variant.click()
            await human_delay(2, 3)

            print(f"\n  API calls after selecting variant ({len(api_calls)}):")
            for call in api_calls:
                print(f"    {call['method']} {call['url']} [{call['status']}] {call['content_type'][:50]}")

        # Click Show
        api_calls.clear()
        show_btn = page.locator("button:has-text('Show')").first
        await human_delay(1, 2)
        await show_btn.click()
        await human_delay(5, 8)

        print(f"\n  API calls after Show ({len(api_calls)}):")
        for call in api_calls:
            print(f"    {call['method']} {call['url']} [{call['status']}] {call['content_type'][:50]}")

        # Check if there's a direct API that returns JSON
        json_calls = [c for c in api_calls if 'json' in c.get('content_type', '')]
        print(f"\n  JSON API calls: {len(json_calls)}")
        for call in json_calls:
            print(f"    {call['method']} {call['url']}")

        await screenshot(page, "41_hilux_loaded")

        # Now try to read the API response
        # Let's also intercept the actual response bodies on the next request
        api_bodies = {}

        async def capture_response(response):
            url = response.url
            if "quickpic" in url and ("api" in url.lower() or "autospec" in url.lower()):
                try:
                    body = await response.text()
                    api_bodies[url] = body[:2000]
                except:
                    pass

        page.on("response", capture_response)

        # Try the Excel export to see if it triggers an API call
        api_calls.clear()
        print("\n[4] Trying Excel export...")
        try:
            excel_btn = page.locator("text='Excel Sheet'").first
            async with page.expect_download(timeout=15000) as download_info:
                await human_delay(1, 2)
                await excel_btn.click()
            download = await download_info.value
            fname = download.suggested_filename or "hilux_export.xlsx"
            save_path = os.path.join(SCREENSHOTS_DIR, fname)
            await download.save_as(save_path)
            print(f"  Excel downloaded: {save_path}")
        except Exception as e:
            print(f"  Excel export failed: {e}")

        print(f"\n  API calls during Excel export ({len(api_calls)}):")
        for call in api_calls:
            print(f"    {call['method']} {call['url']} [{call['status']}] {call['content_type'][:50]}")

        # Dump captured API bodies
        print(f"\n  Captured API response bodies ({len(api_bodies)}):")
        for url, body in api_bodies.items():
            print(f"    URL: {url}")
            print(f"    Body: {body[:500]}")

        # Save all API calls for analysis
        all_calls_path = os.path.join(SCREENSHOTS_DIR, "api_calls.json")
        with open(all_calls_path, "w") as f:
            json.dump(api_calls + [{"bodies": api_bodies}], f, indent=2)
        print(f"\n  Saved API calls to: {all_calls_path}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
