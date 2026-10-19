from backend.app.agent.state import ApplicationState
from backend.app.core.logging import logger


async def initialize_application_node(state: ApplicationState) -> ApplicationState:
    """Initialize workflow state for application."""
    logger.info(f"Node [INITIALIZE]: Starting workflow for session '{state.application_id}' (URL: {state.target_url})")
    state.status = "RUNNING"
    state.retry_count = 0
    state.error_message = None
    return state
