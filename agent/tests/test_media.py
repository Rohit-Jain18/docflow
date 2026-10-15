"""
Tests for Temporary Media Expiry Validation and Re-Upload Readiness.

Covers:
- Operational expiry check against configurable safety buffer (default 300s).
- Strict UTC ISO 8601 timestamp parsing.
- Retained local source PDF availability verification (fails closed on missing/empty files with 'source_file_unavailable').
- Standardized attachment filename verification ('Diagnostic_Report.pdf', rejecting phone numbers or arbitrary names).
- Renewal routing through injected MediaRenewalInterface when expired or near buffer.
- Reconcile-before-resend rule: strictly blocks renewal or resend when in 'reconciliation_required'.
"""

from __future__ import annotations

import datetime
from datetime import timedelta, timezone
import pathlib
import pytest

from docflow_agent.media import (
    MediaExpiryValidator,
    MediaReference,
    MediaError,
    SourceFileUnavailableError,
    MediaExpiredError,
    ReconciliationRequiredError,
    STANDARDIZED_ATTACHMENT_FILENAME,
)


class MockMediaRenewalHandler:
    def __init__(self, future_minutes: int = 60):
        self.future_minutes = future_minutes
        self.renew_call_count = 0

    def renew_media_reference(self, source_path: pathlib.Path) -> MediaReference:
        self.renew_call_count += 1
        now = datetime.datetime.now(timezone.utc)
        exp = (now + timedelta(minutes=self.future_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return MediaReference(
            kind="development_download_url",
            url="https://tmpfiles.org/dl/renewed-sample.pdf",
            expires_at=exp,
        )


class TestMediaExpiryValidator:
    def test_is_expired_or_near_expiry(self):
        validator = MediaExpiryValidator(safety_buffer_seconds=300)
        now = datetime.datetime.now(timezone.utc)

        # None / empty / invalid format -> expired
        assert validator.is_expired_or_near_expiry(None, now_dt=now) is True
        assert validator.is_expired_or_near_expiry("", now_dt=now) is True
        assert validator.is_expired_or_near_expiry("not-a-date", now_dt=now) is True

        # Timestamp in past -> expired
        past = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert validator.is_expired_or_near_expiry(past, now_dt=now) is True

        # Timestamp 2 minutes in future (inside 5-minute safety buffer) -> near expiry
        near = (now + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert validator.is_expired_or_near_expiry(near, now_dt=now) is True

        # Timestamp 30 minutes in future (outside safety buffer) -> not expired
        fresh = (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert validator.is_expired_or_near_expiry(fresh, now_dt=now) is False

    def test_validate_source_file_available(self, tmp_path: pathlib.Path):
        validator = MediaExpiryValidator()

        # Valid non-empty file
        valid_file = tmp_path / "report.pdf"
        valid_file.write_bytes(b"%PDF-1.4 content")
        assert validator.validate_source_file_available(valid_file) == valid_file.resolve()

        # Non-existent file
        missing_file = tmp_path / "missing.pdf"
        with pytest.raises(SourceFileUnavailableError) as exc_info:
            validator.validate_source_file_available(missing_file)
        assert exc_info.value.code == "source_file_unavailable"

        # Empty 0-byte file
        empty_file = tmp_path / "empty.pdf"
        empty_file.write_bytes(b"")
        with pytest.raises(SourceFileUnavailableError) as exc_info:
            validator.validate_source_file_available(empty_file)
        assert exc_info.value.code == "source_file_unavailable"

    def test_validate_attachment_filename(self):
        validator = MediaExpiryValidator()

        # Standardized approved name
        assert validator.validate_attachment_filename(STANDARDIZED_ATTACHMENT_FILENAME) == "Diagnostic_Report.pdf"

        # Reject phone-bearing or arbitrary filenames
        with pytest.raises(MediaError) as exc_info:
            validator.validate_attachment_filename("919876543210.pdf")
        assert exc_info.value.code == "invalid_attachment_filename"

        with pytest.raises(MediaError):
            validator.validate_attachment_filename("../secret.pdf")

    def test_prepare_media_unexpired_returns_current(self, tmp_path: pathlib.Path):
        validator = MediaExpiryValidator(safety_buffer_seconds=300)
        source_file = tmp_path / "test.pdf"
        source_file.write_bytes(b"%PDF-1.4 sample")

        now = datetime.datetime.now(timezone.utc)
        fresh_exp = (now + timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        current_ref = MediaReference(
            kind="development_download_url",
            url="https://tmpfiles.org/dl/active.pdf",
            expires_at=fresh_exp,
        )

        handler = MockMediaRenewalHandler()
        result = validator.prepare_media_reference(
            source_path=source_file,
            current_reference=current_ref,
            job_status="uploaded",
            renewal_handler=handler,
            now_dt=now,
        )

        assert result == current_ref
        assert handler.renew_call_count == 0

    def test_prepare_media_expired_triggers_renewal(self, tmp_path: pathlib.Path):
        validator = MediaExpiryValidator(safety_buffer_seconds=300)
        source_file = tmp_path / "test.pdf"
        source_file.write_bytes(b"%PDF-1.4 sample")

        now = datetime.datetime.now(timezone.utc)
        expired_exp = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_ref = MediaReference(
            kind="development_download_url",
            url="https://tmpfiles.org/dl/expired.pdf",
            expires_at=expired_exp,
        )

        handler = MockMediaRenewalHandler(future_minutes=60)
        result = validator.prepare_media_reference(
            source_path=source_file,
            current_reference=old_ref,
            job_status="uploaded",
            renewal_handler=handler,
            now_dt=now,
        )

        assert handler.renew_call_count == 1
        assert result.url == "https://tmpfiles.org/dl/renewed-sample.pdf"
        assert result.expires_at is not None
        assert validator.is_expired_or_near_expiry(result.expires_at, now_dt=now) is False

    def test_prepare_media_missing_source_fails_closed(self, tmp_path: pathlib.Path):
        validator = MediaExpiryValidator()
        missing_file = tmp_path / "deleted_source.pdf"

        handler = MockMediaRenewalHandler()
        with pytest.raises(SourceFileUnavailableError) as exc_info:
            validator.prepare_media_reference(
                source_path=missing_file,
                current_reference=None,
                job_status="uploaded",
                renewal_handler=handler,
            )
        assert exc_info.value.code == "source_file_unavailable"
        assert handler.renew_call_count == 0

    def test_reconciliation_required_blocks_renewal_even_if_expired(self, tmp_path: pathlib.Path):
        validator = MediaExpiryValidator()
        source_file = tmp_path / "test.pdf"
        source_file.write_bytes(b"%PDF-1.4 sample")

        now = datetime.datetime.now(timezone.utc)
        expired_exp = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        expired_ref = MediaReference(
            kind="development_download_url",
            url="https://tmpfiles.org/dl/sample.pdf",
            expires_at=expired_exp,
        )

        handler = MockMediaRenewalHandler()
        with pytest.raises(ReconciliationRequiredError) as exc_info:
            validator.prepare_media_reference(
                source_path=source_file,
                current_reference=expired_ref,
                job_status="reconciliation_required",
                renewal_handler=handler,
                now_dt=now,
            )
        assert exc_info.value.code == "reconciliation_required"
        assert handler.renew_call_count == 0
