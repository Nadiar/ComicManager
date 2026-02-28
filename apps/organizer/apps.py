from django.apps import AppConfig


class OrganizerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.organizer"

    def ready(self):
        from .signals import flag_all_on_profile_template_change  # noqa: F401 — connect via @receiver
