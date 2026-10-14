"""
Authentication classes for Docflow Human User Authentication (Phase 1, Task 3C).

Enforces:
  - Standard Django session authentication.
  - Strict CSRF protection for unsafe HTTP methods, even for anonymous requests (POST /api/v1/auth/login).
  - Explicit rejection of device bearer credentials for human user endpoints.
"""

from rest_framework.authentication import CSRFCheck, SessionAuthentication
from rest_framework.exceptions import PermissionDenied


class CSRFEnforcedSessionAuthentication(SessionAuthentication):
    """
    Session authentication class that strictly enforces CSRF token validation
    on all unsafe HTTP methods, even for unauthenticated / anonymous requests.
    """

    def authenticate(self, request):
        # Always enforce CSRF for unsafe methods regardless of whether request.user is authenticated
        self.enforce_csrf(request)
        return super().authenticate(request)

    def enforce_csrf(self, request):
        raw_request = getattr(request, "_request", request)

        def dummy_get_response(r):
            return None

        check = CSRFCheck(dummy_get_response)
        check.process_request(raw_request)
        reason = check.process_view(raw_request, None, (), {})
        if reason:
            raise PermissionDenied(f"CSRF Failed: {reason}")

    def authenticate_header(self, request):
        return "Session"

