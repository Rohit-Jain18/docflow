"""
Docflow Windows Agent.

Watches a configured folder for PDF files, validates them, and coordinates
report registration and delivery through the Docflow control plane.
"""

__version__ = "0.1.0"

from docflow_agent.activation import (
    ActivationCodeExpiredError,
    ActivationError,
    ActivationRateLimitedError,
    ActivationResult,
    ActivationService,
    ActivationStorageError,
    ActivationValidationError,
    DeviceInfo,
    activate_device,
)
from docflow_agent.client import (
    ApiClient,
    ApiClientError,
    ApiAuthenticationError,
    ApiConflictError,
    ApiConnectionError,
    ApiNotFoundError,
    ApiPayloadError,
    ApiPermissionError,
    ApiRateLimitError,
    ApiResponseError,
    ApiTimeoutError,
    UntrustedOriginError,
)
from docflow_agent.pdf import ValidationResult, validate_pdf
from docflow_agent.quarantine import QuarantineResult, quarantine_file, should_quarantine
from docflow_agent.queue import (
    EnqueueResult,
    JobEvent,
    JobQueue,
    JobRecord,
    JobStatus,
    compute_fingerprint,
    create_watcher_enqueue_adapter,
    handle_watcher_result,
)
from docflow_agent.recipient import mask_phone, validate_recipient
from docflow_agent.stability import StabilityResult, check_stability
from docflow_agent.watcher import Watcher, is_candidate_file, process_candidate_file

__all__ = [
    "ActivationCodeExpiredError",
    "ActivationError",
    "ActivationRateLimitedError",
    "ActivationResult",
    "ActivationService",
    "ActivationStorageError",
    "ActivationValidationError",
    "ApiClient",
    "ApiClientError",
    "activate_device",
    "ApiAuthenticationError",
    "ApiConflictError",
    "ApiConnectionError",
    "ApiNotFoundError",
    "ApiPayloadError",
    "ApiPermissionError",
    "ApiRateLimitError",
    "ApiResponseError",
    "ApiTimeoutError",
    "DeviceInfo",
    "EnqueueResult",
    "JobEvent",
    "JobQueue",
    "JobRecord",
    "JobStatus",
    "QuarantineResult",
    "StabilityResult",
    "UntrustedOriginError",
    "ValidationResult",
    "Watcher",
    "__version__",
    "check_stability",
    "compute_fingerprint",
    "create_watcher_enqueue_adapter",
    "handle_watcher_result",
    "is_candidate_file",
    "mask_phone",
    "process_candidate_file",
    "quarantine_file",
    "should_quarantine",
    "validate_pdf",
    "validate_recipient",
]
