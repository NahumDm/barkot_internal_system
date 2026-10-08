"""Request ID and request context middleware for observability (D5)."""

import logging
import uuid
from typing import Callable

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


class RequestContextMiddleware:
    """Attach request_id and user_id to request for observability."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Get request ID from nginx/header if present, otherwise generate
        request.request_id = (
            request.META.get("HTTP_X_REQUEST_ID")
            or request.META.get("X-Request-Id")
            or str(uuid.uuid4())
        )
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response
