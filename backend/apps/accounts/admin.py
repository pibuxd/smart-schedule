from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from apps.accounts.models import LoginCode, User, normalize_phone


class PhoneCleanMixin:
    def clean_phone_e164(self):
        return normalize_phone(self.cleaned_data["phone_e164"])


class UserCreateForm(PhoneCleanMixin, AdminUserCreationForm):
    class Meta:
        model = User
        fields = ("phone_e164", "first_name", "last_name")


class UserEditForm(PhoneCleanMixin, UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"
        field_classes: dict[str, type[forms.Field]] = {}


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserEditForm
    add_form = UserCreateForm
    ordering = ("last_name", "first_name")
    list_display = ("phone_e164", "first_name", "last_name", "is_staff", "is_active", "date_joined")
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("phone_e164", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("phone_e164", "password")}),
        ("Dane osobowe", {"fields": ("first_name", "last_name")}),
        ("Uprawnienia", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Daty", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone_e164", "first_name", "last_name", "usable_password", "password1", "password2"),
            },
        ),
    )


@admin.register(LoginCode)
class LoginCodeAdmin(admin.ModelAdmin):
    list_display = ("phone_e164", "created_at", "expires_at", "attempts", "used_at", "ip")
    search_fields = ("phone_e164",)
    readonly_fields = ("phone_e164", "code_hash", "created_at", "expires_at", "attempts", "used_at", "ip")

    def has_add_permission(self, request):
        return False
