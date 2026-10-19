import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.database.session import init_db, AsyncSessionLocal
from backend.app.browser.manager import BrowserManager
from backend.app.rag.embeddings.mock_provider import MockEmbeddingProvider
from backend.app.rag.vector_store.faiss_store import FAISSVectorStore
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.services.session_service import SessionService
from backend.app.schemas.session import ApplicationSessionCreate
from backend.app.schemas.form import FormField, ConfidenceResult
from backend.app.agent.state import ApplicationState
from backend.app.agent.confidence import ConfidenceEngine
from backend.app.agent.graph import AgentWorkflowEngine, route_after_validation
from backend.app.agent.nodes.review_nodes import submit_application_node, final_review_node
from backend.app.core.exceptions import JobPilotException

def test_confidence_engine_sensitive_and_thresholds():
    engine = ConfidenceEngine(auto_threshold=0.90, suggest_threshold=0.70)

    # Sensitive field -> MANDATORY_HUMAN_INPUT
    f_salary = FormField(data_jp_id="f_001", tag_name="input", label="Expected Salary ($)")
    ans_salary = ConfidenceResult(field_id="f_001", answer="$150,000", confidence=0.95, reason="Match")
    cat_salary = engine.evaluate_field(f_salary, ans_salary)
    assert cat_salary == "MANDATORY_HUMAN_INPUT"

    # High confidence standard field -> AUTO_FILL
    f_fname = FormField(data_jp_id="f_002", tag_name="input", label="First Name")
    ans_fname = ConfidenceResult(field_id="f_002", answer="Raghav", confidence=0.99, reason="Match")
    cat_fname = engine.evaluate_field(f_fname, ans_fname)
    assert cat_fname == "AUTO_FILL"

    # Low confidence field -> MANDATORY_HUMAN_INPUT
    f_low = FormField(data_jp_id="f_003", tag_name="input", label="Favorite Editor")
    ans_low = ConfidenceResult(field_id="f_003", answer="VSCode", confidence=0.45, reason="Guess")
    cat_low = engine.evaluate_field(f_low, ans_low)
    assert cat_low == "MANDATORY_HUMAN_INPUT"

@pytest.mark.asyncio
async def test_hard_submission_safety_lock(mock_file_url):
    bm = BrowserManager(headless=True)
    await bm.start()
    session_id = "test_safety_lock_session"
    await bm.create_session(session_id)
    await bm.navigate(session_id, mock_file_url)

    state_unapproved = ApplicationState(
        application_id=session_id,
        user_id="user_test",
        target_url=mock_file_url,
        submission_approved=False
    )

    # Must raise JobPilotException when submission_approved is False
    with pytest.raises(JobPilotException) as exc_info:
        await submit_application_node(state_unapproved, bm)
    assert "HARD SUBMISSION LOCK PREVENTED SUBMISSION" in exc_info.value.message

    # Fill mock form required fields so browser form submit succeeds and confirms completion
    page = await bm.get_page(session_id)
    await page.fill("#first_name", "Jane")
    await page.fill("#last_name", "Doe")
    await page.fill("#email", "jane@example.com")
    await page.select_option("#country", "US")
    await page.check("#consent")
    await page.evaluate("() => document.getElementById('resume').removeAttribute('required')")

    # Must succeed when submission_approved is True
    state_approved = ApplicationState(
        application_id=session_id,
        user_id="user_test",
        target_url=mock_file_url,
        submission_approved=True
    )
    res_approved = await submit_application_node(state_approved, bm)
    assert res_approved.status == "SUBMITTED"

    await bm.close_all()

@pytest.mark.asyncio
async def test_agent_workflow_engine_end_to_end(mock_file_url):
    await init_db()
    bm = BrowserManager(headless=True)
    await bm.start()

    async with AsyncSessionLocal() as session:
        embedder = MockEmbeddingProvider()
        store = FAISSVectorStore()
        ks = KnowledgeService(db=session, embedding_provider=embedder, vector_store=store)

        engine = AgentWorkflowEngine(browser_manager=bm, knowledge_service=ks)
        assert engine.graph is not None

        initial_state = ApplicationState(
            application_id="session_e2e_001",
            user_id="user_default",
            target_url=mock_file_url
        )

        final_state = await engine.run_step(initial_state)
        assert final_state.status in ("RUNNING", "WAITING_FOR_USER", "READY_FOR_REVIEW", "SUBMITTED")
        assert final_state.current_page_title is not None

    await bm.close_all()


def test_final_review_safety_gate_blocks_zero_processed_fields():
    """Ensure route_after_validation blocks transition to final_review if zero fields were processed."""
    state_empty = ApplicationState(
        application_id="app_safety_gate",
        user_id="user_test",
        target_url="https://company.com/apply",
        detected_fields=[
            FormField(data_jp_id="f1", tag_name="input", input_type="text", label="First Name"),
            FormField(data_jp_id="f2", tag_name="input", input_type="email", label="Email")
        ],
        mapped_answers={},  # 0 fields mapped or processed
        human_review_queue=[]
    )

    next_route = route_after_validation(state_empty)
    assert next_route == "end"
    assert state_empty.status == "FAILED"
    assert "0 fields processed" in state_empty.error_message


@pytest.mark.asyncio
async def test_final_review_node_sets_failed_when_zero_fields():
    """Ensure final_review_node refuses to declare READY_FOR_REVIEW when 0 fields were processed."""
    state_empty = ApplicationState(
        application_id="app_review_fail",
        user_id="user_test",
        target_url="https://company.com/apply",
        detected_fields=[
            FormField(data_jp_id="f1", tag_name="input", input_type="text", label="First Name")
        ],
        mapped_answers={},  # 0 fields mapped
        status="RUNNING"
    )

    res = await final_review_node(state_empty)
    assert res.status == "FAILED"
    assert "zero fields were filled or processed" in res.error_message


def test_route_after_validation_routes_to_navigate_next_when_next_page_exists():
    """Verify route_after_validation routes to navigate_next rather than final_review when an intermediate Next button is present."""
    state_step1 = ApplicationState(
        application_id="app_multipage_step1",
        user_id="user_test",
        target_url="https://company.com/apply?step=1",
        detected_fields=[
            FormField(data_jp_id="f1", tag_name="input", input_type="text", label="First Name"),
            FormField(data_jp_id="btn_next", tag_name="button", input_type="submit", visible_text="Next")
        ],
        mapped_answers={"f1": ConfidenceResult(field_id="f1", answer="Raghav", confidence=0.99, reason="Match")},
        has_next_page=True,
        next_button_id="btn_next"
    )

    next_route = route_after_validation(state_step1)
    assert next_route == "navigate_next", "Should route to 'navigate_next' instead of 'final_review' when has_next_page is True"


@pytest.mark.asyncio
async def test_navigate_next_node_advances_multipage_mock():
    """Verify navigate_next_node clicks the Next button, advances step, and inspects new fields."""
    import os
    from backend.app.agent.nodes.execution_nodes import navigate_next_node

    bm = BrowserManager(headless=True)
    await bm.start()
    session_id = "test_multipage_session"
    await bm.create_session(session_id)

    mock_multipage_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "mock_multipage.html"))
    mock_url = f"file:///{mock_multipage_path.replace(os.sep, '/')}"
    await bm.navigate(session_id, mock_url)

    from backend.app.browser.dom_inspector import DOMInspector
    page = await bm.get_page(session_id)
    initial_form = await DOMInspector.inspect_page(page)

    state = ApplicationState(
        application_id=session_id,
        user_id="user_test",
        target_url=mock_url,
        current_url=mock_url,
        current_step=1,
        form_page=initial_form,
        detected_fields=initial_form.fields,
        has_next_page=True
    )

    # Execute navigate_next_node
    updated_state = await navigate_next_node(state, bm)

    # Step must advance from 1 to 2
    assert updated_state.current_step == 2
    # Step 2 fields must now be visible in DOM
    step2_fields = [f for f in updated_state.detected_fields if f.is_visible]
    assert len(step2_fields) > 0

    await bm.close_all()

