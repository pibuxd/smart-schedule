"""How the rules of a location group and of a location become one ordered list (used by the generator,
the rules screen and its preview).

A location setting replaces the group setting for the same rule. All settings are ordered by their place on the
list; on the same place the location's own setting comes first. Switched-off rules stay in the list (the screen
shows them) but do not reach the engine.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from engine.problem import RuleConfig
from engine.rules_catalog import RULES, RULES_BY_CODE


class RuleRow(Protocol):
    rule_code: str
    enabled: bool
    is_hard: bool
    position: int
    params: dict[str, Any]


@dataclass(frozen=True)
class Row:
    """A rule setting that is not (yet) saved, e.g. a change the manager is previewing."""

    rule_code: str
    enabled: bool
    is_hard: bool
    position: int
    params: dict[str, Any] = field(default_factory=dict)


# Rules whose parameters point at a location's positions or shift types: they can only be set in a location.
LOCATION_ONLY_PARAMS = {"position", "shift_type"}
LOCATION_ONLY_RULES = frozenset(rule.code for rule in RULES if LOCATION_ONLY_PARAMS & set(rule.params))

# Numeric parameters: allowed range and the Polish name used in error messages.
NUMBER_PARAMS: dict[str, tuple[int, int, str]] = {
    "hours": (1, 24, "liczba godzin"),
    "days": (1, 14, "liczba dni"),
    "shifts": (1, 14, "liczba zmian"),
    "count": (1, 10, "liczba osób"),
}


def merge(group_rows: Iterable[RuleRow], location_rows: Iterable[RuleRow]) -> list[RuleRow]:
    """One list in order of importance, enabled and switched-off rules alike."""
    by_code: dict[str, tuple[int, int, RuleRow]] = {}
    for row in group_rows:
        by_code[row.rule_code] = (row.position, 1, row)
    for row in location_rows:
        by_code[row.rule_code] = (row.position, 0, row)  # the location's own setting wins
    return [row for _, _, row in sorted(by_code.values(), key=lambda v: (v[0], v[1], v[2].rule_code))]


def rule_configs(location_id: str, rows: Iterable[RuleRow]) -> list[RuleConfig]:
    """Enabled rules of one location as the engine sees them (rank = place among enabled rules)."""
    enabled = [row for row in rows if row.enabled and row.rule_code in RULES_BY_CODE]
    return [
        RuleConfig(code=row.rule_code, location=location_id, rank=rank, hard=row.is_hard, params=row.params or {})
        for rank, row in enumerate(enabled, start=1)
    ]


def same_setting(a: RuleRow, b: RuleRow) -> bool:
    return a.enabled == b.enabled and a.is_hard == b.is_hard and (a.params or {}) == (b.params or {})
