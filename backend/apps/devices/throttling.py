"""
DRF Throttling for Docflow Agent Authentication APIs.

Enforces:
  - Strict IP-based throttling for sensitive authentication endpoints.
  - Independent rates for activation code exchange and refresh rotation.
  - Never relies on caller-supplied tenant or installation identifiers.
"""

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class ActivationRateThrottle(SimpleRateThrottle):
    """
    IP-based rate throttle for POST /api/v1/agent/activation/exchange.
    Configured via REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["agent_activation"].
    """

    scope = "agent_activation"
    default_rate = "10/minute"

    def get_rate(self):
        rf_settings = getattr(settings, "REST_FRAMEWORK", {})
        rates = rf_settings.get("DEFAULT_THROTTLE_RATES", {})
        if self.scope in rates:
            return rates[self.scope]
        return self.THROTTLE_RATES.get(self.scope, self.default_rate)

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class RefreshRateThrottle(SimpleRateThrottle):
    """
    IP-based rate throttle for POST /api/v1/agent/auth/refresh.
    Configured via REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["agent_refresh"].
    """

    scope = "agent_refresh"
    default_rate = "30/minute"

    def get_rate(self):
        rf_settings = getattr(settings, "REST_FRAMEWORK", {})
        rates = rf_settings.get("DEFAULT_THROTTLE_RATES", {})
        if self.scope in rates:
            return rates[self.scope]
        return self.THROTTLE_RATES.get(self.scope, self.default_rate)

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }
