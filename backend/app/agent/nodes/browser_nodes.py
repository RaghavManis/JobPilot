from backend.app.agent.state import ApplicationState
from backend.app.browser.manager import BrowserManager
from backend.app.browser.dom_inspector import DOMInspector
from backend.app.browser.actions import BrowserActions
from backend.app.core.logging import logger
from backend.app.core.exceptions import BrowserException
from backend.app.services.event_stream import event_stream


async def open_browser_node(state: ApplicationState, browser_manager: BrowserManager) -> ApplicationState:
    """Open Playwright browser session and navigate to application target URL if not already open."""
    try:
        await browser_manager.create_session(state.application_id)
        page = await browser_manager.get_page(state.application_id)
        curr_url = (page.url or "").strip()

        # If browser session is already active and currently on an application page (not blank),
        # keep the user's active page position and do NOT force-reload state.target_url!
        if curr_url and curr_url != "about:blank":
            logger.info(f"Node [OPEN_BROWSER]: Browser already open at active page '{curr_url}'. Preserving current position.")
            title = await page.title()
        else:
            logger.info(f"Node [OPEN_BROWSER]: Navigating to initial target URL {state.target_url}")
            await event_stream.update_status(state.application_id, "RUNNING", "Opening visible browser...")
            title = await browser_manager.navigate(state.application_id, state.target_url)
            await event_stream.log_action(
                state.application_id,
                f"Browser window opened and loaded '{title}'.",
                level="info",
                action="navigate",
                value=page.url
            )

        state.current_page_title = title
        state.current_url = page.url
        return state
    except Exception as e:
        logger.error(f"Node [OPEN_BROWSER] Error: {e}")
        state.status = "FAILED"
        state.error_message = f"Failed to open browser or navigate: {e}"
        await event_stream.update_status(state.application_id, "FAILED", str(e))
        await event_stream.log_action(state.application_id, f"Browser error: {e}", level="error")
        return state


async def detect_page_node(state: ApplicationState, browser_manager: BrowserManager) -> ApplicationState:
    """Check current active page, inspect text for login walls or authentication requirement."""
    logger.info(f"Node [DETECT_PAGE]: Checking page for authentication barriers...")
    await event_stream.update_status(state.application_id, "RUNNING", "Analyzing page structure...")
    await event_stream.log_action(state.application_id, "Analyzing website DOM and extracting interactive elements...", action="analyze")
    try:
        page = await browser_manager.get_page(state.application_id)
        # Give modern SPAs a brief moment if still mounting client-side forms
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        # Dismiss any blocking cookie / consent overlays before DOM inspection
        await BrowserActions.dismiss_cookie_and_overlay_banners(page)

        form_page = await DOMInspector.inspect_page(page)

        state.current_url = page.url
        state.current_page_title = form_page.title
        state.form_page = form_page
        state.page_type = form_page.page_type
        state.auth_category = form_page.auth_category
        state.auth_details = form_page.auth_details

        # If the page has an active login/auth barrier, login is required
        state.login_required = form_page.has_login_wall

        if state.login_required:
            state.status = "LOGIN_REQUIRED"
            category_label = form_page.auth_category or "Authentication"
            logger.warning(f"Authentication barrier ({category_label}) detected on page! Pausing for user interaction.")
            await event_stream.update_status(state.application_id, "LOGIN_REQUIRED", f"{category_label} required")
            detail_msg = form_page.auth_details or "Authentication barrier detected on portal."
            await event_stream.log_action(
                state.application_id,
                f"⚠️ {detail_msg} Switch to the visible browser window, complete authentication/registration, and click Resume.",
                level="warning"
            )
        elif form_page.has_webcam_challenge:
            state.status = "CAMERA_VERIFICATION_REQUIRED"
            logger.warning("Live camera / selfie identity verification detected on page! Pausing for user interaction.")
            await event_stream.update_status(state.application_id, "CAMERA_VERIFICATION_REQUIRED", "Live Camera Verification Required")
            await event_stream.log_action(
                state.application_id,
                "⚠️ Live selfie / webcam identity verification detected on portal. Switch to the visible browser window, complete camera verification, and click Resume.",
                level="warning"
            )
        else:
            state.detected_fields = form_page.fields
            state.login_completed = True
            logger.info(f"Page valid ({form_page.page_type}). Detected {len(form_page.fields)} interactive fields.")
            await event_stream.log_action(
                state.application_id,
                f"Page structure analyzed: {len(form_page.fields)} interactive application fields identified.",
                level="info",
                action="analyze"
            )

        return state
    except Exception as e:
        logger.error(f"Node [DETECT_PAGE] Error: {e}")
        state.status = "FAILED"
        state.error_message = f"Failed page detection: {e}"
        await event_stream.update_status(state.application_id, "FAILED", str(e))
        await event_stream.log_action(state.application_id, f"❌ Failed page detection: {e}", level="error")
        return state


async def analyze_page_node(state: ApplicationState, browser_manager: BrowserManager) -> ApplicationState:
    """Re-analyze page DOM after interactions or state updates."""
    logger.info("Node [ANALYZE_PAGE]: Re-inspecting DOM interactive elements...")
    try:
        page = await browser_manager.get_page(state.application_id)
        form_page = await DOMInspector.inspect_page(page)
        state.form_page = form_page
        state.detected_fields = form_page.fields
        return state
    except Exception as e:
        logger.error(f"Node [ANALYZE_PAGE] Error: {e}")
        return state
