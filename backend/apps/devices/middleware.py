"""
Middleware for Docflow API request tracing and correlation.

Enforces:
  - Accepts or generates opaque, secret-free X-Request-ID.
  - Attaches request_id to request object for service and audit access.
  - Ensures every HTTP response carries X-Request-ID header.
"""

import re
import uuid

REQUEST_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")


def generate_request_id() -> str:
    """Generate a high-entropy opaque request identifier."""
    return f"req_{uuid.uuid4().hex[:16]}"


class DocflowRequestIDMiddleware:
    """
    Middleware ensuring all requests have a valid request_id and all responses
    include the X-Request-ID header per API_CONTRACTS.md §1.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw_header = request.headers.get("X-Request-ID") or request.META.get("HTTP_X_REQUEST_ID", "")
        raw_header = raw_header.strip()

        if raw_header and REQUEST_ID_REGEX.match(raw_header):
            request_id = raw_header
        else:
            request_id = generate_request_id()

        request.request_id = request_id
        request._request_id = request_id

        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response
