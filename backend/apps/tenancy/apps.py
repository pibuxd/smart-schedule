from django.apps import AppConfig


class TenancyConfig(AppConfig):
    name = "apps.tenancy"
    label = "tenancy"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.tenancy import signals  # noqa: F401  (registers the m2m guard)
