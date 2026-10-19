from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.app.database.session import get_db
from backend.app.agent.state import ApplicationState
from backend.app.agent.graph import AgentWorkflowEngine
from backend.app.services.session_service import SessionService
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.services.event_stream import event_stream
import backend.app.api.routes.sessions as _sessions_module
import backend.app.api.routes.profile as _profile_module
from backend.app.core.logging import logger
from backend.app.core.exceptions import JobPilotException, BrowserException

router = APIRouter(prefix="/api/agent", tags=["Agent Workflow Engine"])

# Active in-memory workflow instances map: session_id -> {engine, state}
_active_workflows: Dict[str, Dict[str, Any]] = {}


def get_agent_engine(db: AsyncSession = Depends(get_db)) -> AgentWorkflowEngine:
    browser_manager = _sessions_module._browser_manager
    if browser_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BrowserManager service is not initialized."
        )
    knowledge_service = KnowledgeService(
        db=db,
        embedding_provider=_profile_module._embedding_provider,
        vector_store=_profile_module._vector_store
    )
    return AgentWorkflowEngine(
        browser_manager=browser_manager,
        knowledge_service=knowledge_service
    )


@router.post("/{session_id}/step", response_model=ApplicationState)
async def run_workflow_step(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    engine: AgentWorkflowEngine = Depends(get_agent_engine)
):
    """Run next execution step in LangGraph StateGraph workflow for a session."""
    session_service = SessionService(db=db, browser_manager=_sessions_module._browser_manager)
    session = await session_service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found.")

    if session_id not in _active_workflows:
        state = ApplicationState(
            application_id=session.id,
            user_id=session.user_id,
            target_url=session.target_url,
            status=session.status,
            submission_approved=session.submission_approved
        )
        _active_workflows[session_id] = {"engine": engine, "state": state}
    else:
        state = _active_workflows[session_id]["state"]

    try:
        if state.current_url and state.status != "STOPPED":
            updated_state = await engine.run_step_from(state, resume_node="detect_page")
        else:
            updated_state = await engine.run_step(state)
        _active_workflows[session_id]["state"] = updated_state
        return updated_state
    except JobPilotException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.get("/{session_id}/state", response_model=ApplicationState)
async def get_workflow_state(session_id: str):
    """Retrieve active ApplicationState for session."""
    if session_id not in _active_workflows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active workflow found for session {session_id}."
        )
    return _active_workflows[session_id]["state"]


@router.get("/{session_id}/screenshot")
async def get_session_screenshot(session_id: str):
    """Capture live screenshot of the session's active browser page for human review."""
    browser_manager = _sessions_module._browser_manager
    if not browser_manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BrowserManager service is not initialized."
        )
    try:
        page = await browser_manager.get_page(session_id)
        try:
            screenshot_bytes = await page.screenshot(type="png", full_page=True)
        except Exception:
            screenshot_bytes = await page.screenshot(type="png")
        return Response(content=screenshot_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to capture browser screenshot: {e}"
        )


@router.get("/{session_id}/events")
async def get_session_events(session_id: str):
    """Server-Sent Events (SSE) endpoint streaming real-time logs, actions, and status updates."""
    return StreamingResponse(
        event_stream.subscribe(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/{session_id}/pause", response_model=ApplicationState)
async def pause_workflow(session_id: str):
    """Pause the active automation workflow while keeping the browser open."""
    if session_id not in _active_workflows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found.")
    state = _active_workflows[session_id]["state"]
    state.status = "PAUSED"
    await event_stream.update_status(session_id, "PAUSED", "Automation paused by user")
    await event_stream.log_action(
        session_id,
        "Automation paused by user. The visible browser window remains open for inspection.",
        level="warning"
    )
    return state


@router.post("/{session_id}/resume", response_model=ApplicationState)
async def resume_workflow(
    session_id: str,
    engine: AgentWorkflowEngine = Depends(get_agent_engine)
):
    """Resume a paused workflow and continue execution."""
    if session_id not in _active_workflows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found.")
    state = _active_workflows[session_id]["state"]
    state.status = "RUNNING"
    await event_stream.update_status(session_id, "RUNNING", "Workflow resumed")
    await event_stream.log_action(session_id, "Workflow resumed by user. Continuing automation...", level="info")

    if state.submission_approved:
        resume_node = "submit_application"
    elif state.auto_fill_queue:
        resume_node = "auto_fill"
    else:
        resume_node = "detect_page"
    try:
        updated_state = await engine.run_step_from(state, resume_node=resume_node)
        _active_workflows[session_id]["state"] = updated_state
        return updated_state
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/{session_id}/stop")
async def stop_workflow(session_id: str):
    """Stop the automation and cleanly close the browser session."""
    browser_manager = _sessions_module._browser_manager
    if browser_manager:
        await browser_manager.close_session(session_id)
    if session_id in _active_workflows:
        state = _active_workflows[session_id]["state"]
        state.status = "STOPPED"
    await event_stream.update_status(session_id, "STOPPED", "Automation stopped")
    await event_stream.log_action(
        session_id,
        "Automation stopped and browser session closed cleanly by user.",
        level="info"
    )
    return {"message": f"Session {session_id} stopped cleanly."}


@router.post("/{session_id}/focus-browser")
async def focus_browser(session_id: str):
    """Bring the visible browser window to the front on the user's desktop."""
    browser_manager = _sessions_module._browser_manager
    if not browser_manager:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="BrowserManager service not initialized.")
    try:
        result = await browser_manager.focus_page(session_id)
        return result
    except (BrowserException, JobPilotException) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to focus browser window: {e}")


@router.post("/{session_id}/login-complete", response_model=ApplicationState)
async def complete_login(
    session_id: str,
    engine: AgentWorkflowEngine = Depends(get_agent_engine)
):
    """Resume workflow after user completes manual login / MFA / CAPTCHA."""
    if session_id not in _active_workflows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {session_id} not found.")

    state = _active_workflows[session_id]["state"]
    state.login_completed = True
    state.login_required = False
    resume_node = "submit_application" if state.submission_approved else "verify_login"
    updated_state = await engine.run_step_from(state, resume_node=resume_node)
    _active_workflows[session_id]["state"] = updated_state
    return updated_state


@router.post("/{session_id}/approve-submission", response_model=ApplicationState)
async def approve_submission_and_submit(
    session_id: str,
    engine: AgentWorkflowEngine = Depends(get_agent_engine)
):
    """Explicitly approve final submission (submission_approved=True) and trigger submission node."""
    if session_id not in _active_workflows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow {session_id} not found.")

    state = _active_workflows[session_id]["state"]
    state.submission_approved = True

    try:
        updated_state = await engine.run_step_from(state, resume_node="submit_application")
        _active_workflows[session_id]["state"] = updated_state
        return updated_state
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


class HumanReviewAnswers(BaseModel):
    """Payload: field_id -> answer string submitted by human reviewer."""
    answers: Dict[str, str] = {}


@router.post("/{session_id}/human-review", response_model=ApplicationState)
async def submit_human_review(
    session_id: str,
    payload: HumanReviewAnswers,
    engine: AgentWorkflowEngine = Depends(get_agent_engine)
):
    """
    Accept human-reviewed answers for WAITING_FOR_USER fields.

    Strategy:
    1. Merge human answers directly into auto_fill_queue (bypassing ConfidenceEngine,
       which would re-flag 'gender' and other sensitive labels back to MANDATORY_HUMAN_INPUT).
    2. Skip confidence_routing on resume — go straight to auto_fill -> validate_page -> final_review.
    3. Skippable fields (file uploads with no path, empty answers) are excluded from the queue
       so auto_fill doesn't crash on them.
    """
    if session_id not in _active_workflows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active workflow for session {session_id}."
        )

    state = _active_workflows[session_id]["state"]

    if state.status != "WAITING_FOR_USER":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is not waiting for human review (current status: {state.status})."
        )

    from backend.app.schemas.form import ConfidenceResult, FieldValue

    # Build a lookup of detected fields by data_jp_id for type info
    field_type_map = {f.data_jp_id: f for f in (state.detected_fields or [])}

    # 1. Validate user responses against field types, required constraints, and available options
    validated_answers: Dict[str, str] = {}
    for field_id, raw_answer in payload.answers.items():
        field = field_type_map.get(field_id)
        ans = (raw_answer or "").strip()

        if field and field.is_required and not ans:
            field_name = field.label or field.name or field_id
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Field '{field_name}' ({field_id}) is required and cannot be left blank."
            )

        if field and field.options and ans:
            opts_lower = [o.strip().lower() for o in field.options]
            is_multi = (field.input_type or "").lower() in ("checkbox_group", "multiselect")

            if is_multi:
                raw_items = [i.strip() for i in ans.split(",") if i.strip()]
                matched_items = []
                for item in raw_items:
                    item_lower = item.lower()
                    matched = next(
                        (o for o, ol in zip(field.options, opts_lower) if ol == item_lower or item_lower in ol or ol in item_lower),
                        None
                    )
                    if not matched:
                        field_name = field.label or field.name or field_id
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Invalid option '{item}' for field '{field_name}'. Value must be one of: {', '.join(field.options)}"
                        )
                    matched_items.append(matched)
                ans = ", ".join(matched_items)
            else:
                ans_lower = ans.lower()
                matched_option = next(
                    (o for o, ol in zip(field.options, opts_lower) if ol == ans_lower or ans_lower in ol or ol in ans_lower),
                    None
                )
                if not matched_option:
                    # Check if the field in live DOM already has a valid option selected
                    dom_curr = (field.current_value or "").strip().lower()
                    if dom_curr and any(ol == dom_curr or dom_curr in ol for ol in opts_lower):
                        matched_option = next((o for o, ol in zip(field.options, opts_lower) if ol == dom_curr or dom_curr in ol), None)
                        if matched_option:
                            logger.info(f"Using live DOM selected option '{matched_option}' for field '{field.label or field_id}' since submitted answer was invalid.")

                if not matched_option:
                    field_name = field.label or field.name or field_id
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid answer '{ans}' for field '{field_name}'. Value must be one of: {', '.join(field.options)}"
                    )
                ans = matched_option

        validated_answers[field_id] = ans

    # 2. Update mapped_answers with human-confirmed answers and persist reusable feedback
    for field_id, answer in validated_answers.items():
        state.mapped_answers[field_id] = ConfidenceResult(
            field_id=field_id,
            answer=answer,
            confidence=1.0,
            reason="Human-confirmed answer",
            source_citations=["human_review"],
            requires_human_input=False
        )

        # Persist reusable feedback for this specific question context
        if answer:
            field = field_type_map.get(field_id)
            q_label = (field.label or field.name or "") if field else ""
            if q_label:
                engine.knowledge_service.save_user_correction(
                    question=q_label,
                    answer=answer,
                    context={
                        "field_type": field.input_type if field else "text",
                        "section_heading": field.section_heading if field else None,
                        "options": field.options if field else []
                    }
                )

    # 3. Build auto_fill_queue from human answers that have a non-empty value
    new_fill_items: list[FieldValue] = []
    for field_id, answer in validated_answers.items():
        if not answer:
            continue
        field = field_type_map.get(field_id)
        if field:
            ftype = field.input_type or (
                "select" if field.tag_name == "select"
                else "textarea" if field.tag_name == "textarea"
                else "text"
            )
        else:
            ftype = "text"
        if ftype == "file":
            continue
        new_fill_items.append(FieldValue(
            data_jp_id=field_id,
            value=answer,
            field_type=ftype or "text"
        ))

    # Keep existing auto_fill items and merge human-confirmed items
    existing_ids = {item.data_jp_id for item in state.auto_fill_queue}
    for item in new_fill_items:
        if item.data_jp_id not in existing_ids:
            state.auto_fill_queue.append(item)
        else:
            state.auto_fill_queue = [
                item if i.data_jp_id == item.data_jp_id else i
                for i in state.auto_fill_queue
            ]

    # 4. Clear HITL queue and validation errors; mark as running
    state.human_review_queue = []
    state.validation_errors = []
    state.status = "RUNNING"

    # 4. Resume from auto_fill — skips initialize/browser/detect/map/confidence_routing
    #    auto_fill -> validate_page -> final_review -> READY_FOR_REVIEW (pauses for submission approval)
    try:
        updated_state = await engine.run_step_from(state, resume_node="auto_fill")
        _active_workflows[session_id]["state"] = updated_state
        return updated_state
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
