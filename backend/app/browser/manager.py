import asyncio
from typing import Dict, List, Optional, Any
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page
from backend.app.config.settings import settings
from backend.app.core.logging import logger
from backend.app.core.exceptions import BrowserException
from backend.app.core.event_stream import event_stream


class BrowserManager:
    """Manages Playwright browser instances, contexts, and pages per application session."""

    def __init__(self, headless: Optional[bool] = None, slow_mo: Optional[int] = None):
        self.headless = headless if headless is not None else settings.BROWSER_HEADLESS
        self.slow_mo = slow_mo if slow_mo is not None else settings.BROWSER_SLOW_MO

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        # session_id -> {context, page, pages: [Page, ...]}
        self._active_sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def start(self):
        """Initialize Playwright and launch Chromium browser in visible/headed mode."""
        async with self._lock:
            if not self._playwright:
                mode_str = "headless" if self.headless else "visible GUI window"
                logger.info(f"Starting Playwright BrowserManager ({mode_str}, slow_mo={self.slow_mo}ms)...")
                self._playwright = await async_playwright().start()

                # Chrome flags for responsive, clean visible window automation
                chromium_args = [
                    "--start-maximized",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-default-browser-check"
                ]

                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    slow_mo=self.slow_mo,
                    args=chromium_args
                )
                logger.info(f"Playwright Chromium browser launched ({mode_str}).")

    async def create_session(self, session_id: str) -> Page:
        """Create a new isolated BrowserContext and Page for a given session ID."""
        if not self._browser:
            await self.start()

        async with self._lock:
            if session_id in self._active_sessions:
                logger.info(f"Session {session_id} already exists, returning active page.")
                page = self._active_sessions[session_id]["page"]
                try:
                    await page.bring_to_front()
                except Exception:
                    pass
                return page

            logger.info(f"Creating isolated BrowserContext for session: {session_id}")
            context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 JobPilot/1.0"
            )
            page = await context.new_page()
            page.set_default_timeout(settings.BROWSER_TIMEOUT_MS)

            # Support multi-page workflows and popups: track new tabs automatically
            pages_list = [page]

            def handle_new_page(new_p: Page):
                url_lower = (new_p.url or "").lower()
                logger.info(f"New popup/tab detected in session {session_id}: {new_p.url}")
                # Auto-close third-party cloud storage (Dropbox, OneDrive, Google Drive, Box) or OAuth popups
                is_unwanted_popup = any(
                    k in url_lower
                    for k in ("dropbox.com", "login.live.com", "microsoftonline.com", "accounts.google.com", "box.com", "oauth")
                )
                if is_unwanted_popup:
                    logger.warning(f"Closing unwanted third-party cloud/auth popup: {new_p.url}")
                    asyncio.create_task(new_p.close())
                    return

                if session_id in self._active_sessions:
                    self._active_sessions[session_id]["pages"].append(new_p)
                    # Only switch active page if the popup is on the same host as the primary application
                    main_p = pages_list[0] if pages_list else None
                    if main_p:
                        try:
                            from urllib.parse import urlparse
                            main_host = urlparse(main_p.url).netloc
                            popup_host = urlparse(new_p.url).netloc
                            if main_host and popup_host and main_host == popup_host:
                                self._active_sessions[session_id]["page"] = new_p
                        except Exception:
                            pass

                    asyncio.create_task(
                        event_stream.log_action(
                            session_id,
                            f"New tab/page opened: {new_p.url}",
                            level="info",
                            action="navigate"
                        )
                    )

            context.on("page", handle_new_page)

            self._active_sessions[session_id] = {
                "context": context,
                "page": page,
                "pages": pages_list
            }

            try:
                await page.bring_to_front()
            except Exception:
                pass

            await event_stream.log_action(
                session_id,
                f"Visible browser session initialized (mode={'headless' if self.headless else 'visible window'}).",
                level="info"
            )

            return page

    async def get_page(self, session_id: str) -> Page:
        """Retrieve the active Playwright Page for a session ID."""
        if session_id not in self._active_sessions:
            raise BrowserException(f"No active browser session found for ID: {session_id}")
        return self._active_sessions[session_id]["page"]

    async def focus_page(self, session_id: str) -> Dict[str, Any]:
        """
        Bring active browser window and page to the foreground on the user's desktop.
        Validates session, headless state, process/page liveness, and uses OS window activation.
        """
        if session_id not in self._active_sessions:
            raise BrowserException(
                f"No active browser session found for ID: {session_id}. Start an application session first."
            )

        session_data = self._active_sessions[session_id]
        page: Page = session_data.get("page")

        if not page or page.is_closed():
            raise BrowserException(
                "The browser page has been closed or crashed. Please start a new session."
            )

        if self.headless:
            raise BrowserException(
                "Browser is running in headless mode. No visible window is available. Set BROWSER_HEADLESS=False to see the browser window."
            )

        # 1. Bring page/tab to front inside Chromium
        try:
            await page.bring_to_front()
        except Exception as e:
            logger.warning(f"Playwright page.bring_to_front warning: {e}")

        # 2. Activate native OS window
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass

        import sys
        os_activated = False
        os_detail = ""

        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32

                matched_hwnds = []

                def enum_windows_callback(hwnd, lparam):
                    if user32.IsWindowVisible(hwnd):
                        length = user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buf = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, buf, length + 1)
                            w_title = buf.value
                            class_buf = ctypes.create_unicode_buffer(256)
                            user32.GetClassNameW(hwnd, class_buf, 256)
                            c_name = class_buf.value
                            # Match Chromium window
                            if "chrome_widgetwin_1" in c_name.lower():
                                if title and title.lower() in w_title.lower():
                                    matched_hwnds.append((hwnd, w_title, 1))
                                elif any(k in w_title.lower() for k in ("chrome", "chromium", "jobpilot")):
                                    matched_hwnds.append((hwnd, w_title, 2))
                    return True

                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

                if matched_hwnds:
                    matched_hwnds.sort(key=lambda x: x[2])
                    target_hwnd, target_title, _ = matched_hwnds[0]

                    # Restore if minimized (SW_RESTORE = 9)
                    SW_RESTORE = 9
                    user32.ShowWindow(target_hwnd, SW_RESTORE)

                    # Bypass Windows foreground lock using AttachThreadInput
                    fg_hwnd = user32.GetForegroundWindow()
                    fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
                    curr_tid = kernel32.GetCurrentThreadId()

                    if fg_tid != curr_tid:
                        user32.AttachThreadInput(curr_tid, fg_tid, True)
                        user32.SetForegroundWindow(target_hwnd)
                        user32.BringWindowToTop(target_hwnd)
                        user32.AttachThreadInput(curr_tid, fg_tid, False)
                    else:
                        user32.SetForegroundWindow(target_hwnd)
                        user32.BringWindowToTop(target_hwnd)

                    user32.SwitchToThisWindow(target_hwnd, True)
                    os_activated = True
                    os_detail = f"Window '{target_title}' focused via Windows User32 API."
                else:
                    os_detail = "Chromium tab focused via Playwright (OS window not matched)."
            except Exception as win_err:
                logger.warning(f"Could not bring Windows window to front: {win_err}")
                os_detail = f"Playwright tab focused; Windows API notice: {win_err}"
        else:
            import os
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                os_detail = "Playwright tab activated. Note: Remote/Docker environment with no desktop display detected."
            else:
                os_detail = "Playwright tab activated (Linux/Mac desktop)."

        logger.info(f"focus_page for session {session_id}: {os_detail}")
        await event_stream.log_action(session_id, f"Browser window focused: {os_detail}", level="info")
        return {
            "status": "success",
            "message": "Browser brought to front successfully.",
            "detail": os_detail,
            "page_title": title,
            "url": page.url
        }

    async def navigate(self, session_id: str, url: str) -> str:
        """Navigate session page to target URL."""
        page = await self.get_page(session_id)
        logger.info(f"Navigating session {session_id} to: {url}")
        await event_stream.log_action(
            session_id,
            f"Navigating browser to: {url}",
            level="info",
            action="navigate",
            value=url
        )
        try:
            response = await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("load")
            page_title = await page.title()
            logger.info(f"Navigated to '{page_title}' ({page.url})")
            await event_stream.log_action(
                session_id,
                f"Page loaded: '{page_title}'",
                level="info",
                action="navigate"
            )
            return page_title
        except Exception as e:
            logger.error(f"Navigation error for session {session_id}: {e}")
            await event_stream.log_action(
                session_id,
                f"Failed to navigate to {url}: {e}",
                level="error"
            )
            raise BrowserException(f"Failed to navigate to {url}: {e}") from e

    async def close_session(self, session_id: str):
        """Close context and page for a specific session."""
        async with self._lock:
            if session_id in self._active_sessions:
                logger.info(f"Closing browser session: {session_id}")
                session_data = self._active_sessions.pop(session_id)
                try:
                    for p in session_data.get("pages", []):
                        try:
                            await p.close()
                        except Exception:
                            pass
                    await session_data["context"].close()
                except Exception as e:
                    logger.warning(f"Error closing session {session_id}: {e}")
                await event_stream.log_action(
                    session_id,
                    "Browser session closed cleanly.",
                    level="info"
                )

    async def close_all(self):
        """Shutdown browser and Playwright runtime with timeouts to prevent hanging on shutdown."""
        async with self._lock:
            logger.info("Closing all browser sessions and shutting down Playwright...")
            session_ids = list(self._active_sessions.keys())
            for session_id in session_ids:
                session_data = self._active_sessions.pop(session_id, None)
                if session_data:
                    try:
                        for p in session_data.get("pages", []):
                            try:
                                await asyncio.wait_for(p.close(), timeout=1.5)
                            except Exception:
                                pass
                        if "context" in session_data:
                            await asyncio.wait_for(session_data["context"].close(), timeout=1.5)
                    except Exception:
                        pass

            if self._browser:
                try:
                    await asyncio.wait_for(self._browser.close(), timeout=2.0)
                except Exception:
                    pass
                self._browser = None

            if self._playwright:
                try:
                    await asyncio.wait_for(self._playwright.stop(), timeout=2.0)
                except Exception:
                    pass
                self._playwright = None
            logger.info("Playwright BrowserManager shut down completely.")
