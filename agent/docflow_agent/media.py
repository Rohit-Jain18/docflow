"""
Temporary Media Expiry Validation and Re-Upload Readiness Lifecycle Interface.

Implements requirements from:
- docs/AGENT_SPEC.md §§ 4, 7, 8
- docs/DELIVERY_STATE_MACHINE.md §§ 1, 4
- docs/RULES.md (Rules 4, 6, 7)
- docs/ROADMAP.md (Phase 2 deliverables)

Core rules:
1. Provider-independent lifecycle support for temporary media expiry checking.
2. Checks media reference expiry against configured safety buffer (default 300s).
3. If expired or within safety buffer before dispatch, signals renewal required and routes
   through injected renewal handler.
4. Requires local source PDF to be retained and verified intact; if missing/corrupt, fails
   closed with normalized error code 'source_file_unavailable'.
5. Strictly blocks renewal or resend when a job is in 'reconciliation_required'; prior ambiguous
   send attempts must be reconciled first.
6. Validates standardized patient-facing attachment filename ('Diagnostic_Report.pdf'),
   prohibiting phone numbers or local file paths.
7. Phase 2 provides the interface and mock adapters only; live media uploaders belong to Phase 3.
"""

from __future__ import annotations

import dataclasses
import datetime
from datetime import timezone
import logging
import os
import pathlib
import re
from typing import Any, Protocol

logger = logging.getLogger(__name__)

DEFAULT_MEDIA_EXPIRY_BUFFER_SECONDS = 300  # 5 minutes
STANDARDIZED_ATTACHMENT_FILENAME = "Diagnostic_Report.pdf"

_ISO8601_UTC_Z_REGEX = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


class MediaError(Exception):
    """Base exception for media lifecycle errors."""

    def __init__(self, message: str, code: str = "media_error") -> None:
        super().__init__(message)
        self.code = code


class SourceFileUnavailableError(MediaError):
    """Raised when the local source PDF is missing, corrupted, or unreadable when needed."""

    def __init__(self, message: str = "Source PDF file is missing or unavailable.") -> None:
        super().__init__(message, code="source_file_unavailable")


class MediaExpiredError(MediaError):
    """Raised when a media reference is expired or within the safety buffer and cannot be renewed."""

    def __init__(self, message: str = "Media reference has expired or is nearing expiry.") -> None:
        super().__init__(message, code="media_expired")


class ReconciliationRequiredError(MediaError):
    """Raised when an operation is attempted on a job in reconciliation_required before resolution."""

    def __init__(
        self,
        message: str = "Ambiguous send must be reconciled before renewing media or resending.",
    ) -> None:
        super().__init__(message, code="reconciliation_required")


@dataclasses.dataclass(frozen=True)
class MediaReference:
    """Safe, provider-independent representation of an attached media reference."""

    kind: str
    url: str | None = None
    expires_at: str | None = None
    provider_media_id: str | None = None

    def __repr__(self) -> str:
        # Avoid leaking full public download URLs in logs or reprs
        url_repr = f"<{self.kind}>" if self.url else "None"
        return f"MediaReference(kind={self.kind!r}, url={url_repr}, expires_at={self.expires_at!r})"


class MediaRenewalInterface(Protocol):
    """Protocol for injecting a media renewal/re-upload provider (mocked in Phase 2)."""

    def renew_media_reference(self, source_path: pathlib.Path) -> MediaReference:
        """Upload source PDF to media destination and return renewed MediaReference with expires_at."""
        ...


class MediaExpiryValidator:
    """Validates media reference expiry and pre-send readiness."""

    def __init__(
        self,
        safety_buffer_seconds: int = DEFAULT_MEDIA_EXPIRY_BUFFER_SECONDS,
    ) -> None:
        self.safety_buffer_seconds = max(0, int(safety_buffer_seconds))

    def is_expired_or_near_expiry(
        self,
        expires_at_iso: str | None,
        now_dt: datetime.datetime | None = None,
    ) -> bool:
        """Check whether the given UTC ISO 8601 expiry timestamp is expired or within the safety buffer."""
        if not expires_at_iso or not isinstance(expires_at_iso, str):
            # Null or missing expiration is treated as expired/invalid for temporary media
            return True

        val = expires_at_iso.strip()
        if not _ISO8601_UTC_Z_REGEX.match(val):
            return True

        try:
            # Parse strict UTC timestamp
            cleaned = val[:-1] if val.endswith("Z") else val
            exp_dt = datetime.datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return True

        now = now_dt or datetime.datetime.now(timezone.utc)
        threshold = now + datetime.timedelta(seconds=self.safety_buffer_seconds)
        return exp_dt <= threshold

    def validate_source_file_available(self, source_path: pathlib.Path | str) -> pathlib.Path:
        """Verify that the retained local source PDF exists, is a regular file, and is non-empty.

        Fails closed with SourceFileUnavailableError ('source_file_unavailable') if absent or unreadable.
        """
        try:
            path = pathlib.Path(source_path).resolve()
        except Exception as exc:
            raise SourceFileUnavailableError(f"Invalid source file path: {exc}") from exc

        if not path.exists():
            logger.error("Source PDF is missing at '%s'. Failing closed.", path.name)
            raise SourceFileUnavailableError("Source PDF does not exist on disk.")

        if not path.is_file():
            logger.error("Source path '%s' is not a regular file.", path.name)
            raise SourceFileUnavailableError("Source path is not a regular file.")

        try:
            size = path.stat().st_size
            if size <= 0:
                raise SourceFileUnavailableError("Source PDF file is empty (0 bytes).")
        except OSError as exc:
            raise SourceFileUnavailableError(f"Source PDF stat check failed: {exc}") from exc

        return path

    def validate_attachment_filename(self, filename: str) -> str:
        """Validate the standardized patient-facing attachment filename.

        Ensures no phone numbers, path separators, or identifying patient data appear in the attachment name.
        """
        name = str(filename).strip()
        if not name or name != STANDARDIZED_ATTACHMENT_FILENAME:
            # Must strictly match the approved standardized filename
            raise MediaError(
                f"Attachment filename must be '{STANDARDIZED_ATTACHMENT_FILENAME}', got '{name}'.",
                code="invalid_attachment_filename",
            )
        return name

    def prepare_media_reference(
        self,
        source_path: pathlib.Path | str,
        current_reference: MediaReference | None,
        job_status: str,
        renewal_handler: MediaRenewalInterface | None = None,
        now_dt: datetime.datetime | None = None,
    ) -> MediaReference:
        """Ensure a valid, unexpired media reference is ready for dispatch.

        Rules:
        - If job is in 'reconciliation_required', reject renewal/resend until reconciled.
        - Verify local source PDF is intact before evaluating or renewing media.
        - If current reference is unexpired (outside buffer), return it.
        - If expired or near expiry, invoke renewal_handler to re-upload from source PDF.
        """
        # 1. Reconcile-before-resend check
        if job_status == "reconciliation_required":
            logger.warning("Attempted to prepare media while job is in reconciliation_required. Aborting.")
            raise ReconciliationRequiredError()

        # 2. Source file availability check
        valid_path = self.validate_source_file_available(source_path)

        # 3. Expiry evaluation
        if current_reference is not None and current_reference.expires_at:
            if not self.is_expired_or_near_expiry(current_reference.expires_at, now_dt=now_dt):
                return current_reference

        # 4. Renewal required
        logger.info("Media reference expired or nearing safety buffer; initiating renewal from retained PDF.")
        if renewal_handler is None:
            raise MediaExpiredError("Media reference expired and no renewal handler was provided.")

        renewed = renewal_handler.renew_media_reference(valid_path)
        if not renewed or not renewed.expires_at:
            raise MediaError("Renewed media reference is missing required expiration timestamp.")

        if self.is_expired_or_near_expiry(renewed.expires_at, now_dt=now_dt):
            raise MediaError("Renewed media reference expires within the safety buffer threshold.")

        return renewed
