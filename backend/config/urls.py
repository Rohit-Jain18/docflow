"""Docflow URL configuration."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.devices.urls")),
    path("api/v1/", include("apps.users.urls")),
    path("api/v1/", include("apps.tenants.urls")),
    path("api/v1/", include("apps.whatsapp.urls")),
    path("api/v1/", include("apps.reports.urls")),
]

