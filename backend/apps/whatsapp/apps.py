"""AppConfig for the whatsapp app."""
from django.apps import AppConfig


class WhatsappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.whatsapp"
    label = "whatsapp"
    verbose_name = "WhatsApp"
