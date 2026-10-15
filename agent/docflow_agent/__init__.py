"""
Docflow Windows Agent.

Watches a configured folder for PDF files, validates them, and coordinates
report registration and delivery through the Docflow control plane.
"""

__version__ = "0.1.0"

from docflow_agent.pdf import ValidationResult, validate_pdf
from docflow_agent.quarantine import QuarantineResult, quarantine_file, should_quarantine
from docflow_agent.recipient import mask_phone, validate_recipient
from docflow_agent.stability import StabilityResult, check_stability
from docflow_agent.watcher import Watcher, is_candidate_file, process_candidate_file

__all__ = [
    "QuarantineResult",
    "StabilityResult",
    "ValidationResult",
    "Watcher",
    "__version__",
    "check_stability",
    "is_candidate_file",
    "mask_phone",
    "process_candidate_file",
    "quarantine_file",
    "should_quarantine",
    "validate_pdf",
    "validate_recipient",
]
