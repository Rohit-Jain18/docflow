"""
Docflow Client IP Resolution Utilities.

Enforces:
  - Default rejection of untrusted client-supplied X-Forwarded-For headers.
  - Safe fallback to actual REMOTE_ADDR when directly reachable.
  - Forwarded IP resolution ONLY via explicit, approved trusted-proxy configuration:
      * DOCFLOW_TRUSTED_PROXIES: Iterable of trusted reverse proxy IP addresses or CIDR blocks.
  - A non-zero DOCFLOW_NUM_PROXIES or NUM_PROXIES alone NEVER authorizes forwarded headers.
  - Strict right-to-left traversal of proxy chains to extract the originating client IP.
  - Strict validation of IPv4/IPv6 address syntax.
  - Unified resolution for both DRF rate throttling and device telemetry.
"""

import ipaddress
from typing import Optional, Set

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def is_valid_ip(ip_str: Optional[str]) -> bool:
    """Return True if ip_str is a syntactically valid IPv4 or IPv6 address."""
    if not ip_str or not isinstance(ip_str, str):
        return False
    try:
        ipaddress.ip_address(ip_str.strip())
        return True
    except (ValueError, TypeError):
        return False


def validate_trusted_proxy_entry(entry: str) -> None:
    """
    Validate that an entry is a syntactically valid IPv4/IPv6 address or CIDR network.
    Raises ImproperlyConfigured on malformed entries or open wildcard networks (0.0.0.0/0).
    """
    clean = str(entry).strip()
    if not clean:
        raise ImproperlyConfigured("[Docflow] DOCFLOW_TRUSTED_PROXIES contains empty entry.")
    try:
        if "/" in clean:
            net = ipaddress.ip_network(clean, strict=False)
            if net.prefixlen == 0:
                raise ImproperlyConfigured(
                    f"[Docflow] Insecure trusted proxy wildcard range '{clean}' in DOCFLOW_TRUSTED_PROXIES is forbidden."
                )
        else:
            ipaddress.ip_address(clean)
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"[Docflow] Invalid trusted proxy address or CIDR in DOCFLOW_TRUSTED_PROXIES: '{clean}'."
        ) from exc


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
      2. Non-zero proxy count alone:
         A non-zero DOCFLOW_NUM_PROXIES or NUM_PROXIES alone never authorizes
         forwarded headers. Fails closed to REMOTE_ADDR.
      3. Explicit trusted proxies (DOCFLOW_TRUSTED_PROXIES):
         Only if REMOTE_ADDR matches an entry in DOCFLOW_TRUSTED_PROXIES, parse X-Forwarded-For.
         Traverse the proxy chain from right to left, skipping trusted proxies,
         to extract the originating client IP.
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

    # If no trusted proxies are explicitly configured, always return REMOTE_ADDR.
    # A non-zero DOCFLOW_NUM_PROXIES alone must never authorize forwarded headers.
    if not trusted_proxies:
        return remote_addr

    # If REMOTE_ADDR does not match an explicitly trusted proxy, ignore XFF
    if not remote_addr or not is_trusted_proxy(remote_addr, trusted_proxies):
        return remote_addr

    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if not xff or not isinstance(xff, str):
        return remote_addr

    addrs = [ip.strip() for ip in xff.split(",") if ip.strip()]
    if not addrs:
        return remote_addr

    # Walk backwards from the rightmost proxy, skipping trusted proxies
    for ip in reversed(addrs):
        if not is_trusted_proxy(ip, trusted_proxies) and is_valid_ip(ip):
            return ip

    return remote_addr

