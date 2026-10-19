from fastapi import APIRouter
from backend.app.config.settings import settings

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Health check endpoint to verify backend service status."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "version": "0.1.0",
        "llm_provider": settings.DEFAULT_LLM_PROVIDER
    }
