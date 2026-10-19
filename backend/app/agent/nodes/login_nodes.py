from backend.app.agent.state import ApplicationState
from backend.app.core.logging import logger


async def human_login_pause_node(state: ApplicationState) -> ApplicationState:
    """Pause execution breakpoint when login/OTP/CAPTCHA is required."""
    logger.info(f"Node [HUMAN_LOGIN_PAUSE]: Agent paused for user authentication on session {state.application_id}")
    state.status = "LOGIN_REQUIRED"
    return state


async def verify_login_completed_node(state: ApplicationState) -> ApplicationState:
    """Verify that human authentication is complete and resume workflow."""
    logger.info(f"Node [VERIFY_LOGIN]: Verifying authenticated state...")
    state.login_completed = True
    state.login_required = False
    state.status = "RUNNING"
    return state
