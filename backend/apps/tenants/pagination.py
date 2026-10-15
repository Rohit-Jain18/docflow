"""
Pagination classes for Docflow APIs (Phase 1, Task 3D).

Enforces:
  - Stable paginated response shape: results, page, page_size, total.
  - Default page size: 25.
  - Maximum page size: 100.
  - Query parameter control: page, page_size.
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class DocflowPagination(PageNumberPagination):
    """
    Standard pagination class for Docflow collection endpoints.

    Produces response payload:
    {
      "results": [...],
      "page": 1,
      "page_size": 25,
      "total": 42
    }
    """

    page_size = 25
    page_query_param = "page"
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        assert self.page is not None
        assert self.request is not None
        return Response({
            "results": data,
            "page": self.page.number,
            "page_size": self.get_page_size(self.request),
            "total": self.page.paginator.count,
        })
