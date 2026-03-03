"""Debug: Test different methods to interact with QuickPic Blazor search input."""
import asyncio, random, os, json, sys
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

        # 0) Dump dialog structure
        print("\n[STEP 0] Dump dialog HTML structure")
        structure = await page.evaluate("""() => {
            const modals = document.querySelectorAll('.w3-modal');
            for (const m of modals) {
                if (!m.innerText.includes('Compare Vehicles')) continue;

                // Find all inputs
                const inputs = m.querySelectorAll('input');
                const inputInfo = Array.from(inputs).map(i => ({
                    type: i.type, placeholder: i.placeholder,
                    name: i.name, id: i.id,
                    classes: i.className.substring(0, 100),
                    value: i.value,
                    visible: i.offsetHeight > 0,
                }));

                // Find tree structure - look for expand/collapse elements
                const treeInfo = [];
                const items = m.querySelectorAll('.chkboxItem');
                for (let i = 0; i < Math.min(items.length, 5); i++) {
                    const el = items[i];
                    treeInfo.push({
                        text: el.innerText.trim().substring(0, 60),
                        tagName: el.tagName,
                        className: el.className.substring(0, 100),
                        children: el.children.length,
                        childTags: Array.from(el.children).map(c => c.tagName + '.' + c.className.substring(0, 30)),
                        parentTag: el.parentElement?.tagName,
                        parentClass: el.parentElement?.className?.substring(0, 100),
                        grandparentTag: el.parentElement?.parentElement?.tagName,
                        grandparentClass: el.parentElement?.parentElement?.className?.substring(0, 60),
                        html: el.outerHTML.substring(0, 400),
                    });
                }

                // Get overall modal structure (just the container class hierarchy)
                const modalHTML = m.innerHTML.substring(0, 5000);

                return { inputs: inputInfo, tree: treeInfo, modalHTMLpreview: modalHTML };
            }
            return null;
        }""")

        if structure:
            print(f"  Inputs found: {len(structure['inputs'])}")
            for inp in structure['inputs']:
                print(f"    type={inp['type']} placeholder='{inp['placeholder']}' visible={inp['visible']} id='{inp['id']}'")
            print(f"  Tree items (first 5): {len(structure['tree'])}")
            for t in structure['tree']:
                print(f"    '{t['text']}' children={t['children']} parent={t['parentTag']}.{t['parentClass'][:40]}")
                print(f"      childTags: {t['childTags'][:3]}")
            # Save full HTML for analysis
            with open(os.path.join(BASE, "debug_dialog_structure.txt"), "w", encoding="utf-8") as f:
                f.write(json.dumps(structure, indent=2, ensure_ascii=False))
                f.write("\n\n--- MODAL HTML ---\n")
                f.write(structure.get('modalHTMLpreview', ''))
            print("  -> Saved to debug_dialog_structure.txt")

        await page.screenshot(path=os.path.join(BASE, "debug_0_initial.png"), full_page=True)

        # Find the search input
        search = page.locator("input[placeholder*='Search']").first
        search_count = await page.locator("input[placeholder*='Search']").count()
        print(f"\n  Search inputs matching placeholder='Search': {search_count}")

        if search_count == 0:
            # Try other selectors
            all_inputs = await page.locator("input").count()
            print(f"  Total inputs on page: {all_inputs}")
            # Try finding by type=text or type=search
            for sel in ["input[type='search']", "input[type='text']", "input.search", "input[placeholder]"]:
                c = await page.locator(sel).count()
                if c > 0:
                    print(f"  {sel}: {c} matches")

        # =====================================================
        # APPROACH 1: keyboard.type() with proper focus
        # =====================================================
        print("\n[APPROACH 1] keyboard.type() with delay=100")
        try:
            await search.click()
            await asyncio.sleep(1)
            await page.keyboard.type("Volkswagen", delay=100)
            await asyncio.sleep(8)  # Long wait for Blazor debounce

            count1 = await page.evaluate("""() => {
                const modals = document.querySelectorAll('.w3-modal');
                for (const m of modals) {
                    if (!m.innerText.includes('Compare Vehicles')) continue;
                    const items = m.querySelectorAll('.chkboxItem');
                    const visible = Array.from(items).filter(el => el.offsetHeight > 0);
                    return {total: items.length, visible: visible.length,
                            texts: visible.slice(0, 8).map(el => el.innerText.trim().substring(0, 50))};
                }
                return null;
            }""")
            print(f"  Result: {count1}")
            await page.screenshot(path=os.path.join(BASE, "debug_1_keyboard_type.png"))
        except Exception as e:
            print(f"  Error: {e}")

        # Clear
        await search.click(click_count=3)
        await page.keyboard.press("Backspace")
        await asyncio.sleep(3)

        # =====================================================
        # APPROACH 2: Native value setter + InputEvent
        # =====================================================
        print("\n[APPROACH 2] Native setter + InputEvent dispatch")
        try:
            result2 = await page.evaluate("""() => {
                const input = document.querySelector("input[placeholder*='Search']");
                if (!input) return {error: 'no input'};
                input.focus();
                // Use native value setter to bypass any framework wrapping
                const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                nativeSetter.call(input, 'Volkswagen');
                // Dispatch events that Blazor should pick up
                input.dispatchEvent(new Event('focus', {bubbles: true}));
                input.dispatchEvent(new InputEvent('input', {bubbles: true, data: 'Volkswagen', inputType: 'insertText'}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
                input.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true, key: 'n'}));
                return {value: input.value, dispatched: true};
            }""")
            print(f"  Dispatch result: {result2}")
            await asyncio.sleep(8)

            count2 = await page.evaluate("""() => {
                const modals = document.querySelectorAll('.w3-modal');
                for (const m of modals) {
                    if (!m.innerText.includes('Compare Vehicles')) continue;
                    const items = m.querySelectorAll('.chkboxItem');
                    const visible = Array.from(items).filter(el => el.offsetHeight > 0);
                    return {total: items.length, visible: visible.length,
                            texts: visible.slice(0, 8).map(el => el.innerText.trim().substring(0, 50))};
                }
                return null;
            }""")
            print(f"  Result: {count2}")
            await page.screenshot(path=os.path.join(BASE, "debug_2_native_setter.png"))
        except Exception as e:
            print(f"  Error: {e}")

        # Clear
        await search.click(click_count=3)
        await page.keyboard.press("Backspace")
        await asyncio.sleep(3)

        # =====================================================
        # APPROACH 3: Char-by-char via evaluate (simulate real keystrokes)
        # =====================================================
        print("\n[APPROACH 3] Char-by-char via JS dispatchEvent")
        try:
            await page.evaluate("""() => {
                const input = document.querySelector("input[placeholder*='Search']");
                if (!input) return;
                input.focus();
                const text = 'Volkswagen';
                const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;

                for (let i = 0; i < text.length; i++) {
                    const char = text[i];
                    const currentVal = text.substring(0, i + 1);

                    // Fire keydown
                    input.dispatchEvent(new KeyboardEvent('keydown', {key: char, code: 'Key' + char.toUpperCase(), bubbles: true}));
                    // Set value incrementally
                    nativeSetter.call(input, currentVal);
                    // Fire input event
                    input.dispatchEvent(new InputEvent('input', {bubbles: true, data: char, inputType: 'insertText'}));
                    // Fire keyup
                    input.dispatchEvent(new KeyboardEvent('keyup', {key: char, code: 'Key' + char.toUpperCase(), bubbles: true}));
                }
            }""")
            await asyncio.sleep(8)

            count3 = await page.evaluate("""() => {
                const modals = document.querySelectorAll('.w3-modal');
                for (const m of modals) {
                    if (!m.innerText.includes('Compare Vehicles')) continue;
                    const items = m.querySelectorAll('.chkboxItem');
                    const visible = Array.from(items).filter(el => el.offsetHeight > 0);
                    return {total: items.length, visible: visible.length,
                            texts: visible.slice(0, 8).map(el => el.innerText.trim().substring(0, 50))};
                }
                return null;
            }""")
            print(f"  Result: {count3}")
            await page.screenshot(path=os.path.join(BASE, "debug_3_charbychar.png"))
        except Exception as e:
            print(f"  Error: {e}")

        # Clear
        await search.click(click_count=3)
        await page.keyboard.press("Backspace")
        await asyncio.sleep(3)

        # =====================================================
        # APPROACH 4: Tree navigation - click brand expand arrow
        # =====================================================
        print("\n[APPROACH 4] Tree navigation - click Volkswagen to expand")
        try:
            # First, dump the detailed HTML of one brand item
            brand_html = await page.evaluate("""() => {
                const modals = document.querySelectorAll('.w3-modal');
                for (const m of modals) {
                    if (!m.innerText.includes('Compare Vehicles')) continue;
                    const items = m.querySelectorAll('.chkboxItem');
                    for (const item of items) {
                        if (item.innerText.includes('Volkswagen')) {
                            // Get parent and siblings structure
                            const parent = item.parentElement;
                            const gp = parent?.parentElement;
                            return {
                                itemHTML: item.outerHTML.substring(0, 500),
                                parentHTML: parent?.outerHTML?.substring(0, 800),
                                parentTag: parent?.tagName,
                                parentClass: parent?.className?.substring(0, 100),
                                gpTag: gp?.tagName,
                                gpClass: gp?.className?.substring(0, 100),
                                siblingCount: parent?.children?.length,
                                siblingTags: Array.from(parent?.children || []).map(c =>
                                    c.tagName + '.' + (c.className || '').substring(0, 40) +
                                    (c.offsetHeight === 0 ? ' [hidden]' : '') +
                                    ' text:' + c.innerText?.trim()?.substring(0, 30)
                                ),
                            };
                        }
                    }
                    return null;
                }
                return null;
            }""")
            print(f"  VW brand HTML structure:")
            if brand_html:
                for k, v in brand_html.items():
                    if k != 'parentHTML':
                        print(f"    {k}: {str(v)[:200]}")
                with open(os.path.join(BASE, "debug_vw_tree_item.txt"), "w", encoding="utf-8") as f:
                    json.dump(brand_html, f, indent=2, ensure_ascii=False)

            # Click on Volkswagen brand item
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
            await asyncio.sleep(5)

            # Check what changed
            after_click = await page.evaluate("""() => {
                const modals = document.querySelectorAll('.w3-modal');
                for (const m of modals) {
                    if (!m.innerText.includes('Compare Vehicles')) continue;
                    const items = m.querySelectorAll('.chkboxItem');
                    const visible = Array.from(items).filter(el => el.offsetHeight > 0);

                    // Also check for any new elements that appeared
                    const allVisible = m.querySelectorAll('*');
                    let newElements = [];
                    for (const el of allVisible) {
                        if (el.offsetHeight === 0) continue;
                        const text = el.innerText?.trim();
                        if (!text || text.length > 80) continue;
                        // Look for model-like items (Polo, Golf, etc.)
                        if (['Polo', 'Golf', 'Tiguan', 'T-Roc', 'Amarok'].some(m => text.includes(m))) {
                            newElements.push({
                                tag: el.tagName,
                                class: el.className?.substring(0, 60),
                                text: text.substring(0, 60),
                                hasCheckbox: !!el.querySelector("input[type='checkbox']"),
                            });
                        }
                    }

                    // Check if any checkboxes appeared
                    const checkboxes = m.querySelectorAll("input[type='checkbox']");
                    const visCheckboxes = Array.from(checkboxes).filter(cb => {
                        const p = cb.closest('.chkboxItem') || cb.parentElement;
                        return p && p.offsetHeight > 0;
                    });

                    return {
                        visibleItems: visible.length,
                        texts: visible.slice(0, 10).map(el => el.innerText.trim().substring(0, 50)),
                        modelElements: newElements.slice(0, 10),
                        checkboxCount: visCheckboxes.length,
                        checkboxTexts: visCheckboxes.slice(0, 5).map(cb => {
                            const p = cb.closest('.chkboxItem') || cb.parentElement;
                            return p?.innerText?.trim()?.substring(0, 50);
                        }),
                    };
                }
                return null;
            }""")
            print(f"  After brand click:")
            if after_click:
                print(f"    Visible tree items: {after_click['visibleItems']}")
                print(f"    Texts: {after_click['texts'][:5]}")
                print(f"    Model elements found: {len(after_click['modelElements'])}")
                for me in after_click['modelElements'][:5]:
                    print(f"      {me['tag']}.{me['class'][:30]} '{me['text']}' checkbox={me['hasCheckbox']}")
                print(f"    Checkboxes visible: {after_click['checkboxCount']}")
                for ct in after_click['checkboxTexts'][:5]:
                    print(f"      checkbox: {ct}")

            await page.screenshot(path=os.path.join(BASE, "debug_4_tree_click.png"))

            # Try double-clicking to expand
            print("\n  Trying double-click on VW...")
            await page.evaluate("""() => {
                const modals = document.querySelectorAll('.w3-modal');
                for (const m of modals) {
                    if (!m.innerText.includes('Compare Vehicles')) continue;
                    const items = m.querySelectorAll('.chkboxItem');
                    for (const item of items) {
                        if (item.innerText.includes('Volkswagen')) {
                            item.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
                            return true;
                        }
                    }
                }
                return false;
            }""")
            await asyncio.sleep(5)

            after_dblclick = await page.evaluate("""() => {
                const modals = document.querySelectorAll('.w3-modal');
                for (const m of modals) {
                    if (!m.innerText.includes('Compare Vehicles')) continue;
                    const items = m.querySelectorAll('.chkboxItem');
                    const visible = Array.from(items).filter(el => el.offsetHeight > 0);
                    return {
                        count: visible.length,
                        texts: visible.slice(0, 15).map(el => el.innerText.trim().substring(0, 50))
                    };
                }
                return null;
            }""")
            print(f"  After double-click: {after_dblclick}")
            await page.screenshot(path=os.path.join(BASE, "debug_4b_tree_dblclick.png"))

        except Exception as e:
            print(f"  Error: {e}")
            import traceback; traceback.print_exc()

        # =====================================================
        # APPROACH 5: Intercept Blazor events - check what Blazor version
        # =====================================================
        print("\n[APPROACH 5] Check Blazor internals")
        try:
            blazor_info = await page.evaluate("""() => {
                return {
                    hasBlazor: typeof Blazor !== 'undefined',
                    hasDotNet: typeof DotNet !== 'undefined',
                    blazorKeys: typeof Blazor !== 'undefined' ? Object.keys(Blazor).slice(0, 20) : [],
                    // Check event listeners on the search input
                    inputEl: (() => {
                        const input = document.querySelector("input[placeholder*='Search']");
                        if (!input) return null;
                        // Check Blazor event attributes
                        const attrs = {};
                        for (const attr of input.attributes) {
                            attrs[attr.name] = attr.value.substring(0, 50);
                        }
                        return attrs;
                    })(),
                };
            }""")
            print(f"  Blazor info: hasBlazor={blazor_info.get('hasBlazor')}, hasDotNet={blazor_info.get('hasDotNet')}")
            print(f"  Blazor keys: {blazor_info.get('blazorKeys', [])[:10]}")
            print(f"  Input attrs: {blazor_info.get('inputEl')}")
        except Exception as e:
            print(f"  Error: {e}")

        print("\n[DONE] Check debug_*.png screenshots")
        await asyncio.sleep(3)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
