"""Logging configuration."""
import logging
import os
from logging.handlers import RotatingFileHandler

from app.core.config import settings

FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging() -> None:
    """Configure console logging and optional rotating-file and Sentry handlers."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.LOG_FILE:
        os.makedirs(os.path.dirname(settings.LOG_FILE) or ".", exist_ok=True)
        handlers.append(RotatingFileHandler(settings.LOG_FILE, maxBytes=5_000_000, backupCount=3))
    logging.basicConfig(level=settings.LOG_LEVEL.upper(), format=FORMAT, handlers=handlers, force=True)

    if settings.SENTRY_DSN:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT)
            logging.getLogger(__name__).info("Sentry monitoring enabled")
        except ImportError:
            logging.getLogger(__name__).warning("SENTRY_DSN set but sentry-sdk not installed")
