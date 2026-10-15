"""Tests for docflow_agent.recipient — recipient and filename validation."""

import pathlib
import pytest

from docflow_agent.recipient import mask_phone, validate_recipient


class TestRecipientValidationSuccess:
    """Test valid filenames and recipient numbers."""

    def test_indian_10_digit_national_number(self) -> None:
        valid, e164, reason = validate_recipient("9876543210.pdf", default_region="IN")
        assert valid is True
        assert e164 == "+919876543210"
        assert reason is None

    def test_indian_country_code_with_plus(self) -> None:
        valid, e164, reason = validate_recipient("+919876543210.pdf", default_region="IN")
        assert valid is True
        assert e164 == "+919876543210"
        assert reason is None

    def test_indian_country_code_without_plus(self) -> None:
        valid, e164, reason = validate_recipient("919876543210.pdf", default_region="IN")
        assert valid is True
        assert e164 == "+919876543210"
        assert reason is None

    def test_indian_national_prefix_zero(self) -> None:
        valid, e164, reason = validate_recipient("09876543210.pdf", default_region="IN")
        assert valid is True
        assert e164 == "+919876543210"
        assert reason is None

    def test_formatted_with_spaces_hyphens_periods_parentheses(self) -> None:
        filenames = [
            "+91 (98765) 43210.pdf",
            "98765-43210.pdf",
            "98765 43210.pdf",
            "98765.43210.pdf",
            "+91-98765-43210.pdf",
            "(022) 28765432.pdf",
        ]
        for name in filenames:
            valid, e164, reason = validate_recipient(name, default_region="IN")
            assert valid is True, f"Failed for {name}: {reason}"
            assert e164 is not None
            assert e164.startswith("+91")
            assert reason is None

    def test_international_number_with_plus(self) -> None:
        # US number with explicit +
        valid, e164, reason = validate_recipient("+14155552671.pdf", default_region="IN")
        assert valid is True
        assert e164 == "+14155552671"
        assert reason is None

        # UK number with explicit +
        valid_uk, e164_uk, reason_uk = validate_recipient("+447911123456.pdf", default_region="IN")
        assert valid_uk is True
        assert e164_uk == "+447911123456"
        assert reason_uk is None

    def test_configured_region_national_number(self) -> None:
        # US 10-digit number when default_region is US
        valid, e164, reason = validate_recipient("4155552671.pdf", default_region="US")
        assert valid is True
        assert e164 == "+14155552671"
        assert reason is None

    def test_case_insensitive_extension(self) -> None:
        for ext in [".PDF", ".Pdf", ".pDf"]:
            valid, e164, reason = validate_recipient(f"9876543210{ext}")
            assert valid is True, f"Failed for extension {ext}"
            assert e164 == "+919876543210"

    def test_accepts_pathlib_path(self) -> None:
        p = pathlib.Path("C:/LIS/incoming/9876543210.pdf")
        valid, e164, reason = validate_recipient(p)
        assert valid is True
        assert e164 == "+919876543210"


class TestRecipientValidationFailure:
    """Test rejection of invalid filenames, characters, numbers, and suffixes."""

    def test_rejects_non_pdf_extension(self) -> None:
        for name in ["9876543210.txt", "9876543210.doc", "9876543210"]:
            valid, e164, reason = validate_recipient(name)
            assert valid is False
            assert e164 is None
            assert reason == "invalid_filename"

    def test_rejects_letters_and_word_suffixes(self) -> None:
        bad_names = [
            "9876543210_report.pdf",
            "report_9876543210.pdf",
            "patient9876543210.pdf",
            "9876543210-v1.pdf",
            "report.pdf",
            "abc.pdf",
        ]
        for name in bad_names:
            valid, e164, reason = validate_recipient(name)
            assert valid is False, f"Should reject {name}"
            assert e164 is None
            assert reason == "invalid_filename"

    def test_rejects_empty_stem(self) -> None:
        for name in [".pdf", "   .pdf"]:
            valid, e164, reason = validate_recipient(name)
            assert valid is False
            assert reason == "invalid_filename"

    def test_rejects_path_separators_in_stem(self) -> None:
        # e.g. stem with slashes
        valid, e164, reason = validate_recipient("98765/43210.pdf")
        assert valid is False
        assert reason == "invalid_filename"

    def test_rejects_multiple_phone_numbers(self) -> None:
        bad_multiple = [
            "9876543210 9876543211.pdf",
            "(9876543210) (9876543211).pdf",
            "+919876543210 +919876543211.pdf",
            "98765432109876543211.pdf",  # 20 digits joined
        ]
        for name in bad_multiple:
            valid, e164, reason = validate_recipient(name)
            assert valid is False, f"Should reject multiple numbers in {name}"
            assert e164 is None
            assert reason in ("invalid_filename", "invalid_phone")

    def test_rejects_ambiguous_plus_signs(self) -> None:
        bad_pluses = [
            "++919876543210.pdf",
            "91+9876543210.pdf",
            "+91+9876543210.pdf",
        ]
        for name in bad_pluses:
            valid, e164, reason = validate_recipient(name)
            assert valid is False, f"Should reject ambiguous plus: {name}"
            assert reason == "invalid_filename"

    def test_rejects_unbalanced_parentheses(self) -> None:
        for name in ["(9876543210.pdf", "9876543210).pdf", "((9876543210.pdf"]:
            valid, e164, reason = validate_recipient(name)
            assert valid is False
            assert reason == "invalid_filename"

    def test_rejects_invalid_phone_lengths(self) -> None:
        # Too short
        valid, e164, reason = validate_recipient("12345.pdf")
        assert valid is False
        assert reason == "invalid_phone"

        # Impossible Indian number
        valid, e164, reason = validate_recipient("1111111111.pdf")
        assert valid is False
        assert reason == "invalid_phone"

    def test_never_blindly_prepends_india_code_to_foreign_national_number(self) -> None:
        # A 10-digit US number without + when default region is IN must not be accepted
        valid, e164, reason = validate_recipient("14155552671.pdf", default_region="IN")
        assert valid is False
        assert reason == "invalid_phone"


class TestMaskPhone:
    """Test safe phone masking for logs."""

    def test_masks_indian_number(self) -> None:
        masked = mask_phone("+919876543210")
        assert masked == "+91******3210"
        assert "987654" not in masked

    def test_masks_us_number(self) -> None:
        masked = mask_phone("+14155552671")
        assert masked == "+1******2671"
        assert "555" not in masked

    def test_masks_empty_or_short(self) -> None:
        assert mask_phone("") == "[REDACTED_PHONE]"
        assert mask_phone("123") == "[REDACTED_PHONE]"
