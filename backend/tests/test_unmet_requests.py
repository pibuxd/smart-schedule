"""The schedule card's unmet requests: the list is cut, the count is not, and the manager's instructions stay."""

from types import SimpleNamespace

from apps.scheduling.api import UNMET_LISTED, _unmet_requests
from engine.validator import RequestKind, RequestMeasure


def _loaded(people: int, instructions: set[int]):
    employees = [SimpleNamespace(id=f"e{i}", name=f"Osoba {i}") for i in range(people)]
    requests = [
        SimpleNamespace(id=f"r{i}", summary=f"Wolne {i}", employee=f"e{i}", location=None) for i in range(people)
    ]
    measures = tuple(
        RequestMeasure(
            location="L",
            employee=f"e{i}",
            kind=RequestKind.TEXT,
            weight=1.0,
            degree=1.0,
            request_id=f"r{i}",
            by_manager=i in instructions,
        )
        for i in range(people)
    )
    problem = SimpleNamespace(employees=employees, requests=requests, request_location=lambda r: "L")
    report = SimpleNamespace(requests=measures, unscored_requests=())
    return SimpleNamespace(problem=problem, report=report, location_id="L")


def test_the_count_covers_every_unmet_employee_request_and_instructions_are_never_cut():
    # 35 unmet: 34 employee requests and 1 manager instruction that sorts last (same weight, last employee id).
    listed, count = _unmet_requests(_loaded(35, instructions={34}))
    assert count == 34
    assert len([r for r in listed if r.kind == "text"]) == UNMET_LISTED
    assert [r.text for r in listed if r.kind == "instruction"] == ["Wolne 34"]


def test_a_short_list_is_not_cut():
    listed, count = _unmet_requests(_loaded(3, instructions=set()))
    assert count == 3
    assert [r.text for r in listed] == ["Wolne 0", "Wolne 1", "Wolne 2"]
