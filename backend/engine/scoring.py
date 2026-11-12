"""The three numbers the manager sees, computed the same way for every schedule (generated or edited by hand).

- unfilled slots (a schedule with any is "incomplete" and must not look good),
- "manager rules" in % (location rules, good-practice rules, target hours),
- "employee requests" in % ("wolę nie" and "chętnie" from the calendar and text requests).

A group score is 100 × (1 − Σ wᵢ·vᵢ / Σ wᵢ) with vᵢ the degree (0–1) to which item i is broken.
For rules wᵢ comes from the place on the location's list (each next rule weighs `rank_decay` times less), so
"everything is most important" cannot happen. Hard ("no exceptions") rules are constraints, not part of the score.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from engine.problem import Problem
from engine.validator import RequestMeasure, RuleMeasure, ValidationReport


@dataclass(frozen=True)
class Scores:
    holes: int
    slots: int
    manager_rules: float  # 0–100
    employee_requests: float  # 0–100
    stability_changes: int
    hard_violations: int

    @property
    def is_complete(self) -> bool:
        return self.holes == 0

    @property
    def is_valid(self) -> bool:
        return self.hard_violations == 0

    def as_dict(self) -> dict[str, float | int | bool]:
        return {**asdict(self), "is_complete": self.is_complete, "is_valid": self.is_valid}


def _percent(items: Iterable[tuple[float, float]]) -> float:
    total = weighted = 0.0
    for weight, degree in items:
        total += weight
        weighted += weight * degree
    return 100.0 * (1 - weighted / total) if total else 100.0


def rule_weights(problem: Problem, report: ValidationReport) -> dict[tuple[str, str], float]:
    """(location, rule code) -> weight of every soft rule, from its place among that location's soft rules."""
    by_location: dict[str, list[RuleMeasure]] = defaultdict(list)
    for measure in report.rules:
        if not measure.hard:
            by_location[measure.location].append(measure)
    weights = {}
    for location, measures in by_location.items():
        for place, measure in enumerate(sorted(measures, key=lambda m: m.rank), start=1):
            weights[(location, measure.code)] = problem.weights.rule_weight(place)
    return weights


def _in(location: str | None, item_location: str) -> bool:
    return location is None or item_location == location


def score(problem: Problem, report: ValidationReport, location: str | None = None) -> Scores:
    """Scores of the whole problem, or of one location (a group run gives one schedule version per location)."""
    weights = rule_weights(problem, report)
    rules = [
        (weights[(m.location, m.code)], m.degree)
        for m in report.rules
        if not m.hard and m.instances and _in(location, m.location)
    ]
    requests = [(r.weight, r.degree) for r in report.requests if _in(location, r.location)]
    slots = [s for s in problem.slots if _in(location, s.location)]
    ids = {s.id for s in slots}
    hard = [v for v in report.hard if location is None or v.location == location or ids.intersection(v.slots)]
    return Scores(
        holes=sum(1 for slot_id in report.holes if slot_id in ids),
        slots=len(slots),
        manager_rules=round(_percent(rules), 2),
        employee_requests=round(_percent(requests), 2),
        stability_changes=sum(1 for slot_id in report.stability_changes if slot_id in ids),
        hard_violations=len(hard),
    )


def penalty(problem: Problem, report: ValidationReport) -> float:
    """What the generator minimises once the number of unfilled slots is as low as it can be (lower is better).

    Points on the 0–100 scale: manager_share × (100 − manager %) + (1 − manager_share) × (100 − requests %)
    + stability_penalty for each changed published assignment. Compare schedules with the same number of holes.
    """
    scores = score(problem, report)
    share = problem.weights.manager_share
    return (
        share * (100 - scores.manager_rules)
        + (1 - share) * (100 - scores.employee_requests)
        + problem.weights.stability_penalty * scores.stability_changes
    )


def unmet_requests(report: ValidationReport, location: str | None = None) -> list[RequestMeasure]:
    """Requests not (fully) kept, most important first; for explanations and the rule preview (stages 7–8)."""
    unmet = [r for r in report.requests if r.degree > 0 and _in(location, r.location)]
    return sorted(unmet, key=lambda r: (-r.weight * r.degree, r.employee))
