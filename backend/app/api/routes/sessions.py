from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.session import get_db
from backend.app.schemas.session import ApplicationSession, ApplicationSessionCreate
from backend.app.schemas.form import FormPage, FieldValue
from backend.app.services.session_service import SessionService
from backend.app.core.exceptions import JobPilotException

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])

# Global browser manager reference injected at app lifespan
_browser_manager = None


def set_global_browser_manager(manager):
    global _browser_manager
    _browser_manager = manager


def get_session_service(db: AsyncSession = Depends(get_db)) -> SessionService:
    if _browser_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BrowserManager service is not initialized."
        )
    return SessionService(db=db, browser_manager=_browser_manager)


@router.post("/", response_model=ApplicationSession, status_code=status.HTTP_201_CREATED)
async def create_session(
    create_dto: ApplicationSessionCreate,
    service: SessionService = Depends(get_session_service)
):
    """Create a new job application automation session."""
    try:
        return await service.create_session(create_dto)
    except JobPilotException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.get("/{session_id}", response_model=ApplicationSession)
async def get_session(
    session_id: str,
    service: SessionService = Depends(get_session_service)
):
    """Retrieve session details by ID."""
    session = await service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found.")
    return session


@router.post("/{session_id}/navigate", response_model=FormPage)
async def navigate_and_inspect(
    session_id: str,
    service: SessionService = Depends(get_session_service)
):
    """Navigate session browser to target URL and inspect interactive DOM elements."""
    try:
        return await service.start_and_navigate(session_id)
    except JobPilotException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.get("/{session_id}/dom", response_model=FormPage)
async def inspect_dom(
    session_id: str,
    service: SessionService = Depends(get_session_service)
):
    """Inspect current active page DOM in session."""
    try:
        return await service.inspect_current_page(session_id)
    except JobPilotException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.post("/{session_id}/actions/{action_type}")
async def execute_action(
    session_id: str,
    action_type: str,
    field_value: FieldValue,
    service: SessionService = Depends(get_session_service)
):
    """Execute browser action (fill_text, click, select_option, check, upload_file)."""
    try:
        await service.execute_action(session_id, action_type, field_value)
        return {"status": "success", "action": action_type, "target": field_value.data_jp_id}
    except JobPilotException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.delete("/{session_id}")
async def close_session(
    session_id: str,
    service: SessionService = Depends(get_session_service)
):
    """Close session and terminate browser context."""
    try:
        await service.close_session(session_id)
        return {"status": "closed", "session_id": session_id}
    except JobPilotException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
