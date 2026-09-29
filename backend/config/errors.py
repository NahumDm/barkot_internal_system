r"""Project-level error handlers.

An unmatched URL never reaches a view function, so DRF's exception handler
cannot see it, and Django answers with its HTML 404 by default. A JSON client
then has to check the content type before it can read a status code, and the
first screen that forgets produces ``Unexpected token < in JSON``.

Only the API's own failures are answered with JSON. A browser navigating to a
non-API path still gets an ordinary 404 page, which is the right shape for a
person reading it.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, JsonResponse

#: Paths whose failures are machine-facing. Anything else gets Django's default.
API_PREFIX = "/api/"


def wants_json(request: HttpRequest) -> bool:
    """Return whether this request should be answered in JSON.

    A path under ``/api/`` is always a machine caller, even when it carries no
    ``Accept`` header - the API root, the schema and the health probes are all
    fetched by scripts that do not set one. The ``Accept`` check is kept as a
    fallback for a future non-API JSON endpoint.

    Args:
        request: The incoming request.

    Returns:
        True when a JSON body is the appropriate response.
    """
    if request.path.startswith(API_PREFIX):
        return True
    return "application/json" in request.headers.get("Accept", "")


def not_found(request: HttpRequest, exception: Exception) -> HttpResponse:
    """Return the API error envelope for an unmatched URL under ``/api/``.

    Registered as ``handler404`` in ``config/urls.py``. The ``exception``
    argument is unused: an unmatched URL and a slug that does not exist are
    indistinguishable to the client, and telling them apart would leak which
    records exist.

    Args:
        request: The incoming request.
        exception: What Django failed to resolve. Unused, per the signature.

    Returns:
        A JSON 404 in the standard envelope, or Django's HTML 404 otherwise.
    """
    if not wants_json(request):
        from django.views.defaults import page_not_found

        return page_not_found(request, exception)
    return JsonResponse(
        {
            "error": {
                "code": "not_found",
                "message": "The requested resource does not exist.",
            }
        },
        status=404,
    )
