"""Rule settings and weight profiles of a location group or a single location (never global)."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.tenancy.base import CompanyOwnedModel, exactly_one_scope_constraint
from apps.tenancy.models import Location, LocationGroup
from engine.rules_catalog import RULES, RULES_BY_CODE, validate_params


class ScopedModel(CompanyOwnedModel):
    """Belongs to exactly one of: a location group or a location. A location setting overrides the group one."""

    group = models.ForeignKey(
        LocationGroup, on_delete=models.CASCADE, null=True, blank=True, related_name="+", verbose_name="grupa"
    )
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, null=True, blank=True, related_name="+", verbose_name="lokal"
    )

    class Meta:
        abstract = True

    def _fill_company(self) -> None:
        if self.company_id is None:
            parent = self.group if self.group_id else self.location if self.location_id else None
            if parent is not None:
                self.company_id = parent.company_id

    @property
    def scope(self):
        return self.group or self.location


class RuleSetting(ScopedModel):
    rule_code = models.CharField("zasada", max_length=64, choices=[(rule.code, rule.label) for rule in RULES])
    enabled = models.BooleanField("włączona", default=True)
    is_hard = models.BooleanField("bez wyjątków", default=False)
    position = models.PositiveSmallIntegerField("miejsce na liście", help_text="1 = najważniejsza.")
    params = models.JSONField("parametry", default=dict, blank=True)

    class Meta:
        verbose_name = "zasada"
        verbose_name_plural = "zasady"
        ordering = ["group", "location", "position"]
        constraints = [
            exactly_one_scope_constraint("rule_setting_one_scope"),
            models.UniqueConstraint(
                fields=["group", "rule_code"], condition=Q(group__isnull=False), name="rule_setting_unique_in_group"
            ),
            models.UniqueConstraint(
                fields=["location", "rule_code"],
                condition=Q(location__isnull=False),
                name="rule_setting_unique_in_location",
            ),
            models.CheckConstraint(condition=Q(position__gte=1), name="rule_setting_position_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.position}. {RULES_BY_CODE[self.rule_code].label} ({self.scope})"

    def clean(self) -> None:
        super().clean()
        if self.rule_code not in RULES_BY_CODE:
            raise ValidationError({"rule_code": "Nieznana zasada."})
        problems = validate_params(self.rule_code, self.params or {})
        if problems:
            raise ValidationError({"params": problems})


def default_level_weights() -> dict[str, float]:
    # employee_budget: the most one person's text requests can weigh together (see engine.problem).
    return {
        "bardzo_wazne": 9.0,
        "wazne": 3.0,
        "mile_widziane": 1.0,
        "manager_higher": 2.0,
        "manager_lower": 0.5,
        "employee_budget": 12.0,
    }


class WeightProfile(ScopedModel):
    """How the generator weighs things. Never shown in the app; editable only in the Django admin."""

    manager_share = models.DecimalField(
        "udział zasad menedżera",
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.80"),
        validators=[MinValueValidator(Decimal("0.50")), MaxValueValidator(Decimal("1.00"))],
        help_text="0,80 = zasady menedżera ważą 80, prośby pracowników 20.",
    )
    level_weights = models.JSONField("wagi poziomów próśb", default=default_level_weights)
    rank_decay = models.DecimalField(
        "spadek wagi z miejscem na liście",
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.75"),
        validators=[MinValueValidator(Decimal("0.10")), MaxValueValidator(Decimal("0.99"))],
    )
    stability_penalty = models.DecimalField(
        "kara za zmianę opublikowanego grafiku", max_digits=6, decimal_places=2, default=Decimal("5.00")
    )

    class Meta:
        verbose_name = "profil wag"
        verbose_name_plural = "profile wag"
        constraints = [
            exactly_one_scope_constraint("weight_profile_one_scope"),
            models.UniqueConstraint(
                fields=["group"], condition=Q(group__isnull=False), name="weight_profile_unique_group"
            ),
            models.UniqueConstraint(
                fields=["location"], condition=Q(location__isnull=False), name="weight_profile_unique_location"
            ),
            models.CheckConstraint(
                condition=Q(manager_share__gte=Decimal("0.50"), manager_share__lte=Decimal("1.00")),
                name="weight_profile_manager_share_range",
            ),
            models.CheckConstraint(
                condition=Q(rank_decay__gt=0, rank_decay__lt=1), name="weight_profile_rank_decay_range"
            ),
        ]

    def __str__(self) -> str:
        return f"Profil wag: {self.scope}"
