"""
Heartbeat and Configuration Synchronization Service for Docflow Windows Agent.

Implements requirements from:
- docs/AGENT_SPEC.md §§ 2, 5, 8
- docs/API_CONTRACTS.md §§ 1, 5
- docs/RULES.md (Rules 1, 2, 3, 7)

Endpoints used:
- POST /api/v1/agent/heartbeat
  Telemetry payload: agent_version, installation_id, service_state, queue_counts, last_successful_job_at
  Response: server_time, configuration_version, device_status
- GET /api/v1/agent/config
  Response: device_id, branch_id, configuration_version, operational parameters

Enforces:
- Strict validation of remote configuration (rejects URL/origin redirection, credential manipulation,
  or tenant/account selection).
- Zero secret, token, or patient PII in requests, logs, or error strings.
- Graceful offline operation, rate-limiting backoff, and fail-closed handling on device revocation (403).
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import re
import uuid
from typing import Any

from docflow_agent.client import (
    ApiClient,
    ApiResponseError,
    ApiAuthenticationError,
    ApiPermissionError,
    ApiTimeoutError,
    ApiConnectionError,
    ApiPayloadError,
)
from docflow_agent.config import AgentConfig
from docflow_agent.queue import JobQueue

logger = logging.getLogger(__name__)

# Strict ISO 8601 UTC timestamp regex ending in 'Z'
_ISO8601_UTC_Z_REGEX = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)

# Standard phone region: 2 uppercase ASCII letters (e.g., "IN", "US")
_PHONE_REGION_REGEX = re.compile(r"^[A-Z]{2}$")

HEARTBEAT_ENDPOINT = "/api/v1/agent/heartbeat"
CONFIG_ENDPOINT = "/api/v1/agent/config"


class DeviceRevokedError(ApiResponseError):
    """Raised when the server reports HTTP 403 or non-active device status."""

    def __init__(self, detail: str = "Device has been revoked or is inactive.", request_id: str | None = None) -> None:
        super().__init__(
            status_code=403,
            code="permission_denied",
            detail=detail,
            request_id=request_id,
        )


class ConfigValidationError(Exception):
    """Raised when server-provided remote configuration fails validation."""


@dataclasses.dataclass(frozen=True)
class HeartbeatResult:
    """Safe representation of a successful server heartbeat response."""

    server_time: str
    configuration_version: int
    device_status: str
    is_active: bool

    def __repr__(self) -> str:
        return (
            f"HeartbeatResult(server_time={self.server_time!r}, "
            f"config_version={self.configuration_version}, "
            f"device_status={self.device_status!r})"
        )


@dataclasses.dataclass(frozen=True)
class RemoteConfig:
    """Validated server-managed operational configuration."""

    device_id: str
    branch_id: str
    configuration_version: int
    watch_folder_policy: str
    filename_pattern: str
    default_phone_region: str
    stability_sample_seconds: int
    stability_required_samples: int
    stability_timeout_seconds: int
    max_pdf_size_bytes: int
    archive_policy: str
    quarantine_policy: str


def validate_iso_utc_timestamp(ts: str | None) -> str | None:
    """Ensure timestamp is valid ISO 8601 UTC string ending in 'Z'."""
    if ts is None:
        return None
    val = str(ts).strip()
    if not _ISO8601_UTC_Z_REGEX.match(val):
        raise ConfigValidationError(
            f"Timestamp '{val}' does not match strict ISO 8601 UTC format ending in 'Z'."
        )
    return val


def parse_remote_config(data: Any) -> RemoteConfig:
    """Strictly validate and parse GET /api/v1/agent/config payload.

    Security rules:
    - Never accept or process api_base_url, credentials, tokens, or tenant/account authority.
    - Bound all numeric thresholds to prevent resource exhaustion or denial-of-service.
    """
    if not isinstance(data, dict):
        raise ConfigValidationError("Remote configuration payload must be a JSON object.")

    # Disallow dangerous or prohibited server-supplied keys
    forbidden_keys = {
        "api_base_url",
        "api_origin",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "password",
        "wa_platform_developer_token",
        "whatsapp_token",
        "phone_number_id",
        "whatsapp_account_id",
        "organization_id",
        "watch_folder",
        "archive_folder",
        "quarantine_folder",
        "db_path",
    }
    present_forbidden = forbidden_keys.intersection(data.keys())
    if present_forbidden:
        raise ConfigValidationError(
            f"Server configuration contains forbidden security-sensitive keys: {sorted(present_forbidden)}"
        )

    # 1. Device and Branch IDs
    raw_device_id = str(data.get("device_id", "")).strip()
    raw_branch_id = str(data.get("branch_id", "")).strip()
    try:
        uuid.UUID(raw_device_id)
        uuid.UUID(raw_branch_id)
    except (ValueError, TypeError) as exc:
        raise ConfigValidationError("device_id and branch_id must be valid UUID strings.") from exc

    # 2. Configuration version
    raw_version = data.get("configuration_version")
    if not isinstance(raw_version, int) or raw_version < 1:
        raise ConfigValidationError("configuration_version must be an integer >= 1.")

    # 3. Phone region
    region = str(data.get("default_phone_region", "")).strip().upper()
    if not _PHONE_REGION_REGEX.match(region):
        raise ConfigValidationError(
            f"default_phone_region must be a 2-letter uppercase ISO country code, got '{region}'."
        )

    # 4. Stability thresholds
    sample_sec = data.get("stability_sample_seconds")
    if not isinstance(sample_sec, int) or not (1 <= sample_sec <= 60):
        raise ConfigValidationError("stability_sample_seconds must be an integer between 1 and 60.")

    req_samples = data.get("stability_required_samples")
    if not isinstance(req_samples, int) or not (2 <= req_samples <= 10):
        raise ConfigValidationError("stability_required_samples must be an integer between 2 and 10.")

    timeout_sec = data.get("stability_timeout_seconds")
    if not isinstance(timeout_sec, int) or not (10 <= timeout_sec <= 600):
        raise ConfigValidationError("stability_timeout_seconds must be an integer between 10 and 600.")

    # 5. Max PDF size (1 KB to 100 MB)
    max_pdf_bytes = data.get("max_pdf_size_bytes")
    if not isinstance(max_pdf_bytes, int) or not (1024 <= max_pdf_bytes <= 104_857_600):
        raise ConfigValidationError("max_pdf_size_bytes must be an integer between 1024 and 104857600.")

    # 6. Policy tokens
    watch_policy = str(data.get("watch_folder_policy", "locally_configured")).strip()
    pattern = str(data.get("filename_pattern", "phone_number.pdf")).strip()
    archive_policy = str(data.get("archive_policy", "after_provider_accepted")).strip()
    quarantine_policy = str(data.get("quarantine_policy", "move_invalid_files")).strip()

    return RemoteConfig(
        device_id=raw_device_id,
        branch_id=raw_branch_id,
        configuration_version=raw_version,
        watch_folder_policy=watch_policy,
        filename_pattern=pattern,
        default_phone_region=region,
        stability_sample_seconds=sample_sec,
        stability_required_samples=req_samples,
        stability_timeout_seconds=timeout_sec,
        max_pdf_size_bytes=max_pdf_bytes,
        archive_policy=archive_policy,
        quarantine_policy=quarantine_policy,
    )


class HeartbeatService:
    """Manages periodic device heartbeat telemetry submissions."""

    def __init__(
        self,
        client: ApiClient,
        queue: JobQueue,
        installation_id: str,
        agent_version: str = "0.1.0",
    ) -> None:
        self.client = client
        self.queue = queue
        self.installation_id = str(installation_id).strip()
        self.agent_version = str(agent_version).strip()

        if not self.installation_id:
            raise ValueError("installation_id is required.")

    def send_heartbeat(self, service_state: str = "running") -> HeartbeatResult:
        """Submit periodic device heartbeat to POST /api/v1/agent/heartbeat.

        Fails closed with DeviceRevokedError if the server returns 403 or non-active status.
        """
        # Query local queue telemetry without locking or exposing sensitive job data
        counts = self.queue.get_queue_counts()
        last_success = self.queue.get_last_successful_job_at()

        payload = {
            "agent_version": self.agent_version,
            "installation_id": self.installation_id,
            "service_state": service_state,
            "queue_counts": {
                "queued": max(0, int(counts.get("queued", 0))),
                "retry_wait": max(0, int(counts.get("retry_wait", 0))),
                "quarantined": max(0, int(counts.get("quarantined", 0))),
            },
            "last_successful_job_at": last_success,
        }

        try:
            resp = self.client.post(
                HEARTBEAT_ENDPOINT,
                json=payload,
                authenticated=True,
            )
        except ApiPermissionError as exc:
            logger.error("Heartbeat rejected: Device or branch has been revoked or deactivated.")
            raise DeviceRevokedError(detail=exc.detail, request_id=exc.request_id) from exc
        except (ApiTimeoutError, ApiConnectionError) as exc:
            logger.warning("Heartbeat network attempt failed: %s", type(exc).__name__)
            raise

        if not isinstance(resp, dict):
            raise ApiPayloadError("Server returned unexpected heartbeat response payload.")

        raw_server_time = resp.get("server_time")
        raw_version = resp.get("configuration_version")
        raw_status = str(resp.get("device_status", "")).strip().lower()

        if not raw_server_time or not isinstance(raw_server_time, str):
            raise ApiPayloadError("Heartbeat response missing valid 'server_time'.")
        if not _ISO8601_UTC_Z_REGEX.match(raw_server_time):
            raise ApiPayloadError("Heartbeat 'server_time' is not in strict ISO 8601 UTC Z format.")

        if not isinstance(raw_version, int) or raw_version < 1:
            raise ApiPayloadError("Heartbeat response missing valid 'configuration_version'.")

        is_active = (raw_status == "active")
        if not is_active:
            logger.error("Device status in heartbeat is not active ('%s'). Pausing operations.", raw_status)
            raise DeviceRevokedError(f"Device status is '{raw_status}'. Operations suspended.")

        result = HeartbeatResult(
            server_time=raw_server_time,
            configuration_version=raw_version,
            device_status=raw_status,
            is_active=is_active,
        )
        logger.debug("Heartbeat successful: config_version=%d, status=%s", raw_version, raw_status)
        return result


class ConfigSyncService:
    """Manages fetching and applying remote operational configuration."""

    def __init__(
        self,
        client: ApiClient,
        queue: JobQueue,
    ) -> None:
        self.client = client
        self.queue = queue

    def get_persisted_version(self) -> int:
        """Fetch the last applied configuration version from local agent_settings."""
        raw = self.queue.get_setting("remote_config_version")
        if raw is not None:
            try:
                return int(raw)
            except (ValueError, TypeError):
                pass
        return 0

    def fetch_and_apply(self) -> RemoteConfig:
        """Fetch GET /api/v1/agent/config, validate, and persist safe operational parameters."""
        resp = self.client.get(CONFIG_ENDPOINT, authenticated=True)
        config = parse_remote_config(resp)

        # Persist non-secret operational settings
        self.queue.set_setting("remote_config_version", str(config.configuration_version))
        self.queue.set_setting("server_device_id", config.device_id)
        self.queue.set_setting("server_branch_id", config.branch_id)
        self.queue.set_setting("stability_sample_seconds", str(config.stability_sample_seconds))
        self.queue.set_setting("stability_required_samples", str(config.stability_required_samples))
        self.queue.set_setting("stability_timeout_seconds", str(config.stability_timeout_seconds))
        self.queue.set_setting("max_pdf_size_bytes", str(config.max_pdf_size_bytes))
        self.queue.set_setting("default_phone_region", config.default_phone_region)

        logger.info(
            "Synchronized remote configuration version %d (branch_id=%s)",
            config.configuration_version,
            config.branch_id,
        )
        return config


class DeviceSyncManager:
    """Coordinates heartbeat telemetry and remote configuration synchronization."""

    def __init__(
        self,
        client: ApiClient,
        queue: JobQueue,
        installation_id: str,
        agent_version: str = "0.1.0",
    ) -> None:
        self.heartbeat_service = HeartbeatService(
            client=client,
            queue=queue,
            installation_id=installation_id,
            agent_version=agent_version,
        )
        self.config_service = ConfigSyncService(
            client=client,
            queue=queue,
        )

    def perform_sync(self, service_state: str = "running") -> HeartbeatResult:
        """Execute one complete sync cycle: send heartbeat and update configuration if newer version exists."""
        hb_result = self.heartbeat_service.send_heartbeat(service_state=service_state)

        current_ver = self.config_service.get_persisted_version()
        if hb_result.configuration_version > current_ver:
            logger.info(
                "Remote configuration version advanced from %d to %d. Synchronizing...",
                current_ver,
                hb_result.configuration_version,
            )
            try:
                self.config_service.fetch_and_apply()
            except ConfigValidationError as exc:
                logger.warning(
                    "Remote configuration validation failed; preserving local settings: %s",
                    str(exc),
                )

        return hb_result
