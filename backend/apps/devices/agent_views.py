"""
Views for Docflow Agent Configuration and Telemetry APIs (Phase 1, Task 3G).

Implements:
  - GET  /api/v1/agent/config: Device configuration retrieval.
  - POST /api/v1/agent/heartbeat: Device periodic heartbeat and telemetry.

Enforces:
  - Device Bearer token authentication (DeviceBearerAuthentication).
  - Server-derived identity from authenticated Device (never client parameters).
  - Strict payload validation and safe field allowlists.
  - Zero raw secret, token, local path, or other-tenant exposure.
"""

import uuid
from django.utils import timezone as tz_utils
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenants.models import BranchStatus, OrganizationStatus
from .authentication import DeviceBearerAuthentication
from .ip_utils import get_client_ip
from .serializers import AgentHeartbeatSerializer


def _get_request_id(request) -> str:
    """Extract or generate request tracking identifier."""
    if request:
        req_id = getattr(request, "request_id", None) or getattr(request, "_request_id", None)
        if req_id:
            return str(req_id)
        header_val = request.headers.get("X-Request-ID") or request.META.get("HTTP_X_REQUEST_ID")
        if header_val:
            return str(header_val).strip()
    return f"req_{uuid.uuid4().hex[:16]}"


class AgentConfigView(APIView):
    """
    GET /api/v1/agent/config

    Returns device-specific safe operational configuration.
    Derives device, organization, and branch authority strictly from authenticated Device.
    """

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        device = request.user

        if (
            device.organization.status != OrganizationStatus.ACTIVE
            or device.branch.status != BranchStatus.ACTIVE
        ):
            raise PermissionDenied("Device organization or branch is inactive.")

        response_data = {
            "device_id": str(device.id),
            "branch_id": str(device.branch_id),
            "configuration_version": 1,
            "watch_folder_policy": "locally_configured",
            "filename_pattern": "phone_number.pdf",
            "default_phone_region": "IN",
            "stability_sample_seconds": 2,
            "stability_required_samples": 3,
            "stability_timeout_seconds": 120,
            "max_pdf_size_bytes": 52428800,
            "archive_policy": "after_provider_accepted",
            "quarantine_policy": "move_invalid_files",
        }
        res = Response(response_data, status=status.HTTP_200_OK)
        res["X-Request-ID"] = _get_request_id(request)
        return res


class AgentHeartbeatView(APIView):
    """
    POST /api/v1/agent/heartbeat

    Receives device telemetry (queue counts, service state, agent version).
    Updates device last_seen_at and IP address.
    Returns server time, configuration version, and device status.
    """

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        device = request.user

        if (
            device.organization.status != OrganizationStatus.ACTIVE
            or device.branch.status != BranchStatus.ACTIVE
        ):
            raise PermissionDenied("Device organization or branch is inactive.")

        serializer = AgentHeartbeatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        now = tz_utils.now()
        device.last_seen_at = now
        device.last_ip = get_client_ip(request)
        device.agent_version = serializer.validated_data["agent_version"]
        device.save(update_fields=["last_seen_at", "last_ip", "agent_version", "updated_at"])

        response_data = {
            "server_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "configuration_version": 1,
            "device_status": device.status,
        }
        res = Response(response_data, status=status.HTTP_200_OK)
        res["X-Request-ID"] = _get_request_id(request)
        return res
