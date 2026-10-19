import pytest
from backend.app.browser.manager import BrowserManager

@pytest.mark.asyncio
async def test_browser_manager_lifecycle(mock_file_url):
    bm = BrowserManager(headless=True)
    await bm.start()

    session_id = "test_session_001"
    page = await bm.create_session(session_id)
    assert page is not None

    title = await bm.navigate(session_id, mock_file_url)
    assert "JobPilot" in title

    active_page = await bm.get_page(session_id)
    assert active_page.url == mock_file_url

    await bm.close_session(session_id)
    await bm.close_all()
