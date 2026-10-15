"""Tests for docflow_agent.quarantine — quarantine handling module."""

import logging
import os
import pathlib
import pytest

from docflow_agent.quarantine import (
    PERMANENT_QUARANTINE_REASONS,
    QuarantineResult,
    quarantine_file,
    should_quarantine,
)


class TestQuarantineHandling:
    """Test safe collision-safe quarantine, opaque filenames, and move failure resilience."""

    def test_quarantine_moves_file_with_opaque_uuid_name(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        quarantine = tmp_path / "quarantine"
        watch.mkdir()
        quarantine.mkdir()

        source_file = watch / "9876543210_report.pdf"
        source_file.write_bytes(b"corrupt or invalid content")

        result = quarantine_file(
            source_file,
            quarantine,
            reason_code="invalid_filename",
        )

        assert result.success is True
        assert result.reason_code == "invalid_filename"
        assert result.quarantined_path is not None
        assert result.quarantined_path.exists()
        assert result.quarantined_path.parent == quarantine

        # Must retain .pdf extension
        assert result.quarantined_path.suffix.lower() == ".pdf"

        # Must NOT contain original filename or patient phone number
        assert "9876543210" not in result.quarantined_path.name
        assert "report" not in result.quarantined_path.name
        assert result.quarantined_path.stem == result.quarantine_id

        # Original source file must no longer exist at original path
        assert not source_file.exists()

    def test_should_quarantine_permanent_reasons_only(self) -> None:
        for reason in ["invalid_filename", "invalid_phone", "invalid_pdf", "empty_file", "file_too_large"]:
            assert should_quarantine(reason) is True

        # Stability timeout MUST NOT be quarantined
        assert should_quarantine("stability_timeout_after_policy") is False
        assert should_quarantine("source_file_unavailable") is False
        assert should_quarantine(None) is False

    def test_source_file_never_discarded_if_move_fails(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        watch = tmp_path / "watch"
        quarantine = tmp_path / "quarantine"
        watch.mkdir()
        quarantine.mkdir()

        source_file = watch / "9876543210.pdf"
        source_file.write_bytes(b"sample bytes")

        # Simulate shutil.move failure (e.g. PermissionError or locked destination)
        import shutil

        def mock_move(src: str, dst: str) -> None:
            raise PermissionError("Access denied moving file")

        monkeypatch.setattr(shutil, "move", mock_move)

        result = quarantine_file(
            source_file,
            quarantine,
            reason_code="invalid_pdf",
        )

        assert result.success is False
        assert "quarantine_move_failed" in (result.error or "")

        # Source file MUST be preserved in place
        assert source_file.exists()
        assert source_file.read_bytes() == b"sample bytes"

    def test_nonexistent_source_returns_safe_failure(self, tmp_path: pathlib.Path) -> None:
        nonexistent = tmp_path / "does_not_exist.pdf"
        quarantine = tmp_path / "quarantine"

        result = quarantine_file(nonexistent, quarantine, reason_code="invalid_pdf")
        assert result.success is False
        assert result.error == "source_file_unavailable"

    def test_quarantine_logs_never_contain_raw_path_or_phone(
        self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG)
        watch = tmp_path / "watch"
        quarantine = tmp_path / "quarantine"
        watch.mkdir()
        quarantine.mkdir()

        phone = "9876543210"
        source_file = watch / f"{phone}_report.pdf"
        source_file.write_bytes(b"bad content")

        result = quarantine_file(source_file, quarantine, reason_code="invalid_filename")
        assert result.success is True

        # Inspect logged messages
        for record in caplog.records:
            msg = record.getMessage()
            # Raw full phone number must never appear in log output
            assert phone not in msg
            # Raw original filename must never appear in log output
            assert f"{phone}_report.pdf" not in msg
