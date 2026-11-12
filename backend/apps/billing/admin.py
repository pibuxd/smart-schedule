from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import AdminSplitDateTime
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import path
from django.utils import timezone

from apps.billing.codes import PREFIX_LENGTH, format_code, generate_code, hash_code
from apps.billing.models import AccessCode, CodeAttempt, CodeRedemption, GenerationUsage, Subscription
from apps.tenancy.admin_base import CompanyOwnedAdmin


class GenerateCodesForm(forms.Form):
    count = forms.IntegerField(label="Ile kodów", min_value=1, max_value=100, initial=1)
    days = forms.TypedChoiceField(label="Długość dostępu", choices=AccessCode.Days.choices, coerce=int, initial=30)
    max_uses = forms.IntegerField(
        label="Maks. liczba użyć każdego kodu",
        min_value=1,
        max_value=1000,
        initial=1,
        help_text="Ile firm może użyć kodu.",
    )
    valid_until = forms.SplitDateTimeField(
        label="Kod ważny do",
        required=False,
        widget=AdminSplitDateTime,
        help_text="Puste = kod nie traci ważności. To termin wpisania kodu, nie koniec dostępu.",
    )
    note = forms.CharField(label="Notatka", max_length=200, required=False, help_text="Np. nazwa firmy.")

    def clean_valid_until(self):
        valid_until = self.cleaned_data["valid_until"]
        if valid_until is not None and valid_until <= timezone.now():
            raise forms.ValidationError("Podaj datę w przyszłości.")
        return valid_until


@admin.register(AccessCode)
class AccessCodeAdmin(admin.ModelAdmin):
    """Codes are created only through "Dodaj" → the generate page, which shows the plain codes once."""

    list_display = ("prefix", "days", "uses", "max_uses", "valid_until", "note", "created_by", "created_at")
    list_filter = ("days",)
    search_fields = ("prefix", "note")
    # The length of access stays as generated; the note, the limit of uses and the deadline can be corrected.
    readonly_fields = ("prefix", "days", "uses", "created_by", "created_at")

    def get_urls(self):
        generate = path("generate/", self.admin_site.admin_view(self.generate_view), name="billing_accesscode_generate")
        return [generate, *super().get_urls()]

    def add_view(self, request, form_url="", extra_context=None):
        return redirect("admin:billing_accesscode_generate")

    def generate_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied
        form = GenerateCodesForm(request.POST or None)
        context = {**self.admin_site.each_context(request), "opts": self.model._meta, "title": "Kody dostępu"}
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data
            plain_codes = [generate_code() for _ in range(data["count"])]
            AccessCode.objects.bulk_create(
                AccessCode(
                    code_hash=hash_code(code),
                    prefix=code[:PREFIX_LENGTH],
                    days=data["days"],
                    max_uses=data["max_uses"],
                    valid_until=data["valid_until"],
                    note=data["note"],
                    created_by=request.user,
                )
                for code in plain_codes
            )
            context.update(
                codes=[format_code(code) for code in plain_codes],
                days=data["days"],
                max_uses=data["max_uses"],
                valid_until=data["valid_until"],
                note=data["note"],
            )
        else:
            context["form"] = form
            context["media"] = self.media + form.media
        return render(request, "admin/billing/accesscode/generate.html", context)


@admin.register(CodeRedemption)
class CodeRedemptionAdmin(CompanyOwnedAdmin):
    list_display = ("code", "company", "user", "days_added", "redeemed_at")
    list_select_related = ("company", "code", "user")
    raw_id_fields = ("user",)


@admin.register(CodeAttempt)
class CodeAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "ip", "at", "success")
    list_filter = ("success",)
    raw_id_fields = ("user",)


@admin.register(Subscription)
class SubscriptionAdmin(CompanyOwnedAdmin):
    list_display = ("company", "ends_at", "source", "status_label")


@admin.register(GenerationUsage)
class GenerationUsageAdmin(CompanyOwnedAdmin):
    list_display = ("company", "month", "count")
