import os
import sys
import asyncio
from contextlib import asynccontextmanager

# On Windows, Playwright requires ProactorEventLoop for subprocess transport.
# Uvicorn 0.36+ asyncio_loop_factory incorrectly returns SelectorEventLoop when use_subprocess is True on Win32.
if sys.platform == "win32":
    try:
        import uvicorn.loops.asyncio
        uvicorn.loops.asyncio.asyncio_loop_factory = lambda use_subprocess=False: asyncio.ProactorEventLoop
    except Exception:
        pass
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config.settings import settings
from backend.app.core.logging import logger
from backend.app.core.exceptions import JobPilotException
from backend.app.database.session import init_db
from backend.app.browser.manager import BrowserManager
from backend.app.api.routes import (
    health_router,
    sessions_router,
    profile_router,
    knowledge_router,
    agent_router,
    set_global_browser_manager
)

browser_manager = BrowserManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle events."""
    logger.info(f"Starting {settings.APP_NAME} ({settings.APP_ENV})...")
    await init_db()
    await browser_manager.start()
    set_global_browser_manager(browser_manager)
    logger.info("Services initialized successfully.")

    yield

    logger.info(f"Shutting down {settings.APP_NAME}...")
    await browser_manager.close_all()
    logger.info("Shutdown complete.")


app = FastAPI(
    title=settings.APP_NAME,
    description="AI-Powered Universal Job Application Agent",
    version="0.5.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(JobPilotException)
async def jobpilot_exception_handler(request: Request, exc: JobPilotException):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": exc.__class__.__name__, "message": exc.message, "details": exc.details}
    )


app.include_router(health_router)
app.include_router(sessions_router)
app.include_router(profile_router)
app.include_router(knowledge_router)
app.include_router(agent_router)

# Serve compiled Vite frontend build (frontend/dist)
_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
frontend_dist_dir = os.path.join(_root, "frontend", "dist")
frontend_assets_dir = os.path.join(frontend_dist_dir, "assets")

if os.path.exists(frontend_dist_dir):
    # Mount compiled JS/CSS assets
    if os.path.exists(frontend_assets_dir):
        app.mount("/assets", StaticFiles(directory=frontend_assets_dir), name="assets")

    @app.get("/favicon.ico", include_in_schema=False)
    async def serve_favicon():
        favicon_path = os.path.join(frontend_dist_dir, "favicon.ico")
        if os.path.exists(favicon_path):
            return FileResponse(favicon_path)
        return JSONResponse(status_code=204, content={})

    # SPA catch-all: serve index.html for all unmatched GET routes
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        index_path = os.path.join(frontend_dist_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return JSONResponse(status_code=404, content={"error": "Frontend not built. Run: cd frontend && npm run build"})
else:
    @app.get("/", include_in_schema=False)
    async def serve_no_frontend():
        return JSONResponse(
            status_code=503,
            content={"error": "Frontend not built.", "fix": "Run: cd frontend && npm install && npm run build"}
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.is_dev)
