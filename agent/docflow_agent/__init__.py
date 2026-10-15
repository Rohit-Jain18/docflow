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
from docflow_agent.media import (
    MediaError,
    MediaExpiredError,
    MediaExpiryValidator,
    MediaReference,
    ReconciliationRequiredError,
    SourceFileUnavailableError,
    STANDARDIZED_ATTACHMENT_FILENAME,
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
from docflow_agent.registration import (
    AccountNotVerifiedError,
    RegistrationConflictError,
    RegistrationError,
    RegistrationResult,
    ReportRegistrationService,
)
from docflow_agent.retention import (
    CleanupChecklistResult,
    CleanupService,
    is_safe_path_for_deletion,
    verify_cleanup_checklist,
)
from docflow_agent.runtime import AgentRuntime, calculate_backoff_delay
from docflow_agent.service import (
    DocflowAgentService,
    ServiceRunner,
    handle_service_command,
    start_service_dispatcher,
)
from docflow_agent.stability import StabilityResult, check_stability
from docflow_agent.sync import (
    ConfigSyncService,
    ConfigValidationError,
    DeviceRevokedError,
    DeviceSyncManager,
    HeartbeatResult,
    HeartbeatService,
    RemoteConfig,
)
from docflow_agent.token_manager import (
    TokenAuthenticationError,
    TokenError,
    TokenManager,
    TokenMissingError,
    TokenRateLimitedError,
    TokenReuseConflictError,
    TokenRotationAmbiguousError,
    TokenStatus,
    TokenStorageError,
    TokenValidationError,
)
from docflow_agent.watcher import Watcher, is_candidate_file, process_candidate_file

__all__ = [
    "AccountNotVerifiedError",
    "ActivationCodeExpiredError",
    "ActivationError",
    "ActivationRateLimitedError",
    "ActivationResult",
    "ActivationService",
    "ActivationStorageError",
    "ActivationValidationError",
    "AgentRuntime",
    "ApiClient",
    "ApiClientError",
    "ApiAuthenticationError",
    "ApiConflictError",
    "ApiConnectionError",
    "ApiNotFoundError",
    "ApiPayloadError",
    "ApiPermissionError",
    "ApiRateLimitError",
    "ApiResponseError",
    "ApiTimeoutError",
    "CleanupChecklistResult",
    "CleanupService",
    "ConfigSyncService",
    "ConfigValidationError",
    "DeviceInfo",
    "DeviceRevokedError",
    "DeviceSyncManager",
    "DocflowAgentService",
    "EnqueueResult",
    "HeartbeatResult",
    "HeartbeatService",
    "JobEvent",
    "JobQueue",
    "JobRecord",
    "JobStatus",
    "MediaError",
    "MediaExpiredError",
    "MediaExpiryValidator",
    "MediaReference",
    "QuarantineResult",
    "ReconciliationRequiredError",
    "RegistrationConflictError",
    "RegistrationError",
    "RegistrationResult",
    "RemoteConfig",
    "ReportRegistrationService",
    "STANDARDIZED_ATTACHMENT_FILENAME",
    "ServiceRunner",
    "SourceFileUnavailableError",
    "handle_service_command",
    "start_service_dispatcher",

    "StabilityResult",
    "TokenAuthenticationError",
    "TokenError",
    "TokenManager",
    "TokenMissingError",
    "TokenRateLimitedError",
    "TokenReuseConflictError",
    "TokenRotationAmbiguousError",
    "TokenStatus",
    "TokenStorageError",
    "TokenValidationError",
    "UntrustedOriginError",
    "ValidationResult",
    "Watcher",
    "__version__",
    "activate_device",
    "calculate_backoff_delay",
    "check_stability",
    "compute_fingerprint",
    "create_watcher_enqueue_adapter",
    "handle_watcher_result",
    "is_candidate_file",
    "is_safe_path_for_deletion",
    "mask_phone",
    "process_candidate_file",
    "quarantine_file",
    "should_quarantine",
    "validate_pdf",
    "validate_recipient",
    "verify_cleanup_checklist",
]
