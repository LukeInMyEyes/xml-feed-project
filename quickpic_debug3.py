"""Quick debug: dump chkboxItem texts after expanding Volkswagen."""
import asyncio, random, os, sys, functools, json
print = functools.partial(print, flush=True)
from playwright.async_api import async_playwright

USERNAME = "dealerdigitalza@gmail.com"
PASSWORD = "LukeJason#1"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="en-ZA", timezone_id="Africa/Johannesburg",
        )
        page = await ctx.new_page()

        print("[LOGIN]")
        await page.goto("https://www.quickpic.co.za", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)
        await page.locator("button:has-text('LOGIN')").first.click()
        await asyncio.sleep(3)
        await page.locator("input[name='email']").first.fill(USERNAME)
        await asyncio.sleep(1)
        await page.locator("input[type='password']").first.fill(PASSWORD)
        await asyncio.sleep(1)
        await page.locator("button:has-text('Login')").last.click()
        await asyncio.sleep(10)
        print(f"  Logged in: {page.url}")

        print("\n[AUTOSPEC]")
        await page.goto("https://www.quickpic.co.za/autospec", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)

        # Open dialog
        await page.locator("#SelectVehicleLabel").first.click(timeout=10000)
        await asyncio.sleep(4)

        # Click Volkswagen
        print("\n[CLICK VW]")
        await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                const items = m.querySelectorAll('.chkboxItem');
                for (const item of items) {
                    if (item.textContent.trim().startsWith('Volkswagen')) {
                        item.click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        await asyncio.sleep(3)

        # Now dump ALL chkboxItem texts to understand structure
        all_items = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            const results = [];
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                const items = m.querySelectorAll('.chkboxItem');
                items.forEach((item, i) => {
                    // Check nesting level
                    let depth = 0;
                    let parent = item.parentElement;
                    while (parent && !parent.classList.contains('w3-modal')) {
                        if (parent.classList.contains('ParentItem') || parent.classList.contains('ChildItem') || parent.classList.contains('GrandChildItem')) {
                            depth++;
                        }
                        parent = parent.parentElement;
                    }

                    // Get direct text (not child text)
                    const directText = Array.from(item.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .filter(t => t)
                        .join(' ');

                    const fullText = item.textContent.trim().substring(0, 120);

                    // Get parent classes
                    const parentClass = item.parentElement ? item.parentElement.className : '';

                    results.push({
                        idx: i,
                        directText: directText,
                        fullText: fullText,
                        parentClass: parentClass.substring(0, 80),
                        hasCheckbox: item.querySelector("input[type='checkbox']") !== null,
                        isVisible: item.offsetHeight > 0,
                    });
                });
            }
            return results;
        }""")

        # Filter to visible items around VW
        vw_start = None
        for item in all_items:
            if 'Volkswagen' in item['fullText'] and not vw_start:
                vw_start = item['idx']

        print(f"\n  Total chkboxItem elements: {len(all_items)}")
        print(f"  VW starts at index: {vw_start}")

        if vw_start is not None:
            # Show items from VW onwards
            for item in all_items[vw_start:vw_start+30]:
                vis = "V" if item['isVisible'] else "H"
                cb = "CB" if item['hasCheckbox'] else "  "
                print(f"    [{vis}][{cb}] #{item['idx']:3d} direct='{item['directText'][:50]}' parent='{item['parentClass'][:40]}'")
                if item['fullText'] != item['directText']:
                    print(f"              full='{item['fullText'][:80]}'")

        await browser.close()
        print("\nDone!")

if __name__ == "__main__":
    asyncio.run(main())
