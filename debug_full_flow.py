"""Debug: Test full flow - search, expand brand, expand model, select variant."""
import asyncio, random, os, json
os.environ.setdefault("PYTHONUTF8", "1")
from playwright.async_api import async_playwright

BASE = os.path.dirname(__file__)
USERNAME = "dealerdigitalza@gmail.com"
PASSWORD = "LukeJason#1"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="en-ZA", timezone_id="Africa/Johannesburg",
        )
        page = await ctx.new_page()

        # Login
        print("[LOGIN]")
        await page.goto("https://www.quickpic.co.za", wait_until="domcontentloaded", timeout=90000)
        await asyncio.sleep(8)
        await page.locator("button:has-text('LOGIN')").first.click()
        await asyncio.sleep(4)
        await page.locator("input[name='email']").first.fill(USERNAME)
        await asyncio.sleep(1)
        await page.locator("input[type='password']").first.fill(PASSWORD)
        await asyncio.sleep(2)
        await page.locator("button:has-text('Login')").last.click()
        await asyncio.sleep(15)
        print(f"  URL: {page.url}")

        # Go to AutoSpec
        print("[AUTOSPEC]")
        await page.goto("https://www.quickpic.co.za/autospec", wait_until="domcontentloaded", timeout=90000)
        await asyncio.sleep(8)

        # Open compare dialog
        print("[OPEN DIALOG]")
        await page.locator("#SelectVehicleLabel").first.click(timeout=10000)
        await asyncio.sleep(5)

        # STEP 1: Type "Volkswagen" to filter
        print("\n[STEP 1] Search for Volkswagen")
        search = page.locator("input[placeholder*='Search']").first
        await search.click()
        await asyncio.sleep(1)
        await page.keyboard.type("Volkswagen", delay=100)
        await asyncio.sleep(5)
        await page.screenshot(path=os.path.join(BASE, "debug_flow_1_search.png"))

        # STEP 2: Click VW brand to expand
        print("[STEP 2] Click VW brand to expand models")
        await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                const items = m.querySelectorAll('.chkboxItem');
                for (const item of items) {
                    if (item.innerText.includes('Volkswagen')) {
                        item.click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        await asyncio.sleep(3)

        # Check what models appeared
        models_info = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                const children = m.querySelectorAll('.chkboxItemChild, .ChildItem');
                const result = [];
                for (const c of children) {
                    if (c.offsetHeight === 0) continue;
                    result.push({
                        text: c.innerText.trim().substring(0, 60),
                        className: c.className.substring(0, 80),
                        hasCheckbox: !!c.querySelector("input[type='checkbox']"),
                        childCount: c.children.length,
                        childTags: Array.from(c.children).map(ch => ch.tagName + '.' + (ch.className || '').substring(0, 30)),
                        parentClass: c.parentElement?.className?.substring(0, 60),
                        html: c.outerHTML.substring(0, 300),
                    });
                }
                return result;
            }
            return [];
        }""")
        print(f"  Models found: {len(models_info)}")
        for m in models_info[:10]:
            print(f"    '{m['text']}' class={m['className'][:40]} checkbox={m['hasCheckbox']} children={m['childCount']}")
            print(f"      childTags: {m['childTags']}")

        await page.screenshot(path=os.path.join(BASE, "debug_flow_2_brand_expanded.png"))

        # STEP 3: Click on "Golf" model to expand variants
        print("\n[STEP 3] Click Golf model to expand variants")
        clicked_model = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                const children = m.querySelectorAll('.chkboxItemChild, .ChildItem');
                for (const c of children) {
                    if (c.offsetHeight === 0) continue;
                    if (c.innerText.includes('Golf')) {
                        c.click();
                        return c.innerText.trim().substring(0, 50);
                    }
                }
            }
            return null;
        }""")
        print(f"  Clicked: {clicked_model}")
        await asyncio.sleep(3)

        # Check what appeared after model click
        after_model = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;

                // Look for ALL elements that might be variants
                const allCheckboxes = m.querySelectorAll("input[type='checkbox']");
                const cbInfo = [];
                for (const cb of allCheckboxes) {
                    const parent = cb.closest('.chkboxItem, .chkboxItemChild, .ChildItem, .VariantItem') || cb.parentElement;
                    if (!parent || parent.offsetHeight === 0) continue;
                    cbInfo.push({
                        text: parent.innerText.trim().substring(0, 80),
                        className: parent.className.substring(0, 60),
                        checked: cb.checked,
                    });
                }

                // Also look for new element types
                const selectors = ['.VariantItem', '.variant', '.LeafItem', '.chkboxItemLeaf',
                                   '.GrandchildItem', '[class*=variant]', '[class*=leaf]', '[class*=child]'];
                const newEls = [];
                for (const sel of selectors) {
                    const els = m.querySelectorAll(sel);
                    for (const el of els) {
                        if (el.offsetHeight === 0) continue;
                        newEls.push({
                            selector: sel,
                            text: el.innerText.trim().substring(0, 80),
                            className: el.className.substring(0, 60),
                            hasCheckbox: !!el.querySelector("input[type='checkbox']"),
                        });
                    }
                }

                // Dump all visible items in the tree area
                const allItems = m.querySelectorAll('.chkboxItem, .chkboxItemChild, .ChildItem, .ParentItem');
                const visItems = [];
                for (const item of allItems) {
                    if (item.offsetHeight === 0) continue;
                    visItems.push({
                        text: item.innerText.trim().substring(0, 80),
                        class: item.className.substring(0, 60),
                        hasCheckbox: !!item.querySelector("input[type='checkbox']"),
                    });
                }

                return {
                    checkboxes: cbInfo,
                    newElements: newEls.slice(0, 15),
                    allVisibleItems: visItems,
                };
            }
            return null;
        }""")

        if after_model:
            print(f"  Checkboxes: {len(after_model['checkboxes'])}")
            for cb in after_model['checkboxes'][:10]:
                print(f"    [{('X' if cb['checked'] else ' ')}] {cb['text']} ({cb['className'][:30]})")
            print(f"  New elements: {len(after_model['newElements'])}")
            for ne in after_model['newElements'][:10]:
                print(f"    {ne['selector']}: '{ne['text']}' checkbox={ne['hasCheckbox']}")
            print(f"  All visible items: {len(after_model['allVisibleItems'])}")
            for vi in after_model['allVisibleItems'][:15]:
                print(f"    [{('CB' if vi['hasCheckbox'] else '  ')}] {vi['class'][:25]} '{vi['text']}'")

        await page.screenshot(path=os.path.join(BASE, "debug_flow_3_model_expanded.png"))

        # STEP 4: If no checkboxes appeared, try using the expand-button
        if after_model and len(after_model['checkboxes']) == 0:
            print("\n[STEP 4] Try expand-button for Golf")
            # Check if there are expand buttons
            expand_info = await page.evaluate("""() => {
                const modals = document.querySelectorAll('.w3-modal');
                for (const m of modals) {
                    if (!m.innerText.includes('Compare Vehicles')) continue;
                    const buttons = m.querySelectorAll('.expand-button, button[class*=expand]');
                    return {
                        count: buttons.length,
                        info: Array.from(buttons).map(b => ({
                            text: b.innerText.trim().substring(0, 30),
                            visible: b.offsetHeight > 0,
                            parent: b.parentElement?.innerText?.trim()?.substring(0, 50),
                            html: b.outerHTML.substring(0, 200),
                        }))
                    };
                }
                return null;
            }""")
            print(f"  Expand buttons: {expand_info}")

        # STEP 5: Try searching more specifically for a variant
        print("\n[STEP 5] Clear and search for specific variant")
        await search.click(click_count=3)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Backspace")
        await asyncio.sleep(3)

        # Try typing a full variant
        await search.click()
        await asyncio.sleep(1)
        await page.keyboard.type("Volkswagen Golf R", delay=100)
        await asyncio.sleep(5)

        # Check what's visible now
        variant_search = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;
                const items = m.querySelectorAll('.chkboxItem, .chkboxItemChild, .ChildItem, .ParentItem');
                const visible = [];
                for (const item of items) {
                    if (item.offsetHeight === 0) continue;
                    visible.push({
                        text: item.innerText.trim().substring(0, 80),
                        class: item.className.substring(0, 50),
                        hasCheckbox: !!item.querySelector("input[type='checkbox']"),
                    });
                }
                // Also check for any checkboxes
                const cbs = m.querySelectorAll("input[type='checkbox']");
                const visCbs = [];
                for (const cb of cbs) {
                    const p = cb.parentElement;
                    if (p && p.offsetHeight > 0) {
                        visCbs.push({
                            text: p.innerText.trim().substring(0, 80),
                            class: p.className.substring(0, 50),
                        });
                    }
                }
                return {items: visible, checkboxes: visCbs};
            }
            return null;
        }""")
        print(f"  After 'Volkswagen Golf R' search:")
        if variant_search:
            print(f"    Items: {len(variant_search['items'])}")
            for it in variant_search['items'][:10]:
                print(f"      [{('CB' if it['hasCheckbox'] else '  ')}] {it['class'][:25]} '{it['text']}'")
            print(f"    Checkboxes: {len(variant_search['checkboxes'])}")
            for cb in variant_search['checkboxes'][:10]:
                print(f"      {cb['text']}")
        await page.screenshot(path=os.path.join(BASE, "debug_flow_5_variant_search.png"))

        # STEP 6: Dump the complete tree HTML when expanded
        print("\n[STEP 6] Complete tree dump after expand")
        # First clear search and start fresh
        await search.click(click_count=3)
        await page.keyboard.press("Backspace")
        await asyncio.sleep(3)

        # Type VW to filter, click brand, click model
        await search.click()
        await page.keyboard.type("Volkswagen", delay=80)
        await asyncio.sleep(4)

        # Click VW brand
        await page.evaluate("""() => {
            const m = Array.from(document.querySelectorAll('.w3-modal')).find(m => m.innerText.includes('Compare'));
            if (!m) return;
            const items = m.querySelectorAll('.chkboxItem');
            for (const item of items) {
                if (item.innerText.includes('Volkswagen')) { item.click(); return; }
            }
        }""")
        await asyncio.sleep(3)

        # Click Golf model (use the chkboxItemChild)
        await page.evaluate("""() => {
            const m = Array.from(document.querySelectorAll('.w3-modal')).find(m => m.innerText.includes('Compare'));
            if (!m) return;
            const items = m.querySelectorAll('.chkboxItemChild');
            for (const item of items) {
                if (item.innerText.includes('Golf')) { item.click(); return; }
            }
        }""")
        await asyncio.sleep(3)

        # Dump FULL tree area HTML
        tree_html = await page.evaluate("""() => {
            const m = Array.from(document.querySelectorAll('.w3-modal')).find(m => m.innerText.includes('Compare'));
            if (!m) return '';
            const listCon = m.querySelector('.list-con');
            if (listCon) return listCon.innerHTML.substring(0, 15000);
            return m.innerHTML.substring(0, 15000);
        }""")
        with open(os.path.join(BASE, "debug_tree_full_html.txt"), "w", encoding="utf-8") as f:
            f.write(tree_html)
        print(f"  Full tree HTML saved ({len(tree_html)} chars)")
        await page.screenshot(path=os.path.join(BASE, "debug_flow_6_full_expand.png"))

        print("\n[DONE]")
        await asyncio.sleep(3)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
