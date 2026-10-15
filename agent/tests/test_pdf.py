"""Tests for docflow_agent.pdf — PDF validation and metadata extraction."""

import hashlib
import os
import pathlib
from typing import Any
import pytest

from docflow_agent.pdf import DEFAULT_MAX_PDF_SIZE_BYTES, ValidationResult, validate_pdf


def _create_mock_pdf(content: bytes = b"mock body") -> bytes:
    """Generate a minimal syntactically valid PDF byte sequence."""
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n" + content + b"\ntrailer\n<<>>\n%%EOF\n"


class TestPDFValidation:
    """Test PDF validation, size checks, signatures, hashes, and change detection."""

    def test_valid_pdf_returns_complete_metadata(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "9876543210.pdf"
        data = _create_mock_pdf(b"Report diagnostic results")
        p.write_bytes(data)

        res = validate_pdf(p)

        assert res.is_valid is True
        assert res.recipient_phone_e164 == "+919876543210"
        assert res.source_path == p
        assert res.source_basename == "9876543210.pdf"
        assert res.file_size_bytes == len(data)
        assert res.mtime_ns > 0
        assert res.content_sha256 == hashlib.sha256(data).hexdigest()
        assert res.reason_code is None

    def test_empty_file_rejected_as_empty_file(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "9876543210.pdf"
        p.write_bytes(b"")

        res = validate_pdf(p)

        assert res.is_valid is False
        assert res.reason_code == "empty_file"
        assert res.file_size_bytes == 0
        assert res.content_sha256 is None

    def test_oversized_file_rejected_as_file_too_large(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "9876543210.pdf"
        p.write_bytes(_create_mock_pdf(b"A" * 1024))

        # Test with small limit of 500 bytes
        res = validate_pdf(p, max_size_bytes=500)

        assert res.is_valid is False
        assert res.reason_code == "file_too_large"
        assert res.file_size_bytes > 500
        assert res.content_sha256 is None

    def test_missing_pdf_header_rejected_as_invalid_pdf(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "9876543210.pdf"
        p.write_bytes(b"NOT A VALID PDF HEADER\ntrailer\n%%EOF\n")

        res = validate_pdf(p)

        assert res.is_valid is False
        assert res.reason_code == "invalid_pdf"

    def test_missing_eof_trailer_rejected_as_invalid_pdf(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "9876543210.pdf"
        p.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\nINCOMPLETE PDF")

        res = validate_pdf(p)

        assert res.is_valid is False
        assert res.reason_code == "invalid_pdf"

    def test_sha256_incremental_correctness(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "9876543210.pdf"
        # Create multi-chunk file (> 64 KiB)
        large_body = b"X" * (128 * 1024)
        data = _create_mock_pdf(large_body)
        p.write_bytes(data)

        res = validate_pdf(p)

        assert res.is_valid is True
        expected_sha = hashlib.sha256(data).hexdigest()
        assert res.content_sha256 == expected_sha

    def test_file_change_during_validation_detected(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        p = tmp_path / "9876543210.pdf"
        p.write_bytes(_create_mock_pdf())

        # Simulate size change after read by modifying stat
        original_stat = os.stat_result

        class FakeStat:
            def __init__(self, original: os.stat_result, altered_size: int) -> None:
                self._orig = original
                self.st_size = altered_size
                self.st_mtime_ns = original.st_mtime_ns + 1000

        call_count = 0
        real_stat = pathlib.Path.stat

        def mock_path_stat(path_obj: pathlib.Path) -> Any:
            nonlocal call_count
            call_count += 1
            real = real_stat(path_obj)
            if call_count > 1:
                # Return modified stat on post-read recheck
                return FakeStat(real, real.st_size + 50)
            return real

        monkeypatch.setattr(pathlib.Path, "stat", mock_path_stat)

        res = validate_pdf(p)

        assert res.is_valid is False
        assert res.reason_code == "file_modified_during_validation"

    def test_disappearing_file_returns_source_file_unavailable(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "9876543210.pdf"
        # Does not exist
        res = validate_pdf(p)

        assert res.is_valid is False
        assert res.reason_code == "source_file_unavailable"

    def test_invalid_recipient_filename_stops_before_pdf_validation(
        self, tmp_path: pathlib.Path,
    ) -> None:
        p = tmp_path / "9876543210_report.pdf"
        p.write_bytes(_create_mock_pdf())

        res = validate_pdf(p)

        assert res.is_valid is False
        assert res.reason_code == "invalid_filename"
        assert res.recipient_phone_e164 is None

    def test_final_metadata_stat_oserror_fails_closed(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        p = tmp_path / "9876543210.pdf"
        p.write_bytes(_create_mock_pdf())

        call_count = 0
        real_stat = pathlib.Path.stat

        def mock_path_stat(path_obj: pathlib.Path) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                # Post-read stat fails with OSError (e.g. file deleted/unmounted)
                raise OSError("Post-read stat failed: file access error")
            return real_stat(path_obj)

        monkeypatch.setattr(pathlib.Path, "stat", mock_path_stat)

        res = validate_pdf(p)

        assert res.is_valid is False
        assert res.reason_code == "source_file_unavailable"
        assert res.content_sha256 is None

