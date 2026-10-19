import os
import re
import asyncio
from typing import Optional, Dict, Any, List
from playwright.async_api import Page
from backend.app.config.settings import settings
from backend.app.core.logging import logger
from backend.app.core.exceptions import BrowserException
from backend.app.core.event_stream import event_stream


class BrowserActions:
    """Executes safe, visible browser actions on interactive DOM elements with visual highlighting."""

    _JS_SEARCH_AND_CLICK = """
    ([sel, val]) => {
        const tgt = val.toLowerCase().trim();
        const tgtDigits = tgt.replace(/\\D/g, '');
        const els = Array.from(document.querySelectorAll(sel));
        const visible = els.filter(el => {
            const style = window.getComputedStyle(el);
            return style && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0);
        });
        if (visible.length === 0) return { matched: false, count: 0 };

        // Priority 1: Exact text match
        for (const el of visible) {
            const txt = (el.innerText || el.textContent || '').toLowerCase().trim();
            if (txt === tgt) {
                el.scrollIntoView({ block: 'nearest' });
                el.click();
                return { matched: true, text: txt, count: visible.length };
            }
        }
        // Priority 2: Substring / contains match
        for (const el of visible) {
            const txt = (el.innerText || el.textContent || '').toLowerCase().trim();
            if (txt.length >= 2 && (txt.includes(tgt) || tgt.includes(txt))) {
                el.scrollIntoView({ block: 'nearest' });
                el.click();
                return { matched: true, text: txt, count: visible.length };
            }
        }
        // Priority 3: Country dial code match (e.g. +91, 91, India)
        if (tgtDigits && (tgt.startsWith('+') || tgtDigits === '91' || tgt.includes('india'))) {
            for (const el of visible) {
                const txt = (el.innerText || el.textContent || '').toLowerCase().trim();
                const digits = txt.replace(/\\D/g, '');
                if (digits === tgtDigits || txt.includes('+91') || txt.includes('india')) {
                    el.scrollIntoView({ block: 'nearest' });
                    el.click();
                    return { matched: true, text: txt, count: visible.length };
                }
            }
        }
        // Priority 4: Fallback to 'Other' option
        for (const el of visible) {
            const txt = (el.innerText || el.textContent || '').toLowerCase().trim();
            if (txt === 'other' || txt.startsWith('other') || txt.includes('not listed') || txt.includes('unlisted')) {
                el.scrollIntoView({ block: 'nearest' });
                el.click();
                return { matched: true, text: txt, isOther: true, count: visible.length };
            }
        }
        return { matched: false, count: visible.length };
    }
    """

    @staticmethod
    def _selector(data_jp_id_or_selector: str) -> str:
        """Convert data-jp-id identifier or raw selector into valid Playwright selector."""
        if data_jp_id_or_selector.startswith("field_") or data_jp_id_or_selector.startswith("jp_"):
            return f'[data-jp-id="{data_jp_id_or_selector}"]'
        return data_jp_id_or_selector

    @classmethod
    async def dismiss_cookie_and_overlay_banners(cls, page: Page):
        """Automatically dismiss cookie consent banners (OneTrust, Cookiebot, etc.) and remove dark overlay backdrops."""
        try:
            await page.add_style_tag(content="""
                #onetrust-consent-sdk, #onetrust-pc-sdk, .ot-pc-container, .onetrust-pc-dark-filter,
                [id*="onetrust"], [class*="onetrust"], .ot-modal, #ot-pc-content, [class*="ot-pc"],
                .cookie-banner, #cookie-banner, .ot-fade-in {
                    display: none !important;
                    pointer-events: none !important;
                    visibility: hidden !important;
                    z-index: -999999 !important;
                }
            """)
            ot_btn = page.locator('#onetrust-accept-btn-handler, #accept-recommended-btn-handler, button[id*="accept-cookie"]').first
            if await ot_btn.count() > 0:
                try:
                    await ot_btn.click(timeout=1000, force=True)
                except Exception:
                    pass
        except Exception:
            pass

    @classmethod
    async def _find_element(cls, page: Page, selector: str):
        """Locate element and its execution context (Page or child Frame)."""
        await cls.dismiss_cookie_and_overlay_banners(page)
        # Check main page
        try:
            loc = page.locator(selector).first
            has_element = True
            try:
                cnt = await loc.count()
                if isinstance(cnt, (int, float)) and cnt == 0:
                    has_element = False
            except Exception:
                pass

            if has_element:
                return loc, page
        except Exception:
            pass

        # Check child frames
        for frame in getattr(page, "frames", []):
            if frame == getattr(page, "main_frame", None):
                continue
            try:
                floc = frame.locator(selector).first
                cnt = await floc.count()
                if not isinstance(cnt, (int, float)) or cnt > 0:
                    return floc, frame
            except Exception:
                continue

        return page.locator(selector).first, page

    @classmethod
    async def _scroll_if_needed(cls, element):
        """Scroll element into view smoothly ONLY if it is not already comfortably visible in the viewport."""
        try:
            is_in_viewport = await element.evaluate("""
                el => {
                    const rect = el.getBoundingClientRect();
                    // Don't scroll invisible/zero-sized elements
                    if (rect.width === 0 && rect.height === 0) return true;
                    const windowHeight = window.innerHeight || document.documentElement.clientHeight;
                    const windowWidth = window.innerWidth || document.documentElement.clientWidth;
                    return (
                        rect.top >= 20 &&
                        rect.bottom <= (windowHeight - 20) &&
                        rect.left >= 0 &&
                        rect.right <= windowWidth
                    );
                }
            """)
            if not is_in_viewport:
                await element.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })")
        except Exception:
            try:
                await element.scroll_into_view_if_needed()
            except Exception:
                pass

    @classmethod
    async def highlight_element(cls, context, selector: str, color: str = "#2563eb", status_text: str = ""):
        """Highlight active element visually in the visible browser window (main page or iframe)."""
        if not settings.BROWSER_VISUAL_HIGHLIGHT:
            return
        try:
            js = """
            ([sel, col, txt]) => {
                const el = document.querySelector(sel);
                if (!el) return;
                el.style.transition = 'all 0.25s ease';
                el.style.outline = `3px solid ${col}`;
                el.style.boxShadow = `0 0 12px ${col}88`;

                // Show or update in-page floating banner
                let badge = document.getElementById('jp-action-banner');
                if (!badge) {
                    badge = document.createElement('div');
                    badge.id = 'jp-action-banner';
                    badge.style.position = 'fixed';
                    badge.style.bottom = '16px';
                    badge.style.right = '16px';
                    badge.style.backgroundColor = '#0f172a';
                    badge.style.color = '#ffffff';
                    badge.style.padding = '8px 16px';
                    badge.style.borderRadius = '8px';
                    badge.style.fontSize = '13px';
                    badge.style.fontFamily = 'monospace';
                    badge.style.zIndex = '999999';
                    badge.style.boxShadow = '0 4px 14px rgba(0,0,0,0.3)';
                    badge.style.pointerEvents = 'none';
                    badge.style.display = 'flex';
                    badge.style.alignItems = 'center';
                    badge.style.gap = '8px';
                    document.body.appendChild(badge);
                }
                badge.innerHTML = `✈️ <strong>JobPilot Live:</strong> ${txt || 'Processing element...'}`;
                badge.style.borderLeft = `4px solid ${col}`;
            }
            """
            await context.evaluate(js, [selector, color, status_text])
        except Exception:
            pass

    @classmethod
    async def mark_success(cls, context, selector: str, message: str = "Field filled"):
        """Mark element green after successful interaction."""
        if not settings.BROWSER_VISUAL_HIGHLIGHT:
            return
        try:
            await cls.highlight_element(context, selector, color="#10b981", status_text=message)
            if hasattr(context, "wait_for_timeout"):
                await context.wait_for_timeout(100)
            elif hasattr(context, "page") and hasattr(context.page, "wait_for_timeout"):
                await context.page.wait_for_timeout(100)
        except Exception:
            pass

    @classmethod
    async def fill_text(cls, page: Page, target: str, value: str, field_label: str = "", session_id: str = ""):
        """Fill text input or textarea with visible highlighting and typing animation."""
        selector = cls._selector(target)
        display_label = field_label or target
        logger.info(f"Action: Fill text at '{selector}' with value '{value}'")

        if session_id:
            await event_stream.log_action(
                session_id,
                f"Filling field '{display_label}' with: \"{value}\"",
                level="info",
                action="fill",
                field_id=target,
                field_label=display_label,
                value=value
            )

        try:
            element, ctx = await cls._find_element(page, selector)
            await cls._scroll_if_needed(element)
            await cls.highlight_element(ctx, selector, color="#2563eb", status_text=f"Filling {display_label}...")

            # Guard against radio/checkbox being routed to fill_text
            input_type = (await element.get_attribute("type") or "").lower()
            if input_type in ("radio", "checkbox"):
                await element.check()
                await cls.mark_success(ctx, selector, message=f"Selected {display_label} ✓")
                return

            # Check if element already contains the target value to eliminate redundant re-typing
            try:
                current_val = await element.input_value()
                if current_val is not None and current_val.strip() == value.strip():
                    logger.info(f"Field '{selector}' already contains desired value '{value}'. Skipping re-type.")
                    await cls.mark_success(ctx, selector, message=f"{display_label} verified ✓")
                    return
            except Exception:
                pass

            # Check if element is an actual combobox, typeahead, or autocomplete dropdown via DOM attributes
            role = (await element.get_attribute("role") or "").lower()
            aria_auto = (await element.get_attribute("aria-autocomplete") or "").lower()
            aria_popup = (await element.get_attribute("aria-haspopup") or "").lower()
            cls_name = (await element.get_attribute("class") or "").lower()
            is_combobox = (
                role == "combobox" or
                aria_auto in ("list", "both", "inline") or
                aria_popup in ("listbox", "true", "menu") or
                any(k in cls_name for k in ("react-select", "select2", "chosen-select", "combobox", "typeahead"))
            )
            if is_combobox:
                return await cls.fill_autocomplete_or_combobox(page, target, value, field_label=field_label, session_id=session_id)

            # Clear and fill text atomically for robust input without dropped keystrokes
            fill_success = False
            try:
                await element.fill(value)
                await element.dispatch_event("input")
                await element.dispatch_event("change")
                fill_success = True
            except Exception as fill_err:
                is_editable = False
                try:
                    is_editable = await element.evaluate("""
                        el => {
                            const tag = el.tagName.toLowerCase();
                            return tag === 'input' || tag === 'textarea' || el.isContentEditable || el.getAttribute('contenteditable') === 'true';
                        }
                    """)
                except Exception:
                    pass

                if is_editable:
                    logger.warning(f"Standard element.fill failed on '{selector}': {fill_err}. Attempting element click & type...")
                    try:
                        await element.click(timeout=2500, force=True)
                        await element.evaluate("""
                            el => {
                                try {
                                    el.focus();
                                    if (typeof el.select === 'function') el.select();
                                    el.value = '';
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                } catch (e) {}
                            }
                        """)
                        await element.type(value, delay=10)
                        fill_success = True
                    except Exception as kb_err:
                        logger.debug(f"Element typing failed on '{selector}': {kb_err}")
                else:
                    logger.warning(f"Element '{selector}' is not an editable input (fill error: {fill_err}). Skipping click-and-type fallback.")

            # Universal React controlled component value setter
            # React tracks input values via internal _valueTracker. Setting via prototype descriptor ensures React updates state.
            try:
                await element.evaluate("""
                    (el, val) => {
                        try {
                            el.focus();
                            const proto = el instanceof HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
                            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                            if (setter) {
                                setter.call(el, val);
                            } else {
                                el.value = val;
                            }
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        } catch (e) {}
                    }
                """, value)
            except Exception:
                pass

            # Re-verify and ensure complete value was entered (critical for masked/phone inputs)
            try:
                is_input_element = await element.evaluate("el => el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement")
                if is_input_element:
                    actual_val = await element.input_value()
                    val_digits = re.sub(r'\D', '', value)
                    act_digits = re.sub(r'\D', '', actual_val or "")
                    is_numeric_or_phone = bool(val_digits and len(val_digits) >= 7)

                    needs_refill = False
                    if is_numeric_or_phone:
                        if act_digits != val_digits:
                            needs_refill = True
                    elif actual_val != value and (not actual_val or value not in actual_val):
                        needs_refill = True

                    if needs_refill:
                        logger.warning(
                            f"Field '{selector}' input discrepancy: actual '{actual_val}' != expected '{value}'. Refilling with keystrokes..."
                        )
                        await element.click(timeout=2000, force=True)
                        await element.evaluate("""
                            el => {
                                try {
                                    el.focus();
                                    if (typeof el.select === 'function') el.select();
                                    el.value = '';
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                } catch (e) {}
                            }
                        """)
                        await element.type(value, delay=15)
                        await element.dispatch_event("input")
                        await element.dispatch_event("change")
            except Exception:
                pass

            await cls.mark_success(ctx, selector, message=f"Filled {display_label} ✓")
        except Exception as e:
            logger.error(f"Failed to fill text for {selector}: {e}")
            if session_id:
                await event_stream.log_action(
                    session_id,
                    f"Failed to fill field '{display_label}': {e}",
                    level="error",
                    field_id=target
                )
            raise BrowserException(f"Failed to fill text for target '{target}': {e}") from e

    @classmethod
    async def fill_autocomplete_or_combobox(
        cls, page: Page, target: str, value: str, field_label: str = "", session_id: str = ""
    ) -> bool:
        """
        Specialized interaction for custom dropdown / autocomplete / combobox fields:
        1. Clicks input to focus.
        2. Types search value using real keyboard keystrokes with delay to trigger suggestion events.
        3. Waits dynamically for suggestion menu / options to render in the DOM.
        4. Selects the matching option (exact, contains, dial code, or fallback 'Other').
        5. Verifies the selected value in the browser DOM.
        If selection fails, raises BrowserException so the caller can trigger HITL.
        """
        selector = cls._selector(target)
        display_label = field_label or target
        logger.info(f"Action: Fill autocomplete/combobox at '{selector}' with value '{value}'")

        if session_id:
            await event_stream.log_action(
                session_id,
                f"Selecting option in dropdown '{display_label}': \"{value}\"",
                level="info",
                action="select",
                field_id=target,
                field_label=display_label,
                value=value
            )

        try:
            element, ctx = await cls._find_element(page, selector)
            if await element.count() == 0:
                raise BrowserException(f"Autocomplete element '{selector}' not found.")

            await cls._scroll_if_needed(element)
            await cls.highlight_element(ctx, selector, color="#8b5cf6", status_text=f"Searching options for {display_label}...")

            # 1. Focus and clear input
            try:
                await element.click(timeout=2500, force=True)
            except Exception:
                pass
            await page.wait_for_timeout(50)
            try:
                await element.fill("")
            except Exception:
                pass

            # 2. Fast, natural keyboard typing (delay=8ms per key to trigger autocomplete listeners without 3s lag)
            await page.keyboard.type(value, delay=8)
            await page.wait_for_timeout(100)

            # 3. Dynamic suggestion search across DOM and frames using fast single-pass JavaScript evaluation
            option_selectors = [
                '[role="option"]',
                '.select__option',
                'li[role="option"]',
                '[role="listbox"] > *',
                '.dropdown-menu .dropdown-item',
                '.tt-suggestion',
                '.autocomplete-suggestion',
                '[data-reach-combobox-option]',
                'div[id*="option"]',
                'li[id*="option"]',
                '.suggestions-list > *',
                '.pac-item'
            ]
            combined_sel = ", ".join(option_selectors)

            matched_option_text = None
            max_wait_ms = 1000
            poll_interval_ms = 70
            elapsed_ms = 0
            options_rendered_seen = False

            while elapsed_ms < max_wait_ms:
                frames_to_check = [page] + [f for f in page.frames if f != page.main_frame]
                for f in frames_to_check:
                    try:
                        res = await f.evaluate(cls._JS_SEARCH_AND_CLICK, [combined_sel, value])
                        if res and res.get("matched"):
                            matched_option_text = res.get("text", "")
                            break
                        if res and res.get("count", 0) > 0:
                            options_rendered_seen = True
                    except Exception:
                        continue

                # Once matched, break IMMEDIATELY without waiting out the poll timer
                if matched_option_text:
                    break

                # If options are visible in DOM and checked without match, stop early
                if options_rendered_seen and elapsed_ms >= 210:
                    break

                await page.wait_for_timeout(poll_interval_ms)
                elapsed_ms += poll_interval_ms

            if matched_option_text:
                logger.info(f"Selected matching suggestion option '{matched_option_text}' for '{display_label}'.")
                await page.wait_for_timeout(100)
            else:
                # If no suggestion item clicked, commit via Tab without submitting the form
                logger.info(f"No specific suggestion element matched for '{value}'. Committing via Tab...")
                await page.keyboard.press("Tab")
                await page.wait_for_timeout(100)

            # 4. Verification: Inspect whether value was accepted
            verified_val = ""
            try:
                verified_val = (await element.input_value() or "").strip()
            except Exception:
                pass

            if not verified_val:
                try:
                    parent = element.locator("xpath=..")
                    verified_val = (await parent.text_content() or "").strip()
                except Exception:
                    pass

            val_lower = value.strip().lower()
            ver_lower = verified_val.lower()
            tgt_digits = re.sub(r'\D', '', value)

            is_verified = False
            if val_lower in ver_lower or ver_lower in val_lower or "other" in ver_lower:
                is_verified = True
            elif tgt_digits and tgt_digits in re.sub(r'\D', '', verified_val):
                is_verified = True

            if not is_verified and not verified_val:
                raise BrowserException(
                    f"Could not select matching option for '{value}' in dropdown '{display_label}'. "
                    f"Field remains empty in the browser."
                )

            await cls.mark_success(ctx, selector, message=f"Selected {display_label} ✓")
            return True

        except Exception as e:
            logger.error(f"Failed to fill autocomplete/combobox for {selector}: {e}")
            if session_id:
                await event_stream.log_action(
                    session_id,
                    f"Could not select option in dropdown '{display_label}': {e}",
                    level="warning",
                    field_id=target
                )
            raise BrowserException(f"Failed to select option for target '{target}': {e}") from e

    @classmethod
    async def click(cls, page: Page, target: str, wait_navigation: bool = False, field_label: str = "", session_id: str = ""):
        """Click element (button, radio, link, etc.) with visual highlighting and disabled-state protection."""
        selector = cls._selector(target)
        display_label = field_label or target
        logger.info(f"Action: Click element at '{selector}'")

        if session_id:
            await event_stream.log_action(
                session_id,
                f"Clicking: '{display_label}'",
                level="info",
                action="click",
                field_id=target,
                field_label=display_label
            )

        try:
            element, ctx = await cls._find_element(page, selector)
            if await element.count() == 0:
                raise BrowserException(f"Target element '{selector}' not found on page.")

            # Safety check: Verify button is enabled before attempting click to prevent 30s actionability timeout
            is_disabled = await element.evaluate("""
                el => el.disabled || el.getAttribute('aria-disabled') === 'true' ||
                      el.classList.contains('disabled') || el.getAttribute('disabled') !== null ||
                      window.getComputedStyle(el).pointerEvents === 'none'
            """)
            if is_disabled:
                raise BrowserException(
                    f"Cannot click target '{display_label}' ({selector}) because the element is disabled (aria-disabled='true' or disabled attribute)."
                )

            await cls._scroll_if_needed(element)
            await cls.highlight_element(ctx, selector, color="#f59e0b", status_text=f"Clicking {display_label}...")

            if wait_navigation:
                async with page.expect_navigation(timeout=10000):
                    await element.click(timeout=5000)
            else:
                await element.click(timeout=5000)

            # Wait for potential DOM updates / conditional field renders
            await page.wait_for_timeout(300)
            await cls.mark_success(ctx, selector, message=f"Clicked {display_label} ✓")
        except Exception as e:
            logger.error(f"Failed to click target {selector}: {e}")
            if session_id:
                await event_stream.log_action(
                    session_id,
                    f"Failed to click '{display_label}': {e}",
                    level="error",
                    field_id=target
                )
            raise BrowserException(f"Failed to click target '{target}': {e}") from e

    @classmethod
    async def select_option(cls, page: Page, target: str, value_or_label: str, field_label: str = "", session_id: str = ""):
        """Select option in a `<select>` dropdown by label or value with visual highlight."""
        selector = cls._selector(target)
        display_label = field_label or target
        logger.info(f"Action: Select option '{value_or_label}' in dropdown '{selector}'")

        if session_id:
            await event_stream.log_action(
                session_id,
                f"Selecting option '{value_or_label}' for: '{display_label}'",
                level="info",
                action="select",
                field_id=target,
                field_label=display_label,
                value=value_or_label
            )

        try:
            element, ctx = await cls._find_element(page, selector)
            await cls._scroll_if_needed(element)
            await cls.highlight_element(ctx, selector, color="#8b5cf6", status_text=f"Selecting {value_or_label} in {display_label}...")

            tag_name = (await element.evaluate("el => el.tagName") or "").lower()

            if tag_name == "input":
                return await cls.fill_autocomplete_or_combobox(
                    page, target, value_or_label, field_label=field_label, session_id=session_id
                )

            if tag_name == "select":
                # Native <select> element
                try:
                    current_val = await element.input_value()
                    selected_text = await element.evaluate("el => el.options && el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : ''")
                    val_clean = value_or_label.strip().lower()
                    if (current_val and current_val.strip().lower() == val_clean) or (selected_text and selected_text.strip().lower() == val_clean):
                        logger.info(f"Select '{selector}' already set to '{value_or_label}'. Skipping redundant selection.")
                        await cls.mark_success(ctx, selector, message=f"{display_label} verified ✓")
                        return
                except Exception:
                    pass

                try:
                    await element.select_option(label=value_or_label)
                except Exception:
                    try:
                        await element.select_option(value=value_or_label)
                    except Exception:
                        # Match option text, value, dial codes (+91), or fallback to 'Other'
                        matched = await element.evaluate("""
                            (el, target) => {
                                const tgt = (target || '').toLowerCase().trim();
                                const tgtDigits = tgt.replace(/\\D/g, '');

                                // 1. Exact or substring match on text or value
                                for (let i = 0; i < el.options.length; i++) {
                                    const opt = el.options[i];
                                    const txt = opt.text.toLowerCase().trim();
                                    const val = (opt.value || '').toLowerCase().trim();
                                    if (txt === tgt || val === tgt || txt.includes(tgt) || tgt.includes(txt)) {
                                        el.selectedIndex = i;
                                        return opt.text || opt.value;
                                    }
                                }

                                // 2. Numeric / Country dial code match (e.g. +91, 91, India)
                                if (tgtDigits && (tgt.startsWith('+') || tgtDigits === '91' || tgt.includes('91') || tgt.includes('india'))) {
                                    for (let i = 0; i < el.options.length; i++) {
                                        const opt = el.options[i];
                                        const optTxt = opt.text.toLowerCase().trim();
                                        const optDigits = optTxt.replace(/\\D/g, '') || (opt.value || '').replace(/\\D/g, '');
                                        if (optDigits === tgtDigits || optTxt.includes('+91') || optTxt.includes('(91)') || optTxt.includes('india')) {
                                            el.selectedIndex = i;
                                            return opt.text || opt.value;
                                        }
                                    }
                                }

                                // 3. Fallback to 'Other' option for schools, degrees, or unlisted choices
                                for (let i = 0; i < el.options.length; i++) {
                                    const opt = el.options[i];
                                    const txt = opt.text.toLowerCase().trim();
                                    if (txt === 'other' || txt.startsWith('other') || txt.includes('not listed') || txt.includes('unlisted')) {
                                        el.selectedIndex = i;
                                        return opt.text || opt.value;
                                    }
                                }

                                return null;
                            }
                        """, value_or_label)
                        if not matched:
                            raise BrowserException(f"Could not find matching option for '{value_or_label}' in select '{selector}'.")

                # Dispatch change event for dynamic conditional triggers
                await element.dispatch_event("change")
            else:
                # Custom combobox / button dropdown (React-Select, HeadlessUI, Radix, custom div)
                logger.info(f"Target '{selector}' is custom component <{tag_name}>. Opening dropdown and locating option '{value_or_label}'...")
                # Check if it already displays the desired text
                current_text = (await element.text_content() or "").strip()
                if value_or_label.lower() in current_text.lower():
                    logger.info(f"Custom dropdown '{selector}' already contains '{value_or_label}'.")
                    await cls.mark_success(ctx, selector, message=f"{display_label} verified ✓")
                    return

                # Click to open dropdown
                await element.click()
                await page.wait_for_timeout(100)

                # Fast in-page evaluation and click
                custom_sel = '[role="option"], .select__option, li[role="option"], [role="listbox"] > *, .dropdown-item, [data-reach-combobox-option]'
                clicked_option = False

                for _ in range(5):  # poll up to ~350ms
                    frames_to_check = [page] + [f for f in page.frames if f != page.main_frame]
                    for f in frames_to_check:
                        try:
                            res = await f.evaluate(cls._JS_SEARCH_AND_CLICK, [custom_sel, value_or_label])
                            if res and res.get("matched"):
                                clicked_option = True
                                logger.info(f"Selected option '{res.get('text')}' in custom dropdown '{selector}'.")
                                break
                        except Exception:
                            continue
                    if clicked_option:
                        break
                    await page.wait_for_timeout(70)

                # If still not clicked, check if there is an active search input inside the dropdown
                if not clicked_option:
                    search_input = page.locator('input[role="combobox"], input[type="search"], .select__input input').first
                    if await search_input.count() > 0 and await search_input.is_visible():
                        await search_input.fill(value_or_label.strip())
                        await page.wait_for_timeout(50)
                        await search_input.press("Tab")
                        clicked_option = True

                if not clicked_option:
                    raise BrowserException(f"Could not select option '{value_or_label}' in custom dropdown '{selector}'.")

            await page.wait_for_timeout(250)

            # Verify selected text
            try:
                verified_text = await element.evaluate("el => el.options && el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : el.value")
                logger.info(f"Select '{selector}' selected value verified as '{verified_text}'")
            except Exception:
                pass

            await cls.mark_success(ctx, selector, message=f"Selected {value_or_label} ✓")
        except Exception as e:
            logger.error(f"Failed to select option for {selector}: {e}")
            if session_id:
                await event_stream.log_action(
                    session_id,
                    f"Failed to select option for '{display_label}': {e}",
                    level="error",
                    field_id=target
                )
            raise BrowserException(f"Failed to select option for target '{target}': {e}") from e

    @classmethod
    async def check(cls, page: Page, target: str, checked: bool = True, field_label: str = "", session_id: str = ""):
        """Check or uncheck checkbox element with visual highlight."""
        selector = cls._selector(target)
        display_label = field_label or target
        action_verb = "Checking" if checked else "Unchecking"
        logger.info(f"Action: Set checkbox '{selector}' to checked={checked}")

        if session_id:
            await event_stream.log_action(
                session_id,
                f"{action_verb} '{display_label}'",
                level="info",
                action="check",
                field_id=target,
                field_label=display_label
            )

        try:
            element, ctx = await cls._find_element(page, selector)
            await cls._scroll_if_needed(element)
            await cls.highlight_element(ctx, selector, color="#06b6d4", status_text=f"{action_verb} {display_label}...")

            # Skip redundant check/uncheck
            try:
                is_already_checked = await element.is_checked()
                if is_already_checked == checked:
                    logger.info(f"Checkbox '{selector}' already in state checked={checked}. Skipping redundant toggle.")
                    await cls.mark_success(ctx, selector, message=f"{display_label} verified ✓")
                    return
            except Exception:
                pass

            toggle_success = False
            try:
                if checked:
                    await element.check(timeout=2000)
                else:
                    await element.uncheck(timeout=2000)
                toggle_success = True
            except Exception as check_err:
                logger.info(f"Standard element.check failed on '{selector}': {check_err}. Falling back to styled label/indicator toggle...")

            if not toggle_success:
                # Custom stylized checkboxes (e.g. Cisco/Phenom People, Workday custom spans)
                # where the visual click target is the parent <label> or sibling .checkmark
                await element.evaluate("""
                    (el, targetState) => {
                        const isCurrentlyChecked = el.checked || el.getAttribute('ischecked') === 'true' || el.getAttribute('aria-checked') === 'true';
                        if (isCurrentlyChecked === targetState) return true;

                        // Try clicking associated label, checkmark span, or parent wrapper
                        let clickTarget = null;
                        if (el.id) {
                            clickTarget = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                        }
                        if (!clickTarget && el.getAttribute('aria-labelledby')) {
                            clickTarget = document.getElementById(el.getAttribute('aria-labelledby'));
                        }
                        if (!clickTarget) {
                            clickTarget = el.closest('label') || (el.parentElement ? el.parentElement.querySelector('.checkmark, .checkbox-indicator, label') : null);
                        }
                        if (!clickTarget) {
                            clickTarget = el.parentElement;
                        }

                        if (clickTarget) {
                            clickTarget.click();
                        } else {
                            el.click();
                        }

                        // Also ensure internal state flags and change events are fired
                        el.checked = targetState;
                        el.setAttribute('ischecked', String(targetState));
                        el.setAttribute('aria-checked', String(targetState));
                        el.value = targetState ? 'Yes' : 'No';
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                """, checked)

            await cls.mark_success(ctx, selector, message=f"{action_verb} {display_label} ✓")
        except Exception as e:
            logger.error(f"Failed to check/uncheck target {selector}: {e}")
            if session_id:
                await event_stream.log_action(
                    session_id,
                    f"Failed to toggle checkbox '{display_label}': {e}",
                    level="error",
                    field_id=target
                )
            raise BrowserException(f"Failed to check target '{target}': {e}") from e

    @classmethod
    async def upload_file(cls, page: Page, target: str, file_path: str, field_label: str = "", session_id: str = ""):
        """Upload file to a file input element with visual highlight."""
        selector = cls._selector(target)
        display_label = field_label or target
        filename = os.path.basename(file_path)
        logger.info(f"Action: Upload file '{file_path}' to file input '{selector}'")

        if session_id:
            await event_stream.log_action(
                session_id,
                f"Uploading document '{filename}' to '{display_label}'",
                level="info",
                action="upload",
                field_id=target,
                field_label=display_label,
                value=filename
            )

        if not os.path.exists(file_path):
            raise BrowserException(f"File to upload does not exist: {file_path}")

        try:
            element, ctx = await cls._find_element(page, selector)
            try:
                is_vis = await element.is_visible()
                if is_vis:
                    await cls._scroll_if_needed(element)
                    await cls.highlight_element(ctx, selector, color="#ec4899", status_text=f"Uploading {filename}...")
                else:
                    parent = element.locator("xpath=..").first
                    if await parent.count() > 0:
                        await cls._scroll_if_needed(parent)
            except Exception:
                pass

            await element.set_input_files(file_path)
            await element.dispatch_event("input")
            await element.dispatch_event("change")

            # Verify file attachment
            uploaded_name = await element.evaluate("el => el.files && el.files.length > 0 ? el.files[0].name : ''")
            if not uploaded_name:
                val = await element.input_value()
                if not val or filename.lower() not in val.lower():
                    logger.warning(f"File attachment verification notice for '{selector}'. Dispatching change event...")
                    await element.dispatch_event("change")

            await cls.mark_success(ctx, selector, message=f"Uploaded {filename} ✓")
        except Exception as e:
            logger.error(f"Failed to upload file to {selector}: {e}")
            if session_id:
                await event_stream.log_action(
                    session_id,
                    f"Failed to upload '{filename}' to '{display_label}': {e}",
                    level="error",
                    field_id=target
                )
            raise BrowserException(f"Failed to upload file to target '{target}': {e}") from e

    @classmethod
    async def scroll_into_view(cls, page: Page, target: str):
        """Scroll target element into view."""
        selector = cls._selector(target)
        try:
            element, _ = await cls._find_element(page, selector)
            await cls._scroll_if_needed(element)
        except Exception as e:
            logger.error(f"Failed to scroll to {selector}: {e}")
            raise BrowserException(f"Failed to scroll to target '{target}': {e}") from e

    @classmethod
    async def get_input_value(cls, page: Page, target: str) -> Optional[str]:
        """Retrieve current value or text of an input/select/textarea across main page and child frames."""
        selector = cls._selector(target)
        try:
            elem, _ = await cls._find_element(page, selector)
            if await elem.count() == 0:
                return None
            tag = (await elem.evaluate("el => el.tagName") or "").lower()
            if tag == "select":
                return await elem.evaluate("el => el.options && el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : el.value")
            elif tag in ("input", "textarea"):
                return await elem.input_value()
            return await elem.text_content()
        except Exception:
            return None

    @classmethod
    async def is_element_present(cls, page: Page, target: str) -> bool:
        """Check if target element exists across main page and child frames."""
        selector = cls._selector(target)
        try:
            elem, _ = await cls._find_element(page, selector)
            return await elem.count() > 0
        except Exception:
            return False

    @classmethod
    async def get_field_live_state(cls, page: Page, field) -> Dict[str, Any]:
        """Inspect actual DOM state of a FormField (value, selected option text, checked, files)."""
        selector = cls._selector(field.data_jp_id)
        res: Dict[str, Any] = {
            "value": None,
            "selected_text": None,
            "checked": False,
            "files": [],
            "is_visible": False,
            "tag": None
        }
        try:
            elem, _ = await cls._find_element(page, selector)
            if await elem.count() == 0:
                return res

            res["is_visible"] = await elem.is_visible()
            tag = (await elem.evaluate("el => el.tagName") or "").lower()
            res["tag"] = tag
            input_type = (await elem.get_attribute("type") or "").lower()

            if tag == "select":
                select_info = await elem.evaluate("""
                    el => ({
                        value: el.value || '',
                        text: el.options && el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : ''
                    })
                """)
                res["value"] = select_info.get("value")
                res["selected_text"] = select_info.get("text")
            elif input_type in ("checkbox", "radio"):
                res["checked"] = await elem.is_checked()
                res["value"] = await elem.input_value()
            elif input_type == "file":
                files = await elem.evaluate("el => el.files ? Array.from(el.files).map(f => f.name) : []")
                res["files"] = files
                res["value"] = files[0] if files else None
            elif tag in ("input", "textarea"):
                res["value"] = await elem.input_value()
            else:
                text_val = (await elem.text_content() or "").strip()
                res["value"] = text_val
                res["selected_text"] = text_val
        except Exception as e:
            logger.debug(f"Could not read live state for {field.data_jp_id}: {e}")
        return res
