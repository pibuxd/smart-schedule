from django.contrib import admin


class CompanyOwnedAdmin(admin.ModelAdmin):
    """Superadmin view of company data: always filterable by company, company shown in every list."""

    list_filter: tuple = ("company",)
    list_select_related = ("company",)
    list_per_page = 50
