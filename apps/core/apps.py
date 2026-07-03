from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self):
        # Seed default settings after migrations
        from django.db.models.signals import post_migrate
        from .signals import seed_default_settings, _capture_path_fields_before_save, flag_needs_reorganize_on_metadata_change  # noqa: F401 — connect via @receiver
        post_migrate.connect(seed_default_settings, sender=self)

        from apps.core import task_queue  # noqa: F401 — connects Celery lifecycle signals

        import os
        if os.environ.get("RUN_MAIN") == "true" or os.environ.get("RECONCILE_ON_START") == "1":
            try:
                task_queue.reconcile_orphans()
            except Exception:
                pass
