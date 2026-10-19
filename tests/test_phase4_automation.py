import os
import pytest
from pathlib import Path
from backend.app.browser.manager import BrowserManager
from backend.app.browser.dom_inspector import DOMInspector
from backend.app.browser.actions import BrowserActions
from backend.app.schemas.form import FieldValue

@pytest.fixture(scope="session")
def mock_multipage_url():
    path = Path(__file__).parent / "mock_multipage.html"
    clean_path = str(path.absolute()).replace("\\", "/")
    return f"file:///{clean_path}"

@pytest.mark.asyncio
async def test_dynamic_conditional_fields(mock_multipage_url):
    bm = BrowserManager(headless=True)
    await bm.start()
    session_id = "test_conditional_session"
    await bm.create_session(session_id)
    await bm.navigate(session_id, mock_multipage_url)
    page = await bm.get_page(session_id)

    # Initial inspection on Step 1
    form_page_step1 = await DOMInspector.inspect_page(page)
    assert form_page_step1.is_multi_page is True

    # Navigate to Step 2
    next_btn_step1 = next(f for f in form_page_step1.fields if "Continue to Step 2" in (f.visible_text or ""))
    await BrowserActions.click(page, next_btn_step1.data_jp_id)

    # Re-inspect Step 2 DOM
    form_page_step2 = await DOMInspector.inspect_page(page)
    select_exp = next(f for f in form_page_step2.fields if f.tag_name == "select")

    # Before selecting "Yes", conditional fields are hidden
    company_field_before = next((f for f in form_page_step2.fields if f.name == "companyName"), None)
    assert company_field_before is None or not company_field_before.is_visible

    # Select "Yes" for experience dropdown
    await BrowserActions.select_option(page, select_exp.data_jp_id, "Yes")

    # Re-inspect DOM post-selection: conditional fields must now be visible!
    form_page_revealed = await DOMInspector.inspect_page(page)
    company_field_after = next(f for f in form_page_revealed.fields if f.name == "companyName")
    assert company_field_after is not None
    assert company_field_after.is_visible is True

    await bm.close_all()

@pytest.mark.asyncio
async def test_multi_page_navigation_and_fill(mock_multipage_url):
    bm = BrowserManager(headless=True)
    await bm.start()
    session_id = "test_multipage_fill"
    await bm.create_session(session_id)
    await bm.navigate(session_id, mock_multipage_url)
    page = await bm.get_page(session_id)

    # Fill Step 1
    form_step1 = await DOMInspector.inspect_page(page)
    fn_field = next(f for f in form_step1.fields if f.name == "firstName")
    ln_field = next(f for f in form_step1.fields if f.name == "lastName")
    email_field = next(f for f in form_step1.fields if f.name == "email")

    await BrowserActions.fill_text(page, fn_field.data_jp_id, "Raghav")
    await BrowserActions.fill_text(page, ln_field.data_jp_id, "Sharma")
    await BrowserActions.fill_text(page, email_field.data_jp_id, "raghav@example.com")

    # Click Next
    next_btn = next(f for f in form_step1.fields if "Continue to Step 2" in (f.visible_text or ""))
    await BrowserActions.click(page, next_btn.data_jp_id)

    # Fill Step 2
    form_step2 = await DOMInspector.inspect_page(page)
    why_join = next(f for f in form_step2.fields if f.name == "whyJoin")
    await BrowserActions.fill_text(page, why_join.data_jp_id, "I am passionate about building AI browser automation agents.")

    # Verify textarea filled
    val = await page.locator(f'[data-jp-id="{why_join.data_jp_id}"]').input_value()
    assert "AI browser automation agents" in val

    await bm.close_all()
