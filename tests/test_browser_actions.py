import pytest
import os
import tempfile
from backend.app.browser.manager import BrowserManager
from backend.app.browser.dom_inspector import DOMInspector
from backend.app.browser.actions import BrowserActions

@pytest.mark.asyncio
async def test_browser_actions_on_mock_form(mock_file_url):
    bm = BrowserManager(headless=True)
    await bm.start()

    session_id = "test_actions_session"
    await bm.create_session(session_id)
    await bm.navigate(session_id, mock_file_url)

    page = await bm.get_page(session_id)
    form_page = await DOMInspector.inspect_page(page)

    # Find fields by label
    fn_field = next(f for f in form_page.fields if f.label and "First Name" in f.label)
    email_field = next(f for f in form_page.fields if f.label and "Email Address" in f.label)
    country_field = next(f for f in form_page.fields if f.tag_name == "select")
    consent_field = next(f for f in form_page.fields if f.input_type == "checkbox")

    # Perform fill actions
    await BrowserActions.fill_text(page, fn_field.data_jp_id, "Alice")
    await BrowserActions.fill_text(page, email_field.data_jp_id, "alice@example.com")
    await BrowserActions.select_option(page, country_field.data_jp_id, "United States")
    await BrowserActions.check(page, consent_field.data_jp_id, True)

    # Verify input values changed in DOM
    fn_val = await page.locator(f'[data-jp-id="{fn_field.data_jp_id}"]').input_value()
    email_val = await page.locator(f'[data-jp-id="{email_field.data_jp_id}"]').input_value()
    is_checked = await page.locator(f'[data-jp-id="{consent_field.data_jp_id}"]').is_checked()

    assert fn_val == "Alice"
    assert email_val == "alice@example.com"
    assert is_checked is True

    await bm.close_all()
