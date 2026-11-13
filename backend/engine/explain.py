"""Quick explanations for one slot of a schedule, and who else could take it. Pure Python, no solver.

For every person with the slot's position the validator checks the schedule as if that person took the slot
(about 5 ms per check on a month of one location). What changes is the explanation:

- hard problems that would appear ("nie mogę", another shift at that time, the labour code, a "no exceptions"
  rule): the person cannot take the slot;
- soft costs: their calendar wish for that day, rules they would break, their hours against the target;
- the three scores of the whole schedule after the change, so the manager sees what a swap costs.

The same answer serves "why is this slot empty / why this person" and the list of people in the manual editor.
A deeper analysis (re-running the solver with the slot forced) is left for later, on demand (spec, Generator g).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace

from engine.problem import AvailabilityState, Problem, Schedule
from engine.scoring import Scores, score
from engine.validator import Code, ValidationReport, validate

WISH_WORDS = {
    AvailabilityState.PREFER: "chętnie pracuje tego dnia",
    AvailabilityState.NEUTRAL: "nie zaznaczył(a) nic szczególnego",
    AvailabilityState.PREFER_NOT: "zaznaczył(a) „wolę nie”",
    AvailabilityState.CANNOT: "zaznaczył(a) „nie mogę”",
}

# Why someone cannot take a slot, in words for the summary of an empty slot.
_BLOCK_WORDS = {
    Code.CANNOT: "zaznaczone „nie mogę”",
    Code.OVERLAP: "inna zmiana w tym czasie",
    Code.LABOR_DAILY_REST: "za krótki odpoczynek (umowa o pracę)",
    Code.LABOR_DAILY_HOURS: "ponad 8 h na dobę (umowa o pracę)",
    Code.LABOR_WEEKLY_REST: "brak 35 h wolnego w tygodniu (umowa o pracę)",
    Code.RULE: "zasada „bez wyjątków”",
    Code.FROZEN: "ten dzień już minął",
}

# At most this many soft notes per person (the list must stay readable).
MAX_NOTES = 3


@dataclass(frozen=True)
class Candidate:
    employee: str
    name: str
    current: bool  # works this slot now
    blocked: tuple[str, ...]  # hard problems if they take it (empty: they can)
    block_code: Code | None  # the kind of the first hard problem
    notes: tuple[str, ...]  # soft costs: rules they would break
    wish: AvailabilityState  # their calendar mark for this slot
    hours: float  # their hours in this schedule if they take the slot
    target_hours: float | None
    max_hours: float | None
    scores: Scores  # the location's scores if they take the slot

    @property
    def possible(self) -> bool:
        return not self.blocked


@dataclass(frozen=True)
class SlotExplanation:
    slot: str
    employee: str | None
    summary: str
    candidates: tuple[Candidate, ...]  # the current person first, then those who can, then those who cannot


def _people(n: int) -> str:
    if n == 1:
        return "1 osoba"
    teen = 12 <= n % 100 <= 14
    return f"{n} {'osoby' if 2 <= n % 10 <= 4 and not teen else 'osób'}"


def _hours(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def without_pin(problem: Problem, slot_id: str) -> Problem:
    """A manual change moves the pin to the new person, so a pinned slot does not block the candidates."""
    if slot_id not in problem.pinned:
        return problem
    return replace(problem, pinned={k: v for k, v in problem.pinned.items() if k != slot_id})


def explain_slot(
    problem: Problem, schedule: Schedule, slot_id: str, base: ValidationReport | None = None
) -> SlotExplanation:
    """Why `slot_id` has its person (or nobody), and what every person with its position would change."""
    slot = problem.slot_by_id[slot_id]
    problem = without_pin(problem, slot_id)
    base = base or validate(problem, schedule)
    base_messages = {v.message for v in base.hard}
    current = schedule.get(slot_id)

    candidates = []
    for employee in problem.employees:
        if slot.position not in employee.positions:
            continue
        is_current = employee.id == current
        if not employee.available and not is_current:
            continue
        if is_current:
            report = base
            hard = [v for v in base.hard if slot_id in v.slots and v.employee in (None, employee.id)]
            notes = tuple(
                v.message for m in base.rules for v in m.violations if v.employee == employee.id and slot_id in v.slots
            )
        else:
            changed = dict(schedule)
            changed[slot_id] = employee.id
            report = validate(problem, changed)
            hard = [v for v in report.hard if v.message not in base_messages]
            notes = tuple(new_soft_violations(base, report, employee.id))
        candidates.append(
            Candidate(
                employee=employee.id,
                name=employee.name,
                current=is_current,
                blocked=tuple(v.message for v in hard),
                block_code=hard[0].code if hard else None,
                notes=notes[:MAX_NOTES],
                wish=problem.availability_for(employee.id, slot),
                hours=round(report.hours.get(employee.id, 0.0), 2),
                target_hours=employee.target_hours_month,
                max_hours=employee.max_hours_month,
                scores=score(problem, report, location=slot.location),
            )
        )

    def order(c: Candidate):
        wish_rank = {
            AvailabilityState.PREFER: 0,
            AvailabilityState.NEUTRAL: 1,
            AvailabilityState.PREFER_NOT: 2,
            AvailabilityState.CANNOT: 3,
        }[c.wish]
        return (not c.current, bool(c.blocked), c.scores.holes, -c.scores.manager_rules, wish_rank, c.name)

    candidates.sort(key=order)
    return SlotExplanation(
        slot=slot_id,
        employee=current,
        summary=_summary(problem, slot_id, current, candidates, base),
        candidates=tuple(candidates),
    )


def _summary(problem: Problem, slot_id: str, current: str | None, candidates: list[Candidate], base) -> str:
    slot = problem.slot_by_id[slot_id]
    position = problem.position_names.get(slot.position, "tym stanowisku")
    others = [c for c in candidates if not c.current]
    able = [c for c in others if c.possible]
    if current is None:
        if not others:
            return f"Nikt w tym lokalu nie pracuje na stanowisku {position}, więc nie było kogo wpisać."
        if not able:
            reasons: Counter[str] = Counter()
            for candidate in others:
                reasons[_BLOCK_WORDS.get(candidate.block_code, "inny powód")] += 1
            parts = [f"{words} ({_people(n)})" for words, n in reasons.most_common()]
            return "Nikt nie mógł wziąć tej zmiany. Powody: " + ", ".join(parts) + "."
        return (
            f"Tę zmianę może wziąć {_people(len(able))} z listy niżej, ale każda z tych osób jest potrzebna gdzie "
            "indziej albo złamałaby ważniejsze zasady. Możesz wpisać kogoś ręcznie."
        )
    person = next((c for c in candidates if c.current), None)
    if person is None:  # the person lost the position since; the validator reports it
        return "Osoba na tej zmianie nie pracuje już na tym stanowisku."
    text = f"{person.name} {WISH_WORDS[person.wish]}; ma w tym grafiku {_hours(person.hours)} h"
    if person.target_hours:
        text += f" (cel na miesiąc: {_hours(person.target_hours)} h)"
    text += "."
    if able:
        text += f" Zamiast tej osoby może pracować jeszcze {_people(len(able))}."
    else:
        text += " Nikt inny nie mógł wziąć tej zmiany."
    return text


def new_soft_violations(base: ValidationReport, after: ValidationReport, employee: str | None = None) -> list[str]:
    """Messages of soft rules that got worse (higher degree) after a change, optionally only about one person.
    A rule that got better (e.g. hours closer to the target) is not a cost, even if its message changed."""
    before = {(m.location, m.code): m.degree for m in base.rules}
    known = {v.message for m in base.rules for v in m.violations}
    return [
        v.message
        for m in after.rules
        if not m.hard and m.degree > before.get((m.location, m.code), 0.0) + 1e-9
        for v in m.violations
        if v.message not in known and (employee is None or v.employee in (None, employee))
    ]


def scores_after(
    problem: Problem, schedule: Schedule, changes: Mapping[str, str | None], location: str | None = None
) -> tuple[ValidationReport, Scores]:
    """Validate `schedule` with `changes` applied; for the manual-edit check."""
    changed = {**schedule, **changes}
    report = validate(problem, changed)
    return report, score(problem, report, location=location)
