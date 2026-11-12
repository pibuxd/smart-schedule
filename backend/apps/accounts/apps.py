from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.accounts import checks  # noqa: F401 - registers the system check
