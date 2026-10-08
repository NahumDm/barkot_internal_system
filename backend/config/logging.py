"""Django logging configuration with request/user context (D5)."""

from __future__ import annotations

import os


def get_logging_config() -> dict:
    """Return logging configuration for observability."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: request_id=%(request_id)s user_id=%(user_id)s %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "simple": {
                "format": "%(levelname)s %(message)s",
            },
        },
        "filters": {
            "request_context": {
                "()": "apps.core.logging_filters.RequestContextFilter",
            },
        },
        "handlers": {
            "console": {
                "level": "INFO",
                "class": "logging.StreamHandler",
                "formatter": "verbose",
                "filters": ["request_context"],
            },
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "loggers": {
            "django": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            "django.request": {
                "handlers": ["console"],
                "level": "WARNING",
                "propagate": False,
            },
            "apps": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }
