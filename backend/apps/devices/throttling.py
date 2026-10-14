"""
DRF Throttling for Docflow Agent Authentication APIs.

Enforces:
  - Strict IP-based throttling for sensitive authentication endpoints.
  - Independent rates for activation code exchange and refresh rotation.
  - Never relies on caller-supplied tenant or installation identifiers.
"""

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle

from .ip_utils import get_client_ip


class SafeIPRateThrottle(SimpleRateThrottle):
    """
    Base throttle that strictly resolves client identity using Docflow's
    hardened IP resolution policy (get_client_ip). Never trusts spoofed
    forwarded headers unless an explicit trusted-proxy setup is active.
    """

    def get_ident(self, request):
        """Override DRF's default get_ident to use Docflow's hardened IP resolution."""
        ip = get_client_ip(request)
        if ip:
            return ip
        # Fallback to direct REMOTE_ADDR without trusting X-Forwarded-For
        if hasattr(request, "META"):
            remote_addr = request.META.get("REMOTE_ADDR")
            if remote_addr:
                return str(remote_addr).strip()
        return "127.0.0.1"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        if not ident:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class ActivationRateThrottle(SafeIPRateThrottle):
    """
    IP-based rate throttle for POST /api/v1/agent/activation/exchange.
    Configured via REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["agent_activation"].
    Uses hardened client IP resolution policy (never trusts spoofed headers).
    """

    scope = "agent_activation"
    default_rate = "10/minute"

    def get_rate(self):
        rf_settings = getattr(settings, "REST_FRAMEWORK", {})
        rates = rf_settings.get("DEFAULT_THROTTLE_RATES", {})
        if self.scope in rates:
            return rates[self.scope]
        return self.THROTTLE_RATES.get(self.scope, self.default_rate)


class RefreshRateThrottle(SafeIPRateThrottle):
    """
    IP-based rate throttle for POST /api/v1/agent/auth/refresh.
    Configured via REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["agent_refresh"].
    Uses hardened client IP resolution policy (never trusts spoofed headers).
    """

    scope = "agent_refresh"
    default_rate = "30/minute"

    def get_rate(self):
        rf_settings = getattr(settings, "REST_FRAMEWORK", {})
        rates = rf_settings.get("DEFAULT_THROTTLE_RATES", {})
        if self.scope in rates:
            return rates[self.scope]
        return self.THROTTLE_RATES.get(self.scope, self.default_rate)

