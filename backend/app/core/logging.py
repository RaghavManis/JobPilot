import logging
import sys
from backend.app.config.settings import settings


def setup_logging():
    """Configure structured console logging for JobPilot."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger("jobpilot")
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers if re-initialized
    if not root_logger.handlers:
        root_logger.addHandler(handler)

    return root_logger


logger = setup_logging()
