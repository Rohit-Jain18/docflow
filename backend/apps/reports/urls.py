"""
URL routing for Docflow Report APIs (Phase 1, Task 3G).

Routes:
  - POST /api/v1/agent/reports
"""

from django.urls import re_path

from .views import AgentReportRegistrationView

UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

urlpatterns = [
    re_path(
        r"^agent/reports/?$",
        AgentReportRegistrationView.as_view(),
        name="agent-report-create",
    ),
]
