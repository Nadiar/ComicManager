from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self):
        # Seed default settings after migrations
        from django.db.models.signals import post_migrate
        from .signals import seed_default_settings
        post_migrate.connect(seed_default_settings, sender=self)
