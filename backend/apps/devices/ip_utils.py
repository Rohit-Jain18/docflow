"""
Docflow Client IP Resolution Utilities.

Enforces:
  - Default rejection of untrusted client-supplied X-Forwarded-For headers.
  - Safe fallback to actual REMOTE_ADDR when directly reachable.
  - Forwarded IP resolution ONLY via explicit, approved trusted-proxy configuration:
      * DOCFLOW_TRUSTED_PROXIES: Iterable of trusted reverse proxy IP addresses.
      * DOCFLOW_NUM_PROXIES / REST_FRAMEWORK["NUM_PROXIES"]: Number of trusted proxies.
  - Strict validation of IPv4/IPv6 address syntax.
  - Unified resolution for both DRF rate throttling and device telemetry.
"""

import ipaddress
from typing import Optional, Set

from django.conf import settings


def is_valid_ip(ip_str: Optional[str]) -> bool:
    """Return True if ip_str is a syntactically valid IPv4 or IPv6 address."""
    if not ip_str or not isinstance(ip_str, str):
        return False
    try:
        ipaddress.ip_address(ip_str.strip())
        return True
    except (ValueError, TypeError):
        return False


def get_trusted_proxy_ips() -> Set[str]:
    """Retrieve the set of explicitly configured trusted reverse proxy IPs."""
    raw = getattr(settings, "DOCFLOW_TRUSTED_PROXIES", None)
    if not raw:
        return set()
    if isinstance(raw, (list, tuple, set)):
        return {str(ip).strip() for ip in raw if str(ip).strip()}
    if isinstance(raw, str):
        return {ip.strip() for ip in raw.split(",") if ip.strip()}
    return set()


def is_trusted_proxy(ip_str: Optional[str], trusted_proxies: Set[str]) -> bool:
    """Return True if ip_str matches an explicitly configured trusted proxy IP or CIDR network."""
    if not ip_str or not trusted_proxies:
        return False
    if ip_str in trusted_proxies:
        return True
    try:
        addr = ipaddress.ip_address(ip_str)
        for entry in trusted_proxies:
            if "/" in entry:
                try:
                    if addr in ipaddress.ip_network(entry, strict=False):
                        return True
                except ValueError:
                    continue
            else:
                try:
                    if addr == ipaddress.ip_address(entry):
                        return True
                except ValueError:
                    continue
    except (ValueError, TypeError):
        return False
    return False


def get_client_ip(request) -> Optional[str]:
    """
    Resolve client IP address safely according to trusted-proxy configuration.

    Policy:
      1. Default (no trusted proxies configured):
         Always return REMOTE_ADDR. Any X-Forwarded-For header is ignored.
      2. Explicit trusted proxies (DOCFLOW_TRUSTED_PROXIES):
         Only if REMOTE_ADDR is in DOCFLOW_TRUSTED_PROXIES, parse X-Forwarded-For.
         Traverse the proxy chain from right to left, skipping trusted proxies,
         to extract the originating client IP.
      3. Fixed proxy count (DOCFLOW_NUM_PROXIES / REST_FRAMEWORK["NUM_PROXIES"]):
         If num_proxies > 0 and no explicit list is configured, take the IP at
         index -num_proxies from X-Forwarded-For.
      4. Fallback:
         If forwarded IP is invalid, absent, or REMOTE_ADDR is untrusted,
         return REMOTE_ADDR if valid, else None.
    """
    if not request or not hasattr(request, "META"):
        return None

    remote_addr = request.META.get("REMOTE_ADDR")
    if remote_addr:
        remote_addr = remote_addr.strip()
    if not is_valid_ip(remote_addr):
        remote_addr = None

    trusted_proxies = get_trusted_proxy_ips()

    rf_settings = getattr(settings, "REST_FRAMEWORK", {})
    num_proxies = getattr(settings, "DOCFLOW_NUM_PROXIES", None)
    if num_proxies is None:
        num_proxies = rf_settings.get("NUM_PROXIES", 0)

    # If no trusted proxy setup is active, use actual REMOTE_ADDR
    if not trusted_proxies and (num_proxies is None or num_proxies <= 0):
        return remote_addr

    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if not xff or not isinstance(xff, str):
        return remote_addr

    addrs = [ip.strip() for ip in xff.split(",") if ip.strip()]
    if not addrs:
        return remote_addr

    # If an explicit trusted proxy list is configured
    if trusted_proxies:
        # REMOTE_ADDR must be a trusted proxy; otherwise XFF is untrusted
        if not remote_addr or not is_trusted_proxy(remote_addr, trusted_proxies):
            return remote_addr

        # Walk backwards from the rightmost proxy, skipping trusted proxies
        for ip in reversed(addrs):
            if not is_trusted_proxy(ip, trusted_proxies) and is_valid_ip(ip):
                return ip
        return remote_addr

    # If fixed num_proxies is configured
    if num_proxies and num_proxies > 0:
        index = -min(num_proxies, len(addrs))
        candidate = addrs[index]
        if is_valid_ip(candidate):
            return candidate

    return remote_addr
