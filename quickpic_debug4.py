"""Debug: find model/variant DOM structure after expanding VW."""
import asyncio, random, os, functools
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

        await page.goto("https://www.quickpic.co.za/autospec", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)
        await page.locator("#SelectVehicleLabel").first.click(timeout=10000)
        await asyncio.sleep(4)

        # Get HTML around Volkswagen BEFORE clicking
        print("\n[BEFORE VW CLICK]")
        before_html = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                const items = m.querySelectorAll('.ParentItem');
                for (const item of items) {
                    if (item.textContent.includes('Volkswagen')) {
                        return item.outerHTML.substring(0, 500);
                    }
                }
            }
            return 'NOT FOUND';
        }""")
        print(f"  VW ParentItem HTML:\n{before_html}")

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
                        return;
                    }
                }
            }
        }""")
        await asyncio.sleep(4)

        # Get HTML around Volkswagen AFTER clicking
        print("\n[AFTER VW CLICK]")
        after_html = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                const items = m.querySelectorAll('.ParentItem');
                for (const item of items) {
                    if (item.textContent.includes('Volkswagen')) {
                        return item.outerHTML.substring(0, 5000);
                    }
                }
            }
            return 'NOT FOUND';
        }""")
        print(f"  VW ParentItem HTML (first 3000):\n{after_html[:3000]}")

        # Also look for any new elements that appeared
        print("\n[ALL CLASSES IN COMPARE DIALOG]")
        classes = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            const classSet = new Set();
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                const all = m.querySelectorAll('*');
                all.forEach(el => {
                    el.classList.forEach(c => classSet.add(c));
                });
            }
            return Array.from(classSet).sort();
        }""")
        print(f"  All classes: {classes}")

        # Find model-level items specifically
        print("\n[MODEL ITEMS]")
        models = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            const results = [];
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                // Look for elements whose text contains "Amarok" or "Polo"
                const all = m.querySelectorAll('*');
                for (const el of all) {
                    const t = el.textContent.trim();
                    if ((t.startsWith('Amarok') || t.startsWith('Polo (') || t.startsWith('Golf')) && t.length < 80) {
                        results.push({
                            tag: el.tagName,
                            class: el.className.substring(0, 80),
                            text: t.substring(0, 60),
                            html: el.outerHTML.substring(0, 300),
                            parentClass: el.parentElement ? el.parentElement.className.substring(0, 60) : '',
                        });
                    }
                }
            }
            return results;
        }""")
        for m in models[:15]:
            print(f"  <{m['tag']} class='{m['class']}'> parent='{m['parentClass']}'")
            print(f"    text: {m['text']}")
            print(f"    html: {m['html'][:200]}")
            print()

        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
