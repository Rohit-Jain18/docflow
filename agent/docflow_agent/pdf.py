"""
PDF validation and metadata extraction module for the Docflow Windows Agent.

Implements the PDF validation rules specified in docs/AGENT_SPEC.md §4:
- Enforces non-zero size and configured maximum (default: 50 MiB).
- Validates PDF signature (%PDF-) and EOF marker (%%EOF) without reading the entire
  file into memory.
- Calculates SHA-256 hash incrementally in 64 KiB chunks.
- Re-checks file metadata (size and mtime_ns) after reading to detect modifications.
- Produces a typed ValidationResult with local metadata only.
- Redacts phone numbers and filenames from log messages.
"""

from __future__ import annotations

import hashlib
import logging
import pathlib
from dataclasses import dataclass

from docflow_agent.recipient import mask_phone, validate_recipient

logger = logging.getLogger(__name__)

# Default maximum PDF size: 50 MiB
DEFAULT_MAX_PDF_SIZE_BYTES = 52_428_800
CHUNK_SIZE = 64 * 1024  # 64 KiB


@dataclass(frozen=True)
class ValidationResult:
    """Typed result of PDF and recipient validation."""

    source_path: pathlib.Path
    source_basename: str
    recipient_phone_e164: str | None
    content_sha256: str | None
    file_size_bytes: int
    mtime_ns: int
    is_valid: bool
    reason_code: str | None = None


def validate_pdf(
    path: pathlib.Path | str,
    *,
    max_size_bytes: int = DEFAULT_MAX_PDF_SIZE_BYTES,
    default_region: str = "IN",
) -> ValidationResult:
    """Validate a candidate PDF file and extract recipient and content metadata.

    Args:
        path: Path to the PDF file.
        max_size_bytes: Maximum allowed size in bytes (default 50 MiB).
        default_region: Default country code for national phone numbers (default 'IN').

    Returns:
        ValidationResult containing normalized recipient, SHA-256 hash, size, and outcome.
    """
    file_path = pathlib.Path(path)
    basename = file_path.name

    # 1. Filename & recipient validation
    is_rec_valid, recipient_e164, rec_reason = validate_recipient(
        basename, default_region=default_region
    )

    # Gather initial stat if possible
    initial_size = 0
    initial_mtime_ns = 0
    try:
        stat = file_path.stat()
        initial_size = stat.st_size
        initial_mtime_ns = stat.st_mtime_ns
    except FileNotFoundError:
        return ValidationResult(
            source_path=file_path,
            source_basename=basename,
            recipient_phone_e164=recipient_e164,
            content_sha256=None,
            file_size_bytes=0,
            mtime_ns=0,
            is_valid=False,
            reason_code="source_file_unavailable",
        )
    except OSError:
        return ValidationResult(
            source_path=file_path,
            source_basename=basename,
            recipient_phone_e164=recipient_e164,
            content_sha256=None,
            file_size_bytes=0,
            mtime_ns=0,
            is_valid=False,
            reason_code="source_file_unavailable",
        )

    # If recipient validation failed, report invalid_filename or invalid_phone
    if not is_rec_valid:
        return ValidationResult(
            source_path=file_path,
            source_basename=basename,
            recipient_phone_e164=None,
            content_sha256=None,
            file_size_bytes=initial_size,
            mtime_ns=initial_mtime_ns,
            is_valid=False,
            reason_code=rec_reason,
        )

    # 2. File size validation
    if initial_size == 0:
        return ValidationResult(
            source_path=file_path,
            source_basename=basename,
            recipient_phone_e164=recipient_e164,
            content_sha256=None,
            file_size_bytes=0,
            mtime_ns=initial_mtime_ns,
            is_valid=False,
            reason_code="empty_file",
        )

    if initial_size > max_size_bytes:
        return ValidationResult(
            source_path=file_path,
            source_basename=basename,
            recipient_phone_e164=recipient_e164,
            content_sha256=None,
            file_size_bytes=initial_size,
            mtime_ns=initial_mtime_ns,
            is_valid=False,
            reason_code="file_too_large",
        )

    # 3. Structure check and incremental SHA-256 calculation
    try:
        with open(file_path, "rb") as f:
            # Header check: look for %PDF- in the first 1024 bytes
            header = f.read(min(1024, initial_size))
            if b"%PDF-" not in header:
                return ValidationResult(
                    source_path=file_path,
                    source_basename=basename,
                    recipient_phone_e164=recipient_e164,
                    content_sha256=None,
                    file_size_bytes=initial_size,
                    mtime_ns=initial_mtime_ns,
                    is_valid=False,
                    reason_code="invalid_pdf",
                )

            # Trailer check: look for %%EOF in the last 1024 bytes
            seek_pos = max(0, initial_size - 1024)
            f.seek(seek_pos)
            trailer = f.read()
            if b"%%EOF" not in trailer:
                return ValidationResult(
                    source_path=file_path,
                    source_basename=basename,
                    recipient_phone_e164=recipient_e164,
                    content_sha256=None,
                    file_size_bytes=initial_size,
                    mtime_ns=initial_mtime_ns,
                    is_valid=False,
                    reason_code="invalid_pdf",
                )

            # Incremental SHA-256 calculation
            f.seek(0)
            hasher = hashlib.sha256()
            bytes_read = 0
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
                bytes_read += len(chunk)

    except FileNotFoundError:
        return ValidationResult(
            source_path=file_path,
            source_basename=basename,
            recipient_phone_e164=recipient_e164,
            content_sha256=None,
            file_size_bytes=initial_size,
            mtime_ns=initial_mtime_ns,
            is_valid=False,
            reason_code="source_file_unavailable",
        )
    except (PermissionError, OSError) as exc:
        logger.warning("Error reading file during validation: %s", type(exc).__name__)
        return ValidationResult(
            source_path=file_path,
            source_basename=basename,
            recipient_phone_e164=recipient_e164,
            content_sha256=None,
            file_size_bytes=initial_size,
            mtime_ns=initial_mtime_ns,
            is_valid=False,
            reason_code="source_file_unavailable",
        )

    # 4. Check for concurrent modification during read
    if bytes_read != initial_size:
        return ValidationResult(
            source_path=file_path,
            source_basename=basename,
            recipient_phone_e164=recipient_e164,
            content_sha256=None,
            file_size_bytes=bytes_read,
            mtime_ns=initial_mtime_ns,
            is_valid=False,
            reason_code="file_modified_during_validation",
        )

    try:
        post_stat = file_path.stat()
        if (
            post_stat.st_size != initial_size
            or post_stat.st_mtime_ns != initial_mtime_ns
        ):
            return ValidationResult(
                source_path=file_path,
                source_basename=basename,
                recipient_phone_e164=recipient_e164,
                content_sha256=None,
                file_size_bytes=post_stat.st_size,
                mtime_ns=post_stat.st_mtime_ns,
                is_valid=False,
                reason_code="file_modified_during_validation",
            )
    except OSError:
        pass  # If post-stat fails after successful read, we accept the bytes read

    sha256_hex = hasher.hexdigest()
    masked = mask_phone(recipient_e164 or "")
    logger.debug(
        "Validated candidate PDF (recipient: %s, size: %d bytes, sha256: %s...)",
        masked,
        initial_size,
        sha256_hex[:8],
    )

    return ValidationResult(
        source_path=file_path,
        source_basename=basename,
        recipient_phone_e164=recipient_e164,
        content_sha256=sha256_hex,
        file_size_bytes=initial_size,
        mtime_ns=initial_mtime_ns,
        is_valid=True,
        reason_code=None,
    )
