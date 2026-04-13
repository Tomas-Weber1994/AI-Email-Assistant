import logging
import sys
from app.settings import settings

def configure_logging() -> None:
    """
    Setup app logging with Uvicorn-like colors.
    Ensures consistent formatting and modular prefixes across all app modules.
    """
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    log_format = "\x1b[32m%(levelname)-9s\x1b[0m [%(name)s] %(message)s"

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(log_format))

    for logger_name in ("app", "audit_trail"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.handlers = [stream_handler]
        logger.propagate = False
