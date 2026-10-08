"""Request ID and request context middleware for observability (D5)."""

import logging
import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


class RequestContextMiddleware:
    """Attach request_id and user_id to request for observability."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Get request ID from nginx/header if present, otherwise generate
        request_id = (
            request.META.get("HTTP_X_REQUEST_ID") or str(uuid.uuid4())
        )
        request.request_id = request_id  # type: ignore[attr-defined]
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response
