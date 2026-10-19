from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.sessions import router as sessions_router, set_global_browser_manager
from backend.app.api.routes.profile import router as profile_router
from backend.app.api.routes.knowledge import router as knowledge_router
from backend.app.api.routes.agent import router as agent_router

__all__ = [
    "health_router",
    "sessions_router",
    "profile_router",
    "knowledge_router",
    "agent_router",
    "set_global_browser_manager",
]
