import pytest
from backend.app.browser.manager import BrowserManager
from backend.app.browser.dom_inspector import DOMInspector

@pytest.mark.asyncio
async def test_dom_inspector_extract_fields(mock_file_url):
    bm = BrowserManager(headless=True)
    await bm.start()

    session_id = "test_dom_session"
    await bm.create_session(session_id)
    await bm.navigate(session_id, mock_file_url)

    page = await bm.get_page(session_id)
    form_page = await DOMInspector.inspect_page(page)

    assert form_page is not None
    assert len(form_page.fields) >= 7

    # Verify synthetic IDs were injected
    field_ids = [f.data_jp_id for f in form_page.fields]
    assert "field_001" in field_ids

    # Verify specific form fields extracted
    labels = [f.label for f in form_page.fields if f.label]
    assert any("First Name" in l for l in labels)
    assert any("Email Address" in l for l in labels)
    assert any("Country of Residence" in l for l in labels)

    await bm.close_all()
