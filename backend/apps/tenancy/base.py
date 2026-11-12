"""Base classes for company-owned data (tenant isolation).

Every table that holds a company's data inherits from `CompanyOwnedModel`:

- it has a NOT NULL, indexed `company_id`, also on child tables, so filtering never depends on joins;
- `Model.objects.for_company(company)` is the only way API code reads it (see `apps/tenancy/context.py`);
- saving checks that every foreign key to another company-owned row points into the same company,
  and the `m2m_changed` guard in `apps/tenancy/signals.py` does the same for many-to-many links.
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TenantQuerySet(models.QuerySet):
    def for_company(self, company) -> "TenantQuerySet":
        """Rows of one company. Accepts a Company instance or its id."""
        company_id = getattr(company, "pk", company)
        if company_id is None:
            raise ValueError("for_company() needs a company")
        return self.filter(company_id=company_id)


TenantManager = models.Manager.from_queryset(TenantQuerySet)


def is_company_owned(model) -> bool:
    return isinstance(model, type) and issubclass(model, CompanyOwnedModel)


class CompanyOwnedModel(UUIDModel):
    # blank=True: in forms the company may be left empty and is then copied from `company_from`.
    company = models.ForeignKey(
        "tenancy.Company", on_delete=models.CASCADE, related_name="+", blank=True, verbose_name="firma"
    )

    # Name of a foreign key the company is copied from when it is not set (e.g. "location").
    company_from: str | None = None

    objects = TenantManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.validate_same_company()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        self.validate_same_company()

    def _tenant_foreign_keys(self):
        for field in self._meta.concrete_fields:
            if field.is_relation and field.name != "company" and is_company_owned(field.related_model):
                yield field

    def _fill_company(self) -> None:
        if self.company_id is None and self.company_from:
            parent = getattr(self, self.company_from)
            if parent is not None:
                self.company_id = parent.company_id

    def validate_same_company(self) -> None:
        """Reject links to rows of another company (e.g. a position of company B on a shift of company A)."""
        self._fill_company()
        if self.company_id is None:
            raise ValidationError({"company": "Brak firmy."})
        errors = {}
        for field in self._tenant_foreign_keys():
            related_id = getattr(self, field.attname)
            if related_id is None:
                continue
            if field.is_cached(self):
                related_company_id = getattr(self, field.name).company_id
            else:
                related_company_id = (
                    field.related_model._base_manager.filter(pk=related_id).values_list("company_id", flat=True).first()
                )
            if related_company_id != self.company_id:
                errors[field.name] = "Ten obiekt należy do innej firmy."
        if errors:
            raise ValidationError(errors)


def exactly_one_scope_constraint(name: str) -> models.CheckConstraint:
    """`group` xor `location`: a setting belongs to a location group or to a single location."""
    return models.CheckConstraint(
        condition=(
            models.Q(group__isnull=False, location__isnull=True) | models.Q(group__isnull=True, location__isnull=False)
        ),
        name=name,
    )
