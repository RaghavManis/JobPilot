import os
import pytest
import asyncio
from pathlib import Path
from backend.app.config.settings import settings
from backend.app.browser.manager import BrowserManager
from backend.app.database.session import init_db, engine, Base

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
def mock_html_path():
    path = Path(__file__).parent / "mock_form.html"
    return str(path.absolute())

@pytest.fixture(scope="session")
def mock_file_url(mock_html_path):
    # Format absolute Windows file path as file:/// URL
    clean_path = mock_html_path.replace("\\", "/")
    return f"file:///{clean_path}"

@pytest.fixture
async def async_db():
    await init_db()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture(scope="session")
async def browser_manager():
    manager = BrowserManager(headless=True)
    await manager.start()
    yield manager
    await manager.close_all()
