"""Logging filters to add request context to log records."""

import logging


class RequestContextFilter(logging.Filter):
    """Add request_id and user_id to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        request = getattr(record, "request", None)
        if request is None:
            # Try to get from thread context if available
            record.request_id = "-"
            record.user_id = "-"
            return True

        record.request_id = getattr(request, "request_id", "-")

        if hasattr(request, "user") and request.user and request.user.is_authenticated:
            record.user_id = request.user.id
        else:
            record.user_id = "-"

        return True
