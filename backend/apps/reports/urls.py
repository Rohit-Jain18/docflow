"""
URL routing for Docflow Report APIs (Phase 1, Task 3G & Task 3H).

Routes:
  - POST /api/v1/agent/reports                                -> AgentReportRegistrationView (create)
  - GET  /api/v1/agent/reports                                -> AgentReportRegistrationView (list)
  - PUT  /api/v1/agent/reports/{report_id}/media-reference    -> AgentMediaReferenceAttachmentView
  - GET  /api/v1/agent/reports/{report_id}                    -> AgentReportDetailView
"""

from django.urls import re_path

from .views import (
    AgentMediaReferenceAttachmentView,
    AgentReportDetailView,
    AgentReportRegistrationView,
)

UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

urlpatterns = [
    re_path(
        r"^agent/reports/?$",
        AgentReportRegistrationView.as_view(),
        name="agent-report-list-create",
    ),
    re_path(
        rf"^agent/reports/(?P<report_id>{UUID_PATTERN})/media-reference/?$",
        AgentMediaReferenceAttachmentView.as_view(),
        name="agent-report-media-reference-attach",
    ),
    re_path(
        rf"^agent/reports/(?P<report_id>{UUID_PATTERN})/?$",
        AgentReportDetailView.as_view(),
        name="agent-report-detail",
    ),
]
