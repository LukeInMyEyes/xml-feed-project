"""Debug QuickPic AutoSpec dialog — tree navigation approach."""
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
        await page.locator("input[name='email']").first.fill(USERNAME)
        await asyncio.sleep(1)
        await page.locator("input[type='password']").first.fill(PASSWORD)
        await asyncio.sleep(1)
        await page.locator("button:has-text('Login')").last.click()
        await asyncio.sleep(random.uniform(8, 12))
        print(f"  Logged in: {page.url}")

        # Go to AutoSpec
        print("\n[AUTOSPEC]")
        await page.goto("https://www.quickpic.co.za/autospec", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(random.uniform(4, 7))

        # Click + Vehicle to open dialog
        print("\n[OPEN DIALOG]")
        try:
            await page.locator("#SelectVehicleLabel").first.click(timeout=10000)
        except:
            await page.evaluate("document.getElementById('SelectVehicleLabel')?.click()")
        await asyncio.sleep(random.uniform(3, 5))

        # Dump the ENTIRE dialog structure
        print("\n[DUMP DIALOG STRUCTURE]")
        dialog_info = await page.evaluate("""() => {
            // Find all modals
            const modals = document.querySelectorAll('.w3-modal');
            const results = [];
            modals.forEach((m, i) => {
                const display = getComputedStyle(m).display;
                results.push({
                    index: i,
                    display: display,
                    classes: m.className,
                    textPreview: m.innerText.substring(0, 200),
                    hasSearch: m.querySelector("input[placeholder*='Search']") !== null,
                    checkboxCount: m.querySelectorAll("input[type='checkbox']").length,
                    width: m.offsetWidth,
                    height: m.offsetHeight
                });
            });
            return results;
        }""")

        for m in dialog_info:
            print(f"  Modal {m['index']}: display={m['display']}, {m['width']}x{m['height']}")
            print(f"    classes: {m['classes']}")
            print(f"    hasSearch: {m['hasSearch']}, checkboxes: {m['checkboxCount']}")
            print(f"    text: {m['textPreview'][:100]}")
            print()

        # Find the vehicle compare dialog specifically
        compare_info = await page.evaluate("""() => {
            // Look for the dialog containing "Compare Vehicles"
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (m.innerText.includes('Compare Vehicles')) {
                    // Get the structure of the brand/model tree
                    // Look for clickable brand items
                    const items = m.querySelectorAll('[style*="cursor"]');
                    const clickableTexts = [];
                    items.forEach(el => {
                        const t = el.innerText.trim();
                        if (t && t.length < 100) clickableTexts.push(t);
                    });

                    // Look for elements with expand/collapse chevrons
                    const chevrons = m.querySelectorAll('.mdi-chevron-down, .mdi-chevron-right, [class*="chevron"], [class*="expand"]');

                    // Get all divs that look like tree items
                    const allDivs = m.querySelectorAll('div');
                    const treeItems = [];
                    allDivs.forEach(d => {
                        const t = d.innerText.trim();
                        if (t.match(/^[A-Z].*\\(\\d+\\)$/) && t.length < 60) {
                            treeItems.push({
                                text: t,
                                tag: d.tagName,
                                class: d.className.substring(0, 80),
                                clickable: d.style.cursor === 'pointer',
                                html: d.outerHTML.substring(0, 300)
                            });
                        }
                    });

                    return {
                        found: true,
                        clickableCount: clickableTexts.length,
                        clickableTexts: clickableTexts.slice(0, 20),
                        chevronCount: chevrons.length,
                        treeItemCount: treeItems.length,
                        treeItems: treeItems.slice(0, 15)
                    };
                }
            }
            return {found: false};
        }""")

        print(f"\n[COMPARE DIALOG]")
        if compare_info['found']:
            print(f"  Clickable elements: {compare_info['clickableCount']}")
            print(f"  Chevrons: {compare_info['chevronCount']}")
            print(f"  Tree items: {compare_info['treeItemCount']}")
            print(f"\n  Tree items:")
            for item in compare_info.get('treeItems', []):
                print(f"    {item['text']}")
                print(f"      class: {item['class']}")
                print(f"      clickable: {item['clickable']}")
                print(f"      html: {item['html'][:200]}")
                print()

            print(f"\n  Clickable texts: {compare_info.get('clickableTexts', [])[:15]}")
        else:
            print("  NOT FOUND!")

        # Try clicking on Volkswagen in the tree
        print("\n[CLICK VOLKSWAGEN]")
        vw_clicked = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                const allEls = m.querySelectorAll('*');
                for (const el of allEls) {
                    // Direct text match (not child text)
                    const directText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join('');
                    if (directText.includes('Volkswagen') || el.textContent.trim().startsWith('Volkswagen (')) {
                        if (el.tagName === 'DIV' || el.tagName === 'SPAN' || el.tagName === 'A' || el.tagName === 'BUTTON') {
                            el.click();
                            return {clicked: true, tag: el.tagName, class: el.className, text: el.textContent.trim().substring(0, 80)};
                        }
                    }
                }
            }
            return {clicked: false};
        }""")
        print(f"  Result: {vw_clicked}")
        await asyncio.sleep(random.uniform(3, 5))
        await page.screenshot(path=os.path.join(SCREENSHOT_DIR, "debug2_after_vw_click.png"))

        # Check what expanded
        expanded_info = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                // Check if Volkswagen models are now visible
                const hasPoloBadge = m.innerText.includes('Polo (');
                const hasGolf = m.innerText.includes('Golf (');
                const fullText = m.innerText;

                // Find all visible text after Volkswagen
                const vwIdx = fullText.indexOf('Volkswagen');
                const afterVw = vwIdx >= 0 ? fullText.substring(vwIdx, vwIdx + 500) : '';

                // Count checkboxes now
                const cbs = m.querySelectorAll("input[type='checkbox']");

                return {
                    hasPoloModel: hasPoloBadge,
                    hasGolf: hasGolf,
                    checkboxCount: cbs.length,
                    afterVw: afterVw
                };
            }
            return null;
        }""")
        print(f"\n  After VW click:")
        print(f"    Has Polo model: {expanded_info and expanded_info.get('hasPoloModel')}")
        print(f"    Has Golf: {expanded_info and expanded_info.get('hasGolf')}")
        print(f"    Checkboxes: {expanded_info and expanded_info.get('checkboxCount')}")
        if expanded_info and expanded_info.get('afterVw'):
            print(f"    Text after VW:\n{expanded_info['afterVw'][:400]}")

        # If models appeared, try clicking Polo
        if expanded_info and expanded_info.get('hasPoloModel'):
            print("\n[CLICK POLO]")
            polo_clicked = await page.evaluate("""() => {
                const modals = document.querySelectorAll('.w3-modal');
                for (const m of modals) {
                    if (!m.innerText.includes('Compare Vehicles')) continue;
                    const allEls = m.querySelectorAll('*');
                    for (const el of allEls) {
                        const t = el.textContent.trim();
                        if (t.match(/^Polo \\(\\d+\\)$/) || t.match(/^Polo\\s*\\(\\d+\\)/)) {
                            el.click();
                            return {clicked: true, text: t, tag: el.tagName};
                        }
                    }
                }
                return {clicked: false};
            }""")
            print(f"  Result: {polo_clicked}")
            await asyncio.sleep(random.uniform(3, 5))
            await page.screenshot(path=os.path.join(SCREENSHOT_DIR, "debug2_after_polo_click.png"))

            # Check for variants
            variant_info = await page.evaluate("""() => {
                const modals = document.querySelectorAll('.w3-modal');
                for (const m of modals) {
                    if (!m.innerText.includes('Compare Vehicles')) continue;
                    const fullText = m.innerText;
                    const poloIdx = fullText.indexOf('Polo (');
                    const afterPolo = poloIdx >= 0 ? fullText.substring(poloIdx, poloIdx + 1000) : '';
                    const cbs = m.querySelectorAll("input[type='checkbox']");

                    // Get checkbox parent texts
                    const cbTexts = [];
                    cbs.forEach(cb => {
                        const parent = cb.closest('div') || cb.parentElement;
                        if (parent) cbTexts.push(parent.innerText.trim().substring(0, 100));
                    });

                    return {
                        checkboxCount: cbs.length,
                        afterPolo: afterPolo,
                        cbTexts: cbTexts.slice(0, 10)
                    };
                }
                return null;
            }""")
            print(f"\n  After Polo click:")
            print(f"    Checkboxes: {variant_info and variant_info.get('checkboxCount')}")
            if variant_info and variant_info.get('afterPolo'):
                print(f"    Text after Polo:\n{variant_info['afterPolo'][:600]}")
            if variant_info and variant_info.get('cbTexts'):
                print(f"\n    Checkbox texts:")
                for ct in variant_info['cbTexts']:
                    print(f"      {ct}")

        await browser.close()
        print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
