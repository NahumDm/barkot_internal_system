"""Pagination defaults (spec §20.2: every list endpoint is paginated).

Page-number pagination rather than cursor pagination: Barkot lists are keyed by
date and id, and staff need to jump to "page 3" when reconciling against a
paper register. Cursor pagination would silently break that workflow.
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

    def get_paginated_response(self, data: Any) -> Response:
        """Return the standard DRF envelope plus the resolved page size.

        The resolved ``page_size`` is included so the frontend can show
        "showing 20 of N" without recomputing the server default.

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
