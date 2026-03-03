"""Debug QuickPic AutoSpec dialog to understand DOM structure."""
import asyncio
import random
import os
import sys
import functools
print = functools.partial(print, flush=True)

from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(__file__)
SCREENSHOT_DIR = os.path.join(BASE_DIR, "quickpic_screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

USERNAME = "dealerdigitalza@gmail.com"
PASSWORD = "LukeJason#1"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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

        email_input = page.locator("input[name='email']").first
        await email_input.click()
        await email_input.fill(USERNAME)
        await asyncio.sleep(random.uniform(1, 2))

        pw_input = page.locator("input[type='password']").first
        await pw_input.click()
        await pw_input.fill(PASSWORD)
        await asyncio.sleep(random.uniform(1, 2))

        await page.locator("button:has-text('Login')").last.click()
        await asyncio.sleep(random.uniform(8, 12))
        print(f"  Logged in: {page.url}")

        # Go to AutoSpec
        print("\n[AUTOSPEC]")
        await page.goto("https://www.quickpic.co.za/autospec", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(random.uniform(4, 7))
        await page.screenshot(path=os.path.join(SCREENSHOT_DIR, "debug_1_autospec.png"))
        print("  Screenshot: autospec page")

        # Click + Vehicle to open dialog
        print("\n[OPEN DIALOG]")
        try:
            await page.locator("#SelectVehicleLabel").first.click(timeout=10000)
        except:
            await page.evaluate("document.getElementById('SelectVehicleLabel')?.click()")
        await asyncio.sleep(random.uniform(3, 5))
        await page.screenshot(path=os.path.join(SCREENSHOT_DIR, "debug_2_dialog_open.png"))
        print("  Screenshot: dialog open")

        # Search for Volkswagen Polo
        print("\n[SEARCH VW POLO]")
        search_input = page.locator("input[placeholder*='Search']").first
        cnt = await search_input.count()
        print(f"  Search inputs found: {cnt}")

        if cnt > 0:
            await search_input.click()
            await asyncio.sleep(0.5)
            await search_input.fill("Volkswagen Polo")
            await asyncio.sleep(random.uniform(3, 5))
            await page.screenshot(path=os.path.join(SCREENSHOT_DIR, "debug_3_search_results.png"))
            print("  Screenshot: search results")

            # Dump the dialog HTML to understand structure
            # Get the modal/dialog content
            dialog_html = await page.evaluate("""() => {
                // Look for the modal/dialog
                const modal = document.querySelector('.w3-modal') ||
                              document.querySelector('[class*="modal"]') ||
                              document.querySelector('[class*="dialog"]');
                if (modal) return modal.innerHTML.substring(0, 8000);
                return 'NO MODAL FOUND';
            }""")

            with open(os.path.join(SCREENSHOT_DIR, "debug_dialog_html.txt"), "w", encoding="utf-8") as f:
                f.write(dialog_html)
            print(f"  Dialog HTML saved ({len(dialog_html)} chars)")

            # Also dump the visible text in the dialog
            dialog_text = await page.evaluate("""() => {
                const modal = document.querySelector('.w3-modal') ||
                              document.querySelector('[class*="modal"]');
                if (modal) return modal.innerText;
                return 'NO MODAL FOUND';
            }""")

            with open(os.path.join(SCREENSHOT_DIR, "debug_dialog_text.txt"), "w", encoding="utf-8") as f:
                f.write(dialog_text)
            print(f"  Dialog text saved ({len(dialog_text)} chars)")

            # Count checkboxes
            cb_count = await page.locator("input[type='checkbox']").count()
            print(f"  Checkboxes found: {cb_count}")

            # Look at what elements contain "Polo" text
            polo_elements = await page.evaluate("""() => {
                const results = [];
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_ELEMENT,
                    null,
                    false
                );
                while (walker.nextNode()) {
                    const node = walker.currentNode;
                    const text = node.textContent || '';
                    if (text.includes('1.0 TSI') && text.length < 200) {
                        results.push({
                            tag: node.tagName,
                            class: node.className,
                            id: node.id,
                            text: text.substring(0, 150),
                            childCount: node.children.length,
                            html: node.outerHTML.substring(0, 300)
                        });
                    }
                    if (results.length > 20) break;
                }
                return results;
            }""")

            print(f"\n  Elements containing '1.0 TSI': {len(polo_elements)}")
            for el in polo_elements[:10]:
                print(f"    <{el['tag']} class='{el.get('class','')}' id='{el.get('id','')}'>")
                print(f"      text: {el['text'][:100]}")
                print(f"      html: {el['html'][:200]}")
                print()

        await browser.close()
        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
