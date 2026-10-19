import uuid
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.database.models import ApplicationSessionModel, AgentEventModel, UserProfileModel
from backend.app.browser.manager import BrowserManager
from backend.app.browser.dom_inspector import DOMInspector
from backend.app.browser.actions import BrowserActions
from backend.app.schemas.session import ApplicationSession, ApplicationSessionCreate, BrowserSession
from backend.app.schemas.form import FormPage, FieldValue
from backend.app.schemas.agent import AgentEvent
from backend.app.core.logging import logger
from backend.app.core.exceptions import SessionException


class SessionService:
    """Service layer managing application session state, browser integration, and activity logging."""

    def __init__(self, db: AsyncSession, browser_manager: BrowserManager):
        self.db = db
        self.browser_manager = browser_manager

    async def log_event(self, session_id: str, event_type: str, message: str, details: Optional[Dict[str, Any]] = None) -> AgentEventModel:
        """Create structured activity log event in DB."""
        event = AgentEventModel(
            id=str(uuid.uuid4()),
            session_id=session_id,
            event_type=event_type,
            message=message,
            details_json=json.dumps(details) if details else None,
            timestamp=datetime.utcnow()
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        logger.info(f"Session [{session_id}] Event [{event_type}]: {message}")
        return event

    async def create_session(self, create_dto: ApplicationSessionCreate) -> ApplicationSession:
        """Initialize new application session in DB and start browser context."""
        session_id = str(uuid.uuid4())
        session_model = ApplicationSessionModel(
            id=session_id,
            user_id=create_dto.user_id,
            target_url=create_dto.target_url,
            status="CREATED",
            submission_approved=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        self.db.add(session_model)
        await self.db.commit()
        await self.db.refresh(session_model)

        await self.log_event(session_id, "SESSION_CREATED", f"Session created for URL: {create_dto.target_url}")

        # Initialize browser context for session
        await self.browser_manager.create_session(session_id)
        await self.log_event(session_id, "BROWSER_START", "Browser context initialized.")

        return ApplicationSession.model_validate(session_model)

    async def get_session(self, session_id: str) -> Optional[ApplicationSession]:
        """Fetch session from DB."""
        stmt = select(ApplicationSessionModel).where(ApplicationSessionModel.id == session_id)
        result = await self.db.execute(stmt)
        session_model = result.scalar_one_or_none()
        if not session_model:
            return None
        return ApplicationSession.model_validate(session_model)

    async def start_and_navigate(self, session_id: str) -> FormPage:
        """Navigate session browser to target URL and inspect initial DOM."""
        session = await self.get_session(session_id)
        if not session:
            raise SessionException(f"Session {session_id} not found.")

        page_title = await self.browser_manager.navigate(session_id, session.target_url)

        # Update DB session record
        stmt = select(ApplicationSessionModel).where(ApplicationSessionModel.id == session_id)
        res = await self.db.execute(stmt)
        db_model = res.scalar_one()
        db_model.status = "RUNNING"
        db_model.current_page_title = page_title
        db_model.current_url = session.target_url
        await self.db.commit()

        await self.log_event(session_id, "PAGE_NAVIGATE", f"Navigated to '{page_title}'")

        # Inspect DOM
        page = await self.browser_manager.get_page(session_id)
        form_page = await DOMInspector.inspect_page(page)

        await self.log_event(
            session_id,
            "DOM_INSPECT",
            f"Inspected page. Found {len(form_page.fields)} fields.",
            {"fields_count": len(form_page.fields), "has_login": form_page.has_login_wall}
        )

        return form_page

    async def inspect_current_page(self, session_id: str) -> FormPage:
        """Inspect current page DOM without navigating."""
        page = await self.browser_manager.get_page(session_id)
        form_page = await DOMInspector.inspect_page(page)
        await self.log_event(
            session_id,
            "DOM_INSPECT",
            f"Re-inspected current page. Found {len(form_page.fields)} fields."
        )
        return form_page

    async def execute_action(self, session_id: str, action_type: str, field_value: FieldValue):
        """Execute a browser action (fill_text, click, select_option, check, upload) on session page."""
        page = await self.browser_manager.get_page(session_id)
        target = field_value.data_jp_id
        val = field_value.value

        if action_type == "fill_text":
            await BrowserActions.fill_text(page, target, str(val))
        elif action_type == "click":
            await BrowserActions.click(page, target)
        elif action_type == "select_option":
            await BrowserActions.select_option(page, target, str(val))
        elif action_type == "check":
            await BrowserActions.check(page, target, checked=bool(val))
        elif action_type == "upload_file":
            await BrowserActions.upload_file(page, target, str(val))
        else:
            raise SessionException(f"Unsupported action type: {action_type}")

        await self.log_event(
            session_id,
            "ACTION_EXECUTE",
            f"Executed action '{action_type}' on '{target}'",
            {"action": action_type, "target": target, "value": str(val)}
        )

    async def close_session(self, session_id: str):
        """Close browser context and update DB session status."""
        await self.browser_manager.close_session(session_id)

        stmt = select(ApplicationSessionModel).where(ApplicationSessionModel.id == session_id)
        res = await self.db.execute(stmt)
        db_model = res.scalar_one_or_none()
        if db_model:
            db_model.status = "CLOSED"
            await self.db.commit()

        await self.log_event(session_id, "SESSION_CLOSED", "Session and browser context closed.")
