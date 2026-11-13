"""Catalog of schedule rules a location can switch on, order and tune. Pure Python, no Django.

A location never invents rules: it enables rules from this list and sets their parameters. How each rule is
counted as a violation is implemented in the validator and the solver (stages 4 and 5).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuleDefinition:
    code: str
    label: str  # Polish text for the manager
    description: str
    default_enabled: bool = True
    default_hard: bool = False
    params: dict[str, Any] = field(default_factory=dict)
    # True for "good practice" rules that start enabled in every new location.
    good_practice: bool = False


RULES: tuple[RuleDefinition, ...] = (
    RuleDefinition(
        code="min_rest_between_shifts",
        label="Odpoczynek między zmianami",
        description="Co najmniej tyle godzin przerwy między końcem jednej a początkiem kolejnej zmiany.",
        params={"hours": 11},
        good_practice=True,
    ),
    RuleDefinition(
        code="max_consecutive_days",
        label="Dni pracy z rzędu",
        description="Nie więcej niż tyle dni pracy pod rząd.",
        params={"days": 6},
        good_practice=True,
    ),
    RuleDefinition(
        code="fair_weekends",
        label="Równy podział weekendów",
        description="Praca w soboty i niedziele rozłożona po równo między osoby na tym samym stanowisku.",
        good_practice=True,
    ),
    RuleDefinition(
        code="fair_closings",
        label="Równy podział zamknięć",
        description="Zmiany zamykające rozłożone po równo.",
        good_practice=True,
    ),
    RuleDefinition(
        code="target_hours",
        label="Cel godzin",
        description="Każdy dostaje liczbę godzin bliską swojemu celowi na miesiąc.",
    ),
    RuleDefinition(
        code="personal_max_hours",
        label="Osobiste maksimum godzin",
        description="Nie przekraczaj maksimum godzin ustawionego dla pracownika.",
    ),
    RuleDefinition(
        code="preferred_shift_type_for_position",
        label="Stała pora dla stanowiska",
        description="Osoby na danym stanowisku dostają głównie wybrany typ zmiany (np. piekarze noce).",
        default_enabled=False,
        params={"position": None, "shift_type": None},
    ),
    RuleDefinition(
        code="min_position_on_closing",
        label="Ktoś odpowiedzialny na zamknięciu",
        description="Na każdej zmianie zamykającej jest co najmniej jedna osoba z wybranego stanowiska.",
        default_enabled=False,
        params={"position": None, "count": 1},
    ),
    RuleDefinition(
        code="same_shift_type_in_week",
        label="Ta sama pora przez cały tydzień",
        description="W jednym tygodniu osoba pracuje na tej samej porze (rano albo popołudniu).",
        default_enabled=False,
    ),
    RuleDefinition(
        code="max_shifts_per_week",
        label="Zmiany w tygodniu",
        description="Nie więcej niż tyle zmian w tygodniu na osobę.",
        default_enabled=False,
        params={"shifts": 5},
    ),
    RuleDefinition(
        code="max_hours_per_day",
        label="Godziny pracy w ciągu dnia",
        description=(
            "Nie więcej niż tyle godzin pracy w zmianach zaczynających się tego samego dnia "
            "(nocna zmiana liczy się w całości do dnia, w którym się zaczyna)."
        ),
        default_enabled=False,
        params={"max_hours": 8},
    ),
    RuleDefinition(
        code="min_weekly_rest",
        label="Wolne w tygodniu",
        description="W każdym tygodniu (od poniedziałku) co najmniej tyle godzin wolnego bez przerwy.",
        default_enabled=False,
        params={"rest_hours": 35},
    ),
)

RULES_BY_CODE: dict[str, RuleDefinition] = {rule.code: rule for rule in RULES}


def get_rule(code: str) -> RuleDefinition:
    try:
        return RULES_BY_CODE[code]
    except KeyError:
        raise KeyError(f"Unknown rule code: {code}") from None


def validate_params(code: str, params: dict[str, Any]) -> list[str]:
    """Return problems with `params` for rule `code` (unknown keys); an empty list means OK."""
    allowed = set(get_rule(code).params)
    return [f"Nieznany parametr: {key}" for key in params if key not in allowed]
