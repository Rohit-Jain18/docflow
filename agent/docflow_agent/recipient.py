"""
Filename and recipient phone number validation for the Docflow Windows Agent.

Validates the recipient phone number encoded in the PDF filename stem according
to docs/AGENT_SPEC.md §4:
- Accepts only .pdf filenames (case-insensitive).
- Basename stem consists solely of digits, an optional leading +, spaces, hyphens,
  periods, and parentheses.
- Rejects letters, suffixes (e.g. _report), multiple phone numbers, path separators,
  and ambiguous inputs.
- Validates complete phone number using phonenumbers and normalizes to E.164.
- Redacts phone numbers and filenames in all log statements.
"""

from __future__ import annotations

import logging
import pathlib
import re
from typing import Any

import phonenumbers

logger = logging.getLogger(__name__)

# Allowed stem characters: optional leading +, digits, spaces, hyphens, periods, parentheses
_ALLOWED_STEM_PATTERN = re.compile(r"^\+?[\d\s\-\.\(\)]+$")
_LETTERS_OR_UNDERSCORE_PATTERN = re.compile(r"[a-zA-Z_]")


def mask_phone(phone: str) -> str:
    """Mask a phone number for safe logging, keeping country code and last 4 digits.

    Example:
        '+919876543210' -> '+91******3210'
        '+14155552671'  -> '+1******2671'
    """
    if not phone:
        return "[REDACTED_PHONE]"
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 4:
        return "[REDACTED_PHONE]"
    try:
        raw = phone if phone.startswith("+") else f"+{phone}"
        parsed = phonenumbers.parse(raw, None)
        cc = f"+{parsed.country_code}"
        last4 = digits[-4:]
        return f"{cc}******{last4}"
    except Exception:
        return f"******{digits[-4:]}"


def _are_parentheses_balanced(s: str) -> bool:
    """Return True if parentheses in s are properly matched and balanced."""
    count = 0
    for char in s:
        if char == "(":
            count += 1
        elif char == ")":
            count -= 1
            if count < 0:
                return False
    return count == 0


def validate_recipient(
    filename_or_path: str | pathlib.Path,
    default_region: str = "IN",
) -> tuple[bool, str | None, str | None]:
    """Validate a PDF filename stem and extract the normalized E.164 phone number.

    Args:
        filename_or_path: File path or basename (e.g. '919876543210.pdf').
        default_region:   ISO 3166-1 two-letter region code for national numbers.

    Returns:
        tuple of (is_valid, normalized_e164_or_none, reason_code_or_none).
        Possible failure reason codes:
        - 'invalid_filename': Not a .pdf, forbidden characters/suffixes, unbalanced
          parentheses, or multiple phone numbers.
        - 'invalid_phone': Phone number is structurally invalid, incorrect length,
          or unrecognized country code.
    """
    raw_str = str(filename_or_path)
    p = pathlib.Path(filename_or_path)

    # Reject relative strings containing path separators (ambiguous/invalid input)
    if ("/" in raw_str or "\\" in raw_str) and not p.is_absolute():
        if not p.is_file():
            return False, None, "invalid_filename"

    basename = p.name

    # Must have .pdf extension (case-insensitive)
    if not basename.lower().endswith(".pdf"):
        return False, None, "invalid_filename"

    stem = basename[:-4]
    if not stem or not stem.strip():
        return False, None, "invalid_filename"

    # Reject letters, underscores, and suffixes (e.g. _report, patient_123)
    if _LETTERS_OR_UNDERSCORE_PATTERN.search(stem):
        return False, None, "invalid_filename"

    # Reject path separators or characters not in allowed set
    if not _ALLOWED_STEM_PATTERN.match(stem):
        return False, None, "invalid_filename"

    # Reject unbalanced parentheses
    if not _are_parentheses_balanced(stem):
        return False, None, "invalid_filename"

    # Reject multiple + signs or + not at start
    trimmed_stem = stem.strip()
    if stem.count("+") > 1 or ("+" in stem and not trimmed_stem.startswith("+")):
        return False, None, "invalid_filename"

    # Digits count check (E.164 allows 7 to 15 digits)
    digits = re.findall(r"\d", stem)
    if len(digits) < 7 or len(digits) > 15:
        # Either too short, empty, or multiple phone numbers concatenated
        if len(digits) > 15:
            return False, None, "invalid_filename"
        return False, None, "invalid_phone"

    # Check for multiple distinct phone numbers in stem
    try:
        matches = list(phonenumbers.PhoneNumberMatcher(stem, default_region))
        if len(matches) > 1:
            return False, None, "invalid_filename"
    except Exception:
        pass

    # Parse using phonenumbers
    try:
        if trimmed_stem.startswith("+"):
            parsed = phonenumbers.parse(trimmed_stem, None)
        else:
            parsed = phonenumbers.parse(trimmed_stem, default_region)
    except phonenumbers.NumberParseException:
        return False, None, "invalid_phone"
    except Exception:
        return False, None, "invalid_phone"

    # Validate complete number against region metadata
    if not phonenumbers.is_valid_number(parsed):
        return False, None, "invalid_phone"

    # Normalize to E.164
    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    return True, e164, None
