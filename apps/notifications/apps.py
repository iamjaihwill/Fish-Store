from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    label = "notifications"
    verbose_name = "Email & notifications"

    def ready(self):
        from apps.notifications import checks  # noqa: F401  (registers checks)
