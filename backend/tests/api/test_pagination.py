r"""Pagination: that it is wired, bounded, and applied without being asked.

Every list endpoint is paginated (spec §20.2) because one request must not be
able to ask the API container for a year of sales rows. These tests drive a
throwaway view that declares no pagination of its own, so they pass only while
``DEFAULT_PAGINATION_CLASS`` is doing the work.

The rows are a plain in-memory list rather than real database records. That is
deliberate: the thing under test is the paginator and the setting that points
DRF at it, and 250 real inserts per test would test the database instead.

The cap and its validation are the parts worth being strict about. Silently
returning a different number of rows than were asked for is how a
reconciliation report quietly loses a page of transactions: the client asked
for 500, got 200, and had no way to notice.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from django.conf import settings
from django.test import Client
from rest_framework import serializers, status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from apps.core.pagination import BarkotPagination

factory = APIRequestFactory()

ROWS = 250

#: The single source of truth for the expected sizes. Reading them off an
#: instance of the configured class means these assertions describe the
#: behaviour rather than restating a literal that could drift from the code.
PAGINATOR = BarkotPagination()


class RowSerializer(serializers.Serializer):
    """A stand-in for any real list row."""

    id = serializers.IntegerField()


class _ListView(GenericAPIView):
    """A list endpoint that declares no pagination and no authentication.

    ``paginate_queryset`` is what makes this a test of the *default*: DRF
    returns ``None`` from it when no paginator is configured, so if
    ``DEFAULT_PAGINATION_CLASS`` were ever removed from the settings this view
    would return its whole list in one response and every test below fails.
    """

    serializer_class = RowSerializer
    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def get(self, request: Request) -> Response:
        """Return the rows, letting the configured default do the paging.

        DRF reads the request off the view, so it is not passed on here.

        Args:
            request: The incoming request, carrying any ``page`` and
                ``page_size`` query parameters.

        Returns:
            The paginated response, or an unpaginated one if pagination has
            been switched off entirely.
        """
        rows = [{"id": index} for index in range(ROWS)]
        page = self.paginate_queryset(rows)
        data = RowSerializer(page if page is not None else rows, many=True).data
        if page is not None:
            return self.get_paginated_response(data)
        return Response({"results": data})  # pragma: no cover


def _get(query: str = "") -> tuple[int, Any]:
    """Call the throwaway list and return ``(status, body)``.

    Args:
        query: Query string without the leading ``?``.

    Returns:
        The status code and the response body.
    """
    path = f"/api/v1/rows/{'?' + query if query else ''}"
    response = _ListView.as_view()(factory.get(path))
    return response.status_code, response.data


def _body(query: str = "") -> dict[str, Any]:
    """Call the throwaway list and return only the body.

    Args:
        query: Query string without the leading ``?``.

    Returns:
        The response body, having asserted the request succeeded.
    """
    status_code, data = _get(query)
    assert status_code == status.HTTP_200_OK, data
    return dict(data)


# -- The default is wired ----------------------------------------------------


def test_a_list_is_paginated_without_asking() -> None:
    """A view with no pagination configured still pages, from the default."""
    body = _body()

    assert body["count"] == ROWS
    assert body["page"] == 1
    assert len(body["results"]) == PAGINATOR.page_size


def test_the_envelope_carries_the_resolved_page_size() -> None:
    """The client is told which size it got rather than recomputing it.

    Without this the frontend cannot show "showing 20 of 250" when the server
    has silently chosen a different default from the one the UI assumed.
    """
    assert _body()["page_size"] == PAGINATOR.page_size


def test_the_page_count_matches_the_total() -> None:
    """``pages`` is what a pager needs in order to render "page 2 of 13"."""
    expected = -(-ROWS // PAGINATOR.page_size)  # ceiling division

    assert _body()["pages"] == expected


def test_a_second_page_returns_the_next_slice() -> None:
    """Paging actually advances rather than repeating page one."""
    first = [row["id"] for row in _body()["results"]]
    second = [row["id"] for row in _body("page=2")["results"]]

    assert first == list(range(PAGINATOR.page_size))
    assert second == list(range(PAGINATOR.page_size, PAGINATOR.page_size * 2))


# -- The cap -----------------------------------------------------------------


def test_a_large_page_size_is_capped_rather_than_refused() -> None:
    """``?page_size=500`` returns the maximum, not an error.

    Capping is friendlier than refusing, and the response reports what it did
    via ``page_size``, so a client can detect the cap by comparing the two.
    """
    body = _body("page_size=500")

    assert body["page_size"] == PAGINATOR.max_page_size
    assert len(body["results"]) == PAGINATOR.max_page_size
    assert body["count"] == ROWS


def test_a_page_size_within_the_cap_is_honoured() -> None:
    """The cap is a ceiling, not a fixed size."""
    assert _body("page_size=50")["page_size"] == 50


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "1.5"])
def test_a_nonsensical_page_size_is_rejected_rather_than_ignored(bad: str) -> None:
    """DRF's own handling of these quietly falls back to the default size.

    Serving 20 rows to a client that asked for ``0``, or for ``abc``, is the
    failure worth avoiding: the request looks successful and the rows look
    complete, so a reconciliation report comes out short with no indication of
    why. A 400 says what actually went wrong.
    """
    status_code, _ = _get(f"page_size={bad}")

    assert status_code == status.HTTP_400_BAD_REQUEST


def test_an_out_of_range_page_is_404() -> None:
    """Page 99 of 13 is a 404, not an empty 200 that reads like no data."""
    status_code, _ = _get("page=99")

    assert status_code == status.HTTP_404_NOT_FOUND


def test_a_pagination_failure_uses_the_standard_error_envelope() -> None:
    """A pagination failure is an API failure and is shaped like every other."""
    status_code, data = _get("page_size=abc")

    assert status_code == status.HTTP_400_BAD_REQUEST
    assert data["error"]["code"] == "validation_error"
    assert "page_size" in data["error"]["details"]


# -- Cross-checking the default setting actually points here -----------------


def test_the_configured_default_resolves_to_this_class() -> None:
    """A typo in the dotted path would otherwise only surface in production.

    DRF resolves ``DEFAULT_PAGINATION_CLASS`` lazily, so a wrong path fails on
    the first real list request rather than at boot. The path is resolved by
    hand here so the check is about the setting string, not about DRF agreeing
    with itself.
    """
    dotted = str(settings.REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"])
    module_path, _, class_name = dotted.rpartition(".")
    resolved = getattr(importlib.import_module(module_path), class_name)

    assert resolved is type(PAGINATOR)
    assert api_settings.DEFAULT_PAGINATION_CLASS is type(PAGINATOR)


# -- Probes stay out of it ---------------------------------------------------


def test_health_probe_is_not_paginated() -> None:
    """Probes are infrastructure; a paginated health check would be nonsense."""
    assert "page" not in Client().get("/health/live").json()
