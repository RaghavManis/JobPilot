import asyncio
import inspect
from typing import Dict, Any, Callable, Optional, List, Union, Tuple
from backend.app.agent.state import ApplicationState
from backend.app.agent.nodes import (
    initialize_application_node,
    open_browser_node,
    detect_page_node,
    analyze_page_node,
    human_login_pause_node,
    verify_login_completed_node,
    map_fields_and_retrieve_node,
    confidence_routing_node,
    auto_fill_node,
    human_review_pause_node,
    validate_page_node,
    navigate_next_node,
    final_review_node,
    submit_application_node
)
from backend.app.browser.manager import BrowserManager
from backend.app.services.knowledge_service import KnowledgeService
from backend.app.core.logging import logger

END = "__END__"


class StateGraph:
    """Self-contained StateGraph engine implementing node registration, edge routing, and checkpointing."""

    def __init__(self, state_schema=ApplicationState):
        self.state_schema = state_schema
        self.nodes: Dict[str, Callable] = {}
        self.edges: Dict[str, str] = {}
        self.conditional_edges: Dict[str, Tuple[Callable, Dict[str, str]]] = {}
        self.entry_point: Optional[str] = None

    def add_node(self, name: str, action: Callable):
        self.nodes[name] = action

    def set_entry_point(self, name: str):
        self.entry_point = name

    def add_edge(self, start_node: str, end_node: str):
        self.edges[start_node] = end_node

    def add_conditional_edges(self, start_node: str, router: Callable, path_map: Dict[str, str]):
        self.conditional_edges[start_node] = (router, path_map)

    def compile(self, checkpointer=None):
        return CompiledGraph(self, checkpointer=checkpointer)


class CompiledGraph:
    """Compiled state graph runtime executing async steps across nodes and conditional edges."""

    def __init__(self, graph: StateGraph, checkpointer=None):
        self.graph = graph
        self.checkpointer = checkpointer
        self.checkpoints: Dict[str, Any] = {}

    async def ainvoke(
        self,
        state: ApplicationState,
        config: Optional[Dict[str, Any]] = None,
        resume_from: Optional[str] = None
    ) -> ApplicationState:
        thread_id = config.get("configurable", {}).get("thread_id", state.application_id) if config else state.application_id

        # If resume_from is specified, start from that node; otherwise use entry point
        current_node = resume_from if resume_from else self.graph.entry_point
        curr_state = state

        logger.info(f"StateGraph {'resuming' if resume_from else 'starting'} execution at node '{current_node}' for thread '{thread_id}'...")

        step_count = 0
        max_steps = 60  # Allow multi-step forms across multiple wizard pages to complete

        while current_node and current_node != END and step_count < max_steps:
            step_count += 1
            node_action = self.graph.nodes.get(current_node)

            if not node_action:
                logger.warning(f"No action defined for node '{current_node}'. Halting graph.")
                break

            logger.info(f"StateGraph Step {step_count}: Executing node '{current_node}'")
            if inspect.iscoroutinefunction(node_action):
                curr_state = await node_action(curr_state)
            else:
                curr_state = node_action(curr_state)

            # Checkpoint state
            self.checkpoints[thread_id] = curr_state

            # If node set status to PAUSED / LOGIN_REQUIRED / WAITING_FOR_USER / FAILED / CAMERA_VERIFICATION_REQUIRED, halt graph for HITL interrupt
            if curr_state.status in ("LOGIN_REQUIRED", "WAITING_FOR_USER", "FAILED", "READY_FOR_REVIEW", "PAUSED", "STOPPED", "CAMERA_VERIFICATION_REQUIRED"):
                logger.info(f"StateGraph paused at node '{current_node}' with status '{curr_state.status}'.")
                break

            # Determine next node via conditional edge or direct edge
            if current_node in self.graph.conditional_edges:
                router, path_map = self.graph.conditional_edges[current_node]
                route_key = router(curr_state)
                next_node = path_map.get(route_key, END)
                logger.info(f"Conditional Edge from '{current_node}' routed to '{next_node}' (key='{route_key}')")
            elif current_node in self.graph.edges:
                next_node = self.graph.edges[current_node]
            else:
                next_node = END

            if next_node == END or next_node == "end":
                break

            current_node = next_node

        return curr_state


def route_after_detect(state: ApplicationState) -> str:
    if state.status in ("FAILED", "CAMERA_VERIFICATION_REQUIRED"):
        return "end"
    if state.login_required:
        return "human_login_pause"
    return "map_fields"


def route_after_confidence(state: ApplicationState) -> str:
    if state.human_review_queue:
        return "human_review_pause"
    return "auto_fill"


def route_after_validation(state: ApplicationState) -> str:
    # Route to human_review_pause only if there are actual questions to show.
    # validate_page_node populates human_review_queue when it finds empty required
    # fields, so checking the queue (not raw validation_errors) prevents the UI
    # from getting stuck in WAITING_FOR_USER with 0 questions.
    if state.human_review_queue:
        return "human_review_pause"

    if state.status == "SUBMITTED" or state.page_type == "APPLICATION_SUBMITTED":
        return "end"

    # If the portal auto-advanced to the next step during auto_fill (e.g. resume upload auto-advance):
    if state.has_auto_advanced:
        logger.info(f"Portal auto-advanced to Step {state.current_step}. Routing directly to 'map_fields' for new step...")
        state.has_auto_advanced = False
        return "map_fields"

    # Multi-step progression check: If an intermediate 'Next' / 'Continue' button is active,
    # advance to the next application step!
    if state.has_next_page:
        logger.info(f"Multi-step form progression: Intermediate 'Next' button active ({state.next_button_id}). Routing to 'navigate_next'...")
        return "navigate_next"

    # Safety Gate: Final Review is reachable ONLY after actual field processing and verification.
    # Never transition to final review when zero fields were filled or mapped on an application form.
    total_processed = len(state.mapped_answers) + state.total_fields_filled + len(state.all_completed_fields)
    fillable_fields = [
        f for f in (state.detected_fields or [])
        if f.is_visible and f.tag_name not in ("button", "a")
        and (f.input_type or "").lower() not in ("button", "submit", "reset", "image", "hidden")
    ]
    if total_processed == 0 and len(fillable_fields) > 0 and len(state.completed_pages) == 0:
        logger.warning("Safety Gate: Blocked route to final_review — 0 fields processed or mapped on application form.")
        state.status = "FAILED"
        state.error_message = "No application fields could be processed (0 fields processed). Human intervention required."
        return "end"

    return "final_review"


def route_after_navigate(state: ApplicationState) -> str:
    if state.status in ("FAILED", "WAITING_FOR_USER", "STOPPED", "LOGIN_REQUIRED", "SUBMITTED"):
        return "end"
    if state.page_type == "APPLICATION_SUBMITTED" or (state.form_page and state.form_page.page_type == "APPLICATION_SUBMITTED"):
        return "end"

    # Check if there are fillable input fields detected on the newly loaded step
    fillable = [
        f for f in state.detected_fields
        if f.is_visible and f.tag_name not in ("button", "a")
        and (f.input_type or "").lower() not in ("button", "submit", "reset", "image", "hidden")
    ]

    if fillable:
        logger.info(f"Step transition complete. Routing to 'map_fields' for {len(fillable)} new fields on Step {state.current_step}...")
        return "map_fields"

    logger.info("No fillable fields detected on newly loaded page. Routing to 'final_review'...")
    return "final_review"


def route_after_review(state: ApplicationState) -> str:
    if state.submission_approved:
        return "submit_application"
    return "end"


class AgentWorkflowEngine:
    """LangGraph Orchestration Engine managing workflow state, node execution, and HITL interrupts."""

    def __init__(
        self,
        browser_manager: BrowserManager,
        knowledge_service: KnowledgeService
    ):
        self.browser_manager = browser_manager
        self.knowledge_service = knowledge_service
        self.graph = self._build_graph()

    def _build_graph(self):
        """Construct StateGraph workflow."""
        builder = StateGraph(ApplicationState)

        # Node Wrappers passing dependency services
        async def node_open_browser(state: ApplicationState):
            return await open_browser_node(state, self.browser_manager)

        async def node_detect_page(state: ApplicationState):
            return await detect_page_node(state, self.browser_manager)

        async def node_map_fields(state: ApplicationState):
            return await map_fields_and_retrieve_node(state, self.knowledge_service)

        async def node_auto_fill(state: ApplicationState):
            return await auto_fill_node(state, self.browser_manager)

        async def node_validate_page(state: ApplicationState):
            return await validate_page_node(state, self.browser_manager)

        async def node_navigate_next(state: ApplicationState):
            return await navigate_next_node(state, self.browser_manager)

        async def node_final_review(state: ApplicationState):
            return await final_review_node(state, self.browser_manager)

        async def node_submit(state: ApplicationState):
            return await submit_application_node(state, self.browser_manager)

        # Add Nodes
        builder.add_node("initialize", initialize_application_node)
        builder.add_node("open_browser", node_open_browser)
        builder.add_node("detect_page", node_detect_page)
        builder.add_node("human_login_pause", human_login_pause_node)
        builder.add_node("verify_login", verify_login_completed_node)
        builder.add_node("map_fields", node_map_fields)
        builder.add_node("confidence_routing", confidence_routing_node)
        builder.add_node("auto_fill", node_auto_fill)
        builder.add_node("human_review_pause", human_review_pause_node)
        builder.add_node("validate_page", node_validate_page)
        builder.add_node("navigate_next", node_navigate_next)
        builder.add_node("final_review", node_final_review)
        builder.add_node("submit_application", node_submit)

        # Set Entry Point
        builder.set_entry_point("initialize")

        # Define Edges
        builder.add_edge("initialize", "open_browser")
        builder.add_edge("open_browser", "detect_page")

        # Conditional Edge after detect_page
        builder.add_conditional_edges(
            "detect_page",
            route_after_detect,
            {
                "human_login_pause": "human_login_pause",
                "map_fields": "map_fields",
                "end": END
            }
        )

        builder.add_edge("human_login_pause", END)
        builder.add_edge("verify_login", "detect_page")

        builder.add_edge("map_fields", "confidence_routing")

        # Conditional Edge after confidence_routing
        builder.add_conditional_edges(
            "confidence_routing",
            route_after_confidence,
            {
                "human_review_pause": "human_review_pause",
                "auto_fill": "auto_fill"
            }
        )

        builder.add_edge("human_review_pause", END)
        builder.add_edge("auto_fill", "validate_page")

        # Conditional Edge after validate_page
        builder.add_conditional_edges(
            "validate_page",
            route_after_validation,
            {
                "human_review_pause": "human_review_pause",
                "map_fields": "map_fields",
                "navigate_next": "navigate_next",
                "final_review": "final_review",
                "end": END
            }
        )

        # Conditional Edge after navigate_next
        builder.add_conditional_edges(
            "navigate_next",
            route_after_navigate,
            {
                "map_fields": "map_fields",
                "final_review": "final_review",
                "end": END
            }
        )

        # Conditional Edge after final_review
        builder.add_conditional_edges(
            "final_review",
            route_after_review,
            {
                "submit_application": "submit_application",
                "end": END
            }
        )

        builder.add_edge("submit_application", END)

        # Compile Graph
        return builder.compile()

    async def run_step(self, initial_state: ApplicationState) -> ApplicationState:
        """Run full workflow from entry point for a given ApplicationState."""
        config = {"configurable": {"thread_id": initial_state.application_id}}
        logger.info(f"Executing AgentWorkflowEngine graph step for thread '{initial_state.application_id}'...")
        return await self.graph.ainvoke(initial_state, config=config)

    async def run_step_from(self, state: ApplicationState, resume_node: str) -> ApplicationState:
        """Resume workflow from a specific node (used after HITL interrupts)."""
        config = {"configurable": {"thread_id": state.application_id}}
        logger.info(f"Resuming AgentWorkflowEngine from node '{resume_node}' for thread '{state.application_id}'...")
        return await self.graph.ainvoke(state, config=config, resume_from=resume_node)
