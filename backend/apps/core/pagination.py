"""Pagination defaults (spec §20.2: every list endpoint is paginated).

Page-number pagination rather than cursor pagination: Barkot lists are keyed by
date and id, and staff need to jump to "page 3" when reconciling against a
paper register. Cursor pagination would silently break that workflow.

Two behaviours here are stricter than DRF's defaults, and both are deliberate:

- The cap of 200 exists so one request cannot ask for an entire year of sales
  rows and exhaust the API container's memory (spec §22.2 resource
  constraints). A request above the cap is *capped*, not refused, so a client
  that asks for too much still gets an answer.
- An unparseable or nonsensical ``page_size`` is a 400 rather than a silent
  fallback to the default. DRF catches ``ValueError`` and hands back the
  default page size, so ``?page_size=abc`` returns 200 with 20 rows: the
  request looks successful and the rows look complete, and a reconciliation
  report comes out short with no indication of why.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class BarkotPagination(PageNumberPagination):
    """Page-number pagination with a 20-item default page size.

    The cap of 200 exists so one request cannot ask for an entire year of sales
    rows and exhaust the API container's memory (spec §22.2 resource
    constraints).
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200
    page_query_param = "page"

    def get_page_size(self, request: Any) -> int:
        """Resolve the requested page size, rejecting nonsense rather than ignoring it.

        Args:
            request: The incoming request.

        Returns:
            The page size to use, capped at :attr:`max_page_size`.

        Raises:
            ValidationError: If ``page_size`` is present but is not a positive
                integer. Silently substituting the default would return a
                successful response holding fewer rows than the caller asked
                for, which is indistinguishable from complete data.
        """
        raw = request.query_params.get(self.page_size_query_param)
        if raw is None:
            return self.page_size

        try:
            requested = int(raw)
        except (TypeError, ValueError) as exc:
            raise self._invalid_page_size(raw) from exc

        if requested < 1:
            raise self._invalid_page_size(raw)
        return min(requested, self.max_page_size)

    def _invalid_page_size(self, raw: str) -> Exception:
        """Build the validation error for an unusable ``page_size``.

        Args:
            raw: The value the client sent, quoted back so the client can see
                what it actually sent.

        Returns:
            A DRF ``ValidationError`` naming the parameter.
        """
        from rest_framework.exceptions import ValidationError

        return ValidationError({
            self.page_size_query_param: [
                f"'{raw}' is not a valid page size. Send a whole number of 1 or more."
            ]
        })

    def get_paginated_response(self, data: Any) -> Response:
        """Return the standard DRF envelope plus the resolved page size.

        The resolved ``page_size`` is included so the frontend can show
        "showing 20 of N" without recomputing the server default - and, when a
        request was capped, so the client can see that it did not get what it
        asked for.

        Raises:
            RuntimeError: If DRF calls this before :meth:`paginate_queryset`.
                ``page`` and ``request`` are ``None`` until then, and raising
                beats returning a response full of nulls.
        """
        page = self.page
        request = self.request
        if page is None or request is None:
            raise RuntimeError("get_paginated_response() called before paginate_queryset().")

        return Response(
            OrderedDict([
                ("count", page.paginator.count),
                ("page_size", self.get_page_size(request)),
                ("page", page.number),
                ("pages", page.paginator.num_pages),
                ("results", data),
            ])
        )
