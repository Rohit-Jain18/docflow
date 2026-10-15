"""
In-Memory Access Token Management and Rotating Refresh Token Lifecycle.

Implements the token management requirements specified in:
- docs/AGENT_SPEC.md § 2 (Device Activation and Credentials)
- docs/API_CONTRACTS.md § 3 (POST /api/v1/agent/auth/refresh)
- docs/SECURITY.md § 3 (Credential and Token Storage)

Responsibilities:
1. Store rotating refresh token in OS-backed CredentialStore (Windows Credential Manager / DPAPI).
2. Maintain short-lived access token strictly in process memory (never persisted to SQLite or disk).
3. Coordinate thread-safe refresh token rotation against POST /api/v1/agent/auth/refresh without bearer auth.
4. Enforce strict UTC ISO 8601 Z timestamp validation on all expiry fields.
5. Persist the rotated refresh token to secure storage BEFORE publishing the new in-memory access token.
6. Provide early proactive refresh before access token expiry using a configurable safety buffer.
7. Fail closed on invalid/revoked credentials, rate limits, schema errors, or storage failures.
8. Treat timeouts and ambiguous network errors as non-retryable to prevent triggering server-side
   token-reuse revocation policies.
9. Zero leakage of access tokens, refresh secrets, or raw server payloads in logs, exceptions, or representations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
from typing import TYPE_CHECKING, Any, Callable

from docflow_agent.client import (
    ApiClient,
    ApiAuthenticationError,
    ApiConflictError,
    ApiConnectionError,
    ApiPayloadError,
    ApiRateLimitError,
    ApiResponseError,
    ApiTimeoutError,
)
from docflow_agent.credentials import CredentialStore, get_credential_store

logger = logging.getLogger(__name__)

# Key used in CredentialStore for the rotating refresh credential
REFRESH_TOKEN_KEY = "device_refresh_token"

# Endpoint per docs/API_CONTRACTS.md § 3
REFRESH_ENDPOINT = "/api/v1/agent/auth/refresh"

# Default proactive refresh window before expiry (in seconds)
DEFAULT_SAFETY_WINDOW_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TokenError(Exception):
    """Base exception for all token manager operations."""

    def __init__(
        self,
        message: str,
        code: str = "token_error",
        request_id: str | None = None,
        recoverable: bool = False,
    ) -> None:
        self.message = message
        self.code = code
        self.request_id = request_id
        self.recoverable = recoverable
        super().__init__(message)

    def __repr__(self) -> str:
        parts = [f"code={self.code!r}", f"recoverable={self.recoverable!r}"]
        if self.request_id:
            parts.append(f"request_id={self.request_id!r}")
        return f"{self.__class__.__name__}({', '.join(parts)})"


class TokenMissingError(TokenError):
    """Raised when no refresh token exists in CredentialStore (unactivated device)."""


class TokenAuthenticationError(TokenError):
    """Raised when refresh token is invalid, expired, revoked, or device inactive (HTTP 401)."""


class TokenReuseConflictError(TokenError):
    """Raised when rotated token reuse is detected on server and all credentials revoked (HTTP 409)."""


class TokenRateLimitedError(TokenError):
    """Raised when refresh requests are rate-limited by the server (HTTP 429)."""

    def __init__(
        self,
        message: str,
        code: str = "rate_limited",
        request_id: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message, code=code, request_id=request_id, recoverable=True)

    def __repr__(self) -> str:
        parts = [f"code={self.code!r}", f"recoverable={self.recoverable!r}"]
        if self.retry_after is not None:
            parts.append(f"retry_after={self.retry_after!r}")
        if self.request_id:
            parts.append(f"request_id={self.request_id!r}")
        return f"{self.__class__.__name__}({', '.join(parts)})"


class TokenValidationError(TokenError):
    """Raised when the backend refresh response schema or timestamps are invalid."""


class TokenStorageError(TokenError):
    """Raised when reading or writing credentials in CredentialStore fails."""


class TokenRotationAmbiguousError(TokenError):
    """Raised when rotation request times out or suffers a network failure.

    Rotation may have succeeded on the server. Automatic retry with the same
    refresh token is blocked to prevent triggering the server's token reuse
    theft detection policy.
    """


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TokenStatus:
    """Safe, non-secret summary of current token state."""

    has_access_token: bool
    access_token_expires_at: datetime | None
    refresh_token_expires_at: datetime | None
    is_valid: bool
    is_ambiguous: bool

    def __repr__(self) -> str:
        return (
            f"TokenStatus(has_access_token={self.has_access_token}, "
            f"access_token_expires_at={self.access_token_expires_at.isoformat() if self.access_token_expires_at else None}, "
            f"is_valid={self.is_valid}, "
            f"is_ambiguous={self.is_ambiguous})"
        )


@dataclass(frozen=True)
class _ValidatedRefreshPayload:
    """Internal validated payload received from refresh exchange."""

    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime


# ---------------------------------------------------------------------------
# Timestamp Validation Helper
# ---------------------------------------------------------------------------

def _parse_utc_iso_timestamp(raw_val: Any, field_name: str) -> datetime:
    """Parse and validate an ISO 8601 UTC timestamp ending in 'Z'.

    Per docs/API_CONTRACTS.md § 1 & § 3:
    Rejects:
      - None, non-strings, or empty/whitespace strings
      - Naive timestamps without timezone
      - Non-UTC offset strings (e.g. +05:30, -04:00, or non-Z UTC offsets)
      - Malformed or invalid ISO 8601 timestamp representations
    Never echoes raw server-controlled values in exception messages.
    """
    if not isinstance(raw_val, str) or not raw_val.strip():
        raise TokenValidationError(
            f"Field '{field_name}' is missing or empty.",
            code="missing_timestamp",
        )
    cleaned = raw_val.strip()
    if not cleaned.endswith("Z") or "T" not in cleaned:
        raise TokenValidationError(
            f"Field '{field_name}' must be an ISO 8601 UTC timestamp ending in 'Z'.",
            code="invalid_timestamp",
        )
    try:
        dt = datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        raise TokenValidationError(
            f"Field '{field_name}' is not a valid ISO 8601 timestamp.",
            code="invalid_timestamp",
        ) from None

    if dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise TokenValidationError(
            f"Field '{field_name}' must be a UTC timestamp.",
            code="invalid_timestamp",
        )
    return dt


# ---------------------------------------------------------------------------
# Token Manager
# ---------------------------------------------------------------------------

class TokenManager:
    """Coordinates in-memory access token lifecycle and rotating refresh credentials.

    Features:
    - Thread-safe access token retrieval with double-checked locking on rotation.
    - Proactive early refresh within a configurable safety window before expiry.
    - Strict response validation (UTC Z timestamps) before updating credentials.
    - New rotating refresh token is persisted to CredentialStore BEFORE in-memory
      access token is updated.
    - Fails closed on invalid credentials, rate limits, storage errors, and schema failures.
    - Blocks automatic retry after timeout/network error to prevent triggering server-side
      token-reuse detection.
    - Zero secret leakage in logs, exceptions, or string representations.
    """

    def __init__(
        self,
        client: ApiClient,
        *,
        credential_store: CredentialStore | None = None,
        safety_window_seconds: float = DEFAULT_SAFETY_WINDOW_SECONDS,
        initial_access_token: str | None = None,
        initial_access_token_expires_at: datetime | None = None,
        initial_refresh_token_expires_at: datetime | None = None,
        time_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._credential_store = credential_store or get_credential_store()
        self._safety_window_seconds = max(0.0, float(safety_window_seconds))
        self._time_provider = time_provider or (lambda: datetime.now(timezone.utc))

        self._lock = threading.RLock()

        # In-memory access token state (never written to disk or SQLite)
        self._access_token: str | None = initial_access_token
        self._access_token_expires_at: datetime | None = initial_access_token_expires_at
        self._refresh_token_expires_at: datetime | None = initial_refresh_token_expires_at

        # Flag set when a rotation call timed out or failed ambiguously over network
        self._is_ambiguous: bool = False

    @property
    def safety_window_seconds(self) -> float:
        """Configured safety buffer before access token expiration (in seconds)."""
        return self._safety_window_seconds

    @property
    def credential_store(self) -> CredentialStore:
        """Return the backing CredentialStore."""
        return self._credential_store

    def is_access_token_valid(self) -> bool:
        """Check whether the in-memory access token exists and is outside the safety buffer."""
        with self._lock:
            return self._is_access_token_valid_under_lock()

    def _is_access_token_valid_under_lock(self) -> bool:
        """Internal validity check called while holding self._lock."""
        if not self._access_token or self._access_token_expires_at is None:
            return False
        if self._is_ambiguous:
            return False

        now = self._time_provider()
        # If expiry datetime is naive, treat as invalid
        if self._access_token_expires_at.tzinfo is None:
            return False

        remaining_seconds = (self._access_token_expires_at - now).total_seconds()
        return remaining_seconds > self._safety_window_seconds

    def get_access_token_expires_at(self) -> datetime | None:
        """Return the UTC expiry datetime of current in-memory access token, or None."""
        with self._lock:
            return self._access_token_expires_at

    def get_refresh_token_expires_at(self) -> datetime | None:
        """Return the UTC expiry datetime of current refresh token, or None."""
        with self._lock:
            return self._refresh_token_expires_at

    def get_token_status(self) -> TokenStatus:
        """Return a safe, non-secret summary of current token state."""
        with self._lock:
            return TokenStatus(
                has_access_token=bool(self._access_token),
                access_token_expires_at=self._access_token_expires_at,
                refresh_token_expires_at=self._refresh_token_expires_at,
                is_valid=self._is_access_token_valid_under_lock(),
                is_ambiguous=self._is_ambiguous,
            )

    def set_initial_tokens(
        self,
        access_token: str,
        access_token_expires_at: datetime,
        refresh_token_expires_at: datetime | None = None,
    ) -> None:
        """Initialize in-memory token state (e.g. immediately after initial device activation)."""
        if not isinstance(access_token, str) or not access_token.strip():
            raise TokenValidationError("Access token must be a non-empty string.", code="invalid_token")

        with self._lock:
            self._access_token = access_token.strip()
            self._access_token_expires_at = access_token_expires_at
            self._refresh_token_expires_at = refresh_token_expires_at
            self._is_ambiguous = False

    def invalidate(self) -> None:
        """Clear in-memory access token state (e.g. on revocation or unrecoverable error)."""
        with self._lock:
            self._access_token = None
            self._access_token_expires_at = None
            self._refresh_token_expires_at = None

    def reset_ambiguity(self) -> None:
        """Reset ambiguous rotation state (e.g. after operator resolves device credentials)."""
        with self._lock:
            self._is_ambiguous = False

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        """Obtain a valid access token, rotating the refresh token if necessary.

        This method conforms to the TokenProvider signature ``Callable[[], str | None]``
        expected by ApiClient.

        Args:
            force_refresh: If True, rotate credentials immediately even if the
                current access token is still within its validity window.

        Returns:
            Valid access token string.

        Raises:
            TokenMissingError: No refresh token in CredentialStore.
            TokenAuthenticationError: Refresh credential expired or revoked (401).
            TokenReuseConflictError: Token reuse detected on server (409).
            TokenRateLimitedError: Refresh requests throttled (429).
            TokenRotationAmbiguousError: Request timed out or network failed; automatic
                retry is blocked to prevent token reuse theft triggers.
            TokenValidationError: Backend response schema or timestamp invalid.
            TokenStorageError: Secure storage read or write failed.
        """
        # Fast path: if token is already valid and force_refresh is not requested,
        # return immediately without taking exclusive write locks
        with self._lock:
            if not force_refresh and self._is_access_token_valid_under_lock():
                assert self._access_token is not None
                return self._access_token

        # Slow path: acquire lock and rotate
        with self._lock:
            # Double-check validity after acquiring lock (another thread may have rotated)
            if not force_refresh and self._is_access_token_valid_under_lock():
                assert self._access_token is not None
                return self._access_token

            # If rotation is currently ambiguous from a prior timeout, fail closed
            if self._is_ambiguous:
                logger.error("Token rotation blocked: previous rotation attempt timed out ambiguously")
                raise TokenRotationAmbiguousError(
                    "Token rotation state is ambiguous due to a previous network timeout or connection failure. "
                    "Automatic reuse of the potentially consumed refresh token is blocked to prevent credential revocation.",
                    code="ambiguous_rotation_state",
                    recoverable=False,
                )

            # Invalidate in-memory access token immediately so that failures NEVER expose stale tokens
            self.invalidate()

            # Perform atomic rotation
            return self._rotate_under_lock()

    def _rotate_under_lock(self) -> str:
        """Perform refresh rotation exchange under self._lock."""
        # 1. Read current refresh token from secure CredentialStore
        try:
            current_refresh = self._credential_store.get(REFRESH_TOKEN_KEY)
        except Exception as exc:
            logger.error("Failed to read refresh token from secure credential store")
            raise TokenStorageError(
                "Failed to read refresh token from secure credential store.",
                code="storage_read_error",
                recoverable=False,
            ) from exc

        if not current_refresh or not isinstance(current_refresh, str) or not current_refresh.strip():
            logger.warning("No refresh token stored in credential store; device requires activation")
            raise TokenMissingError(
                "No refresh token available in secure credential store. Device must be activated first.",
                code="refresh_token_missing",
                recoverable=False,
            )

        current_refresh = current_refresh.strip()

        # 2. Call POST /api/v1/agent/auth/refresh without bearer authentication
        logger.info("Initiating refresh token rotation with API backend")
        try:
            response_data = self._client.post(
                REFRESH_ENDPOINT,
                json={"refresh_token": current_refresh},
                authenticated=False,
            )
        except ApiTimeoutError as exc:
            # Ambiguous outcome: rotation may have succeeded on the server.
            # Mark state as ambiguous and block automatic retries.
            self._is_ambiguous = True
            logger.error("Refresh request timed out; rotation status is ambiguous")
            raise TokenRotationAmbiguousError(
                "Refresh request timed out. Rotation may have completed on the server; "
                "automatic retry with this token is blocked to prevent triggering credential revocation.",
                code="rotation_timeout",
                request_id=getattr(exc, "request_id", None),
                recoverable=False,
            ) from exc
        except ApiConnectionError as exc:
            # Network connection error during exchange: ambiguous if request reached server
            self._is_ambiguous = True
            logger.error("Network connection failed during refresh request; rotation status is ambiguous")
            raise TokenRotationAmbiguousError(
                "Network connection failed during refresh exchange. Rotation status is ambiguous; "
                "automatic retry with this token is blocked to prevent triggering credential revocation.",
                code="rotation_network_error",
                request_id=getattr(exc, "request_id", None),
                recoverable=False,
            ) from exc
        except ApiRateLimitError as exc:
            # Rate limited: the server did NOT consume the refresh token
            logger.warning("Refresh request throttled by server (retry_after=%s)", exc.retry_after)
            raise TokenRateLimitedError(
                "Token refresh request was rate-limited.",
                code="rate_limited",
                request_id=exc.request_id,
                retry_after=exc.retry_after,
            ) from exc
        except ApiAuthenticationError as exc:
            # 401: Invalid, expired, or revoked refresh credential
            logger.warning("Refresh credential rejected by server (%s)", exc.code)
            raise TokenAuthenticationError(
                "Refresh credential is invalid, expired, or revoked.",
                code="authentication_required",
                request_id=exc.request_id,
                recoverable=False,
            ) from exc
        except ApiConflictError as exc:
            # 409: Token reuse detected! All credentials revoked on server
            logger.critical("Token reuse conflict detected by server; device credentials revoked")
            raise TokenReuseConflictError(
                "Rotated refresh token reuse detected. All active credentials have been revoked.",
                code="state_conflict",
                request_id=exc.request_id,
                recoverable=False,
            ) from exc
        except ApiResponseError as exc:
            logger.warning("Token refresh rejected by server (%s)", exc.code)
            raise TokenValidationError(
                f"Token refresh rejected by server ({exc.code}).",
                code=exc.code,
                request_id=exc.request_id,
                recoverable=False,
            ) from exc
        except ApiPayloadError as exc:
            logger.error("Server returned non-JSON payload during refresh")
            raise TokenValidationError(
                "Server returned malformed non-JSON payload during refresh.",
                code="invalid_response_format",
                recoverable=False,
            ) from exc
        except Exception as exc:
            logger.error("Unexpected failure during token refresh")
            raise TokenError(
                "Unexpected failure during token refresh.",
                code="unexpected_error",
                recoverable=False,
            ) from exc

        # 3. Validate response payload
        validated = self._validate_response_payload(response_data)

        # 4. Persist newly rotated refresh token to secure CredentialStore FIRST
        try:
            self._credential_store.store(REFRESH_TOKEN_KEY, validated.refresh_token)
        except Exception as exc:
            logger.critical("Failed to persist newly rotated refresh token to credential store")
            # Fail closed: Do NOT publish the new access token
            raise TokenStorageError(
                "Failed to persist newly rotated refresh token to secure credential store. Failed closed.",
                code="storage_write_error",
                recoverable=False,
            ) from exc

        # 5. After secure storage succeeds, update in-memory state
        self._access_token = validated.access_token
        self._access_token_expires_at = validated.access_token_expires_at
        self._refresh_token_expires_at = validated.refresh_token_expires_at
        self._is_ambiguous = False

        logger.info(
            "Refresh token rotation successful (access_expires_at=%s, refresh_expires_at=%s)",
            validated.access_token_expires_at.isoformat(),
            validated.refresh_token_expires_at.isoformat(),
        )

        return self._access_token

    def _validate_response_payload(self, data: Any) -> _ValidatedRefreshPayload:
        """Validate all required fields, types, and strict UTC timestamps in response."""
        if not isinstance(data, dict):
            raise TokenValidationError(
                "Refresh response was not a valid JSON object.",
                code="invalid_response_format",
            )

        # 1. access_token
        raw_access = data.get("access_token")
        if not isinstance(raw_access, str) or not raw_access.strip():
            raise TokenValidationError(
                "Refresh response missing valid 'access_token'.",
                code="missing_access_token",
            )

        # 2. refresh_token
        raw_refresh = data.get("refresh_token")
        if not isinstance(raw_refresh, str) or not raw_refresh.strip():
            raise TokenValidationError(
                "Refresh response missing valid 'refresh_token'.",
                code="missing_refresh_token",
            )

        # 3. access_token_expires_at
        access_expires_at = _parse_utc_iso_timestamp(
            data.get("access_token_expires_at"),
            "access_token_expires_at",
        )

        # 4. refresh_token_expires_at
        refresh_expires_at = _parse_utc_iso_timestamp(
            data.get("refresh_token_expires_at"),
            "refresh_token_expires_at",
        )

        return _ValidatedRefreshPayload(
            access_token=raw_access.strip(),
            access_token_expires_at=access_expires_at,
            refresh_token=raw_refresh.strip(),
            refresh_token_expires_at=refresh_expires_at,
        )

    def __repr__(self) -> str:
        with self._lock:
            status = "valid" if self._is_access_token_valid_under_lock() else "invalid_or_expired"
            exp = self._access_token_expires_at.isoformat() if self._access_token_expires_at else "none"
            return f"TokenManager(status={status!r}, access_expires_at={exp!r}, ambiguous={self._is_ambiguous})"
