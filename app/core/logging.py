"""
app/core/logging.py

Centralized structured logging configuration.
All modules should import `logger` from here rather than calling
logging.getLogger() independently, ensuring consistent formatting.
"""

import logging
import sys
from app.core.config import get_settings


def configure_logging() -> None:
    """
    Configure root logger with the level defined in settings.
    Called once at application startup in main.py.
    """
    settings = get_settings()

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.

    Usage in any module:
        from app.core.logging import get_logger
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)


# Module-level convenience logger for startup/shutdown messages
logger = get_logger("app")
