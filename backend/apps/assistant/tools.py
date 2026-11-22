"""Read-only tools for the assistant: the app's own `GET /api/...` endpoints, run as the person who wrote.

Each tool is one existing endpoint (the tool name is its operation id). The worker builds a GET request with
`RequestFactory`, sets `request.user` to the author of the message and dispatches it through Django's URL resolver,
so the endpoint checks permissions exactly as for the app: an employee sees what the employee's screens show, a
manager what the manager's screens show, and a 403/404 goes back to the model as a tool error. The server fills in
the company and the location; the model picks only periods, versions, shifts, months and how to narrow long lists.

There are no write tools on purpose: changes go through the manager's proposals (`services.check_plan`) or the
employee's preferences, and everything else the assistant only explains (where in the app to do it).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import quote

from django.test import RequestFactory
from django.urls import Resolver404, resolve

logger = logging.getLogger(__name__)

# One tool result goes back to the model in full up to this size; larger ones are cut with a note.
MAX_RESULT_CHARS = 40_000
# Never sent to the model: phone numbers (personal data), fields that only drive the screens, and money: pay,
# hourly rates and supplements stay in the app, out of the external AI service (docs/plan.md, section 35).
DROPPED_KEYS = frozenset(
    {
        "phone",
        "phone_e164",
        "revision",
        "headers",
        "link",
        "pay",
        "supplements_pay",
        "unpriced_hours",
        "hourly_rate",
        "rates",
        "supplements",
    }
)

NULLABLE_DATE = {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "YYYY-MM-DD albo null"}
NULLABLE_ID = {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "Identyfikator (UUID) albo null"}
ID = {"type": "string", "description": "Identyfikator (UUID) z kontekstu albo z wyniku innego narzędzia"}


@dataclass(frozen=True)
class Narrow:
    """How a long list in a result can be narrowed: `path` to the list ("" = the result itself, "a[].b" = list b of
    each item of list a) and the field holding the date or the person's name (dotted for nested objects)."""

    path: str
    date: str | None = None
    person: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApiTool:
    name: str
    path: str  # with {placeholders}; the rest of the parameters go to the query string
    description: str
    params: dict[str, dict] = field(default_factory=dict)  # what the model chooses (JSON schema of each value)
    fixed: dict[str, str] = field(default_factory=dict)  # filled by the server: name -> key in `Toolbox.ids`
    narrow: tuple[Narrow, ...] = ()

    def schema(self) -> dict:
        properties = dict(self.params)
        if any(n.date for n in self.narrow):
            properties["date_from"] = {**NULLABLE_DATE, "description": "Tylko pozycje od tego dnia (YYYY-MM-DD)."}
            properties["date_to"] = {**NULLABLE_DATE, "description": "Tylko pozycje do tego dnia (YYYY-MM-DD)."}
        if any(n.person for n in self.narrow):
            properties["person"] = {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "Tylko pozycje osoby, której imię lub nazwisko zawiera ten tekst.",
            }
        # Not `strict`: the API allows at most 16 union-typed parameters across all strict schemas of a request,
        # and the answer schema (`output_config.format`) already uses most of them. `argument_error` checks each
        # call against this schema instead, and a wrong argument comes back to the model as a tool error.
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        }


def _company(**more) -> dict[str, str]:
    return {"company_id": "company_id", **more}


EMPLOYEE_TOOLS = (
    ApiTool(
        "my_schedule",
        "/api/me/schedule",
        "Ekran „Mój grafik”: moje opublikowane zmiany, które się nie skończyły (shifts: data, godziny z grafiku, "
        "lokal, stanowisko, kto jest ze mną, czy oddaję zmianę), moje zmiany z ostatnich 14 dni (recent), przy "
        "zmianie godziny naprawdę zatwierdzone przez kierownika (worked) i moje zgłoszenie czekające na kierownika "
        "(report), oraz suma moich godzin w każdym miesiącu (liczy zatwierdzone godziny).",
        fixed=_company(),
        narrow=(Narrow("shifts", date="date"), Narrow("recent", date="date")),
    ),
    ApiTool(
        "my_availability",
        "/api/me/availability",
        "Okres, o który kierownik prosi o dyspozycje (daty, termin zaznaczania, czy wysłałem je przyciskiem "
        "„Wyślij kierownikowi”) i moje zaznaczenia w nim. Bez period_id: najbliższy okres, który zbiera dyspozycje.",
        params={"period_id": NULLABLE_ID},
        fixed=_company(),
        narrow=(Narrow("days", date="date"),),
    ),
    ApiTool(
        "my_calendar",
        "/api/me/calendar",
        "Ekran „Kiedy mogę”: moje zaznaczenia (cannot = nie mogę, prefer = chętnie; dzień bez wpisu = mogę) "
        "między dwiema datami, najwyżej 62 dni.",
        params={"start": {"type": "string", "description": "YYYY-MM-DD"}, "end": {"type": "string"}},
        fixed=_company(),
    ),
    ApiTool(
        "my_requests",
        "/api/me/requests",
        "Moje prośby tekstem na okres (period_id) albo na miesiąc bez okresu (month = pierwszy dzień miesiąca).",
        params={"period_id": NULLABLE_ID, "month": NULLABLE_DATE},
        fixed=_company(),
    ),
    ApiTool(
        "available_offers",
        "/api/me/offers",
        "„Zmiany do wzięcia”: zmiany oddane przez innych w firmie, które mogę teraz wziąć.",
        fixed=_company(),
        narrow=(Narrow("", date="shift.date"),),
    ),
    ApiTool(
        "my_notifications",
        "/api/me/notifications",
        "Moje najnowsze powiadomienia w aplikacji.",
        fixed=_company(),
    ),
)

MANAGER_TOOLS = (
    ApiTool(
        "manager_overview",
        "/api/manager/overview",
        "Ekran „Lokale”: moje lokale, bieżący okres każdego (status, termin, ile osób wysłało dyspozycje, "
        "ostatnia wersja grafiku) i stan dostępu firmy.",
        fixed=_company(),
    ),
    ApiTool(
        "location_periods",
        "/api/locations/{location_id}/periods",
        "Okresy grafiku tego lokalu z identyfikatorami wersji (published_version_id, latest_version_id), "
        "terminem dyspozycji i listą osób bez dyspozycji.",
        fixed={"location_id": "location_id"},
    ),
    ApiTool(
        "schedule_version",
        "/api/versions/{version_id}",
        "Jedna wersja grafiku (zakładka „Grafik”): zmiany z osobami (employee_name null = bez obsady), godziny "
        "osób, trzy oceny, zasady i ich złamania, niespełnione prośby. Długi: zawęź datami lub osobą.",
        params={"version_id": ID},
        narrow=(Narrow("shifts", date="date", person=("employee_name",)), Narrow("employees", person=("name",))),
    ),
    ApiTool(
        "explain_shift",
        "/api/versions/{version_id}/shifts/{shift_id}/explain",
        "Dlaczego na tej zmianie jest ta osoba albo nikt: powody i kto inny mógłby ją wziąć.",
        params={"version_id": ID, "shift_id": ID},
    ),
    ApiTool(
        "availability_grid",
        "/api/periods/{period_id}/availability",
        "Zakładka „Dyspozycje”: kto co zaznaczył w okresie (cannot = nie może, prefer = chętnie, brak = może), "
        "kto wysłał dyspozycje przyciskiem „Wyślij kierownikowi” (submitted_at) i zmiany po terminie.",
        params={"period_id": ID},
        narrow=(Narrow("employees[].days", date="date"), Narrow("employees", person=("name",))),
    ),
    ApiTool(
        "period_requests",
        "/api/periods/{period_id}/requests",
        "Prośby tekstem pracowników na okres i to, jak asystent je zrozumiał.",
        params={"period_id": ID},
        narrow=(Narrow("", person=("employee_name",)),),
    ),
    ApiTool(
        "location_employees",
        "/api/locations/{location_id}/employees",
        "Zakładka „Pracownicy”: osoby lokalu, stanowiska, stopień doświadczenia, maksimum i cel godzin.",
        fixed={"location_id": "location_id"},
        narrow=(Narrow("", person=("first_name", "last_name")),),
    ),
    ApiTool(
        "location_invitations",
        "/api/locations/{location_id}/invitations",
        "Zaproszenia do lokalu i to, czy ktoś je przyjął.",
        fixed={"location_id": "location_id"},
    ),
    ApiTool(
        "location_setup",
        "/api/locations/{location_id}/setup",
        "„Ustawienia lokalu”: stanowiska, zmiany z godzinami, obsada na dni tygodnia, inna obsada w wybrane dni, "
        "dni zamknięcia.",
        fixed={"location_id": "location_id"},
    ),
    ApiTool(
        "location_rules",
        "/api/scopes/location/{location_id}/rules",
        "Zakładka „Zasady”: zasady lokalu z katalogu, ich kolejność, liczby i „bez wyjątków”.",
        fixed={"location_id": "location_id"},
    ),
    ApiTool(
        "location_instructions",
        "/api/locations/{location_id}/instructions",
        "Zakładka „Ustalenia”: zasady i polecenia o osobach ustalone z asystentem na okres (bez period_id: bieżący).",
        params={"period_id": NULLABLE_ID},
        fixed={"location_id": "location_id"},
    ),
    ApiTool(
        "hours_report",
        "/api/reports/hours",
        "Ekran „Godziny”: godziny z opublikowanych grafików w miesiącu na osobę i lokal (zatwierdzone inne godziny "
        "liczą się zamiast grafiku; longer = nadgodziny, shorter = krótsze zmiany, w godzinach).",
        params={"month": {"type": "string", "description": "RRRR-MM"}},
        fixed=_company(),
        narrow=(Narrow("rows", person=("name",)),),
    ),
    ApiTool(
        "manager_offers",
        "/api/manager/offers",
        "Ekran „Oddane zmiany”: kto oddaje zmianę, kto chce ją wziąć, co czeka na decyzję.",
        fixed=_company(),
        narrow=(Narrow("offers", date="shift.date", person=("offered_by_name",)),),
    ),
    ApiTool(
        "manager_hours_changes",
        "/api/manager/hours-changes",
        "Ekran „Godziny”: zgłoszenia innych godzin (nadgodziny, wcześniejsze wyjście) czekające na decyzję "
        "(pending) i rozstrzygnięte w ostatnich 14 dniach (recent), z godzinami z grafiku i naprawdę.",
        fixed=_company(),
        narrow=(
            Narrow("pending", date="date", person=("employee_name",)),
            Narrow("recent", date="date", person=("employee_name",)),
        ),
    ),
    ApiTool(
        "handover_shifts",
        "/api/locations/{location_id}/handover-shifts",
        "Opublikowane zmiany lokalu (dwa tygodnie wstecz, dwa miesiące naprzód) z osobami, godzinami naprawdę "
        "(worked) i czekającym zgłoszeniem innych godzin (hours_report).",
        fixed={"location_id": "location_id"},
        narrow=(Narrow("", date="shift.date", person=("employee_name",)),),
    ),
    ApiTool(
        "subscription",
        "/api/companies/{company_id}/subscription",
        "Dostęp firmy: do kiedy działa i czy to okres próbny.",
        fixed=_company(),
    ),
    ApiTool(
        "my_notifications",
        "/api/me/notifications",
        "Moje najnowsze powiadomienia w aplikacji.",
        fixed=_company(),
    ),
    ApiTool(
        "my_schedule",
        "/api/me/schedule",
        "Moje własne opublikowane zmiany, jeśli sam pracuję na zmianach.",
        fixed=_company(),
        narrow=(Narrow("shifts", date="date"),),
    ),
)


JSON_TYPES = {"string": str, "null": type(None)}


def argument_error(tool: ApiTool, arguments: Any) -> str | None:
    """Why these arguments do not fit the tool's schema, or None. Tools are not `strict`, so the model may send a key
    the tool does not have (`employee_name` instead of `person`): the endpoint would ignore it and answer about
    everyone. Such a call is an error result the model can correct instead."""
    if not isinstance(arguments, dict):
        return "Błąd: argumenty muszą być obiektem JSON."
    properties = tool.schema()["input_schema"]["properties"]
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        accepted = ", ".join(properties) or "żadnych parametrów"
        return f"Błąd: nieznany parametr {', '.join(unknown)}. To narzędzie przyjmuje: {accepted}."
    for name, schema in properties.items():
        kinds = [option.get("type") for option in schema.get("anyOf", [schema])]
        if name not in arguments:
            if "null" not in kinds:
                return f"Błąd: brakuje parametru {name}."
            continue
        if not isinstance(arguments[name], tuple(JSON_TYPES[kind] for kind in kinds if kind in JSON_TYPES)):
            return f"Błąd: parametr {name} musi być typu {' albo '.join(kinds)}."
    return None


@dataclass
class Toolbox:
    """The tools of one role, run as `user`. `ids` fills the fixed parameters (company_id, location_id)."""

    user: Any
    tools: tuple[ApiTool, ...]
    ids: dict[str, str]
    calls: list[dict] = field(default_factory=list)

    def definitions(self) -> list[dict]:
        return [tool.schema() for tool in self.tools]

    def run(self, name: str, arguments: dict) -> tuple[str, bool]:
        """(text for the model, is_error). Never raises: a failing tool is an error result the model can read."""
        tool = next((t for t in self.tools if t.name == name), None)
        if tool is None:
            return "Nie ma takiego narzędzia.", True
        problem = argument_error(tool, arguments)
        if problem:
            self.calls.append({"tool": name, "status": 400})
            return problem, True
        arguments = dict(arguments or {})
        status, body = self._get(tool, arguments)
        self.calls.append({"tool": name, "status": status})
        if status != 200:
            detail = body.get("detail") if isinstance(body, dict) else None
            return f"Błąd {status}: {detail or 'nie udało się odczytać danych'}", True
        body = narrowed(tool, body, arguments)
        return fit(clean(body)), False

    def _get(self, tool: ApiTool, arguments: dict) -> tuple[int, Any]:
        values = {name: self.ids[key] for name, key in tool.fixed.items()}
        for name in tool.params:
            value = arguments.get(name)
            if value not in (None, ""):
                values[name] = str(value)
        path = tool.path
        for name in list(values):
            placeholder = "{" + name + "}"
            if placeholder in path:
                path = path.replace(placeholder, quote(values.pop(name), safe=""))
        if "{" in path:
            return 400, {"detail": "Brakuje identyfikatora w zapytaniu."}
        request = RequestFactory().get(path, values)
        request.user = self.user
        try:
            match = resolve(path)
        except Resolver404:
            return 404, {"detail": "Nie znaleziono."}
        try:
            response = match.func(request, *match.args, **match.kwargs)
            return response.status_code, json.loads(response.content or b"null")
        except Exception:
            logger.exception("assistant tool %s failed", tool.name)
            return 500, {"detail": "Błąd aplikacji."}


def employee_toolbox(user, company_id) -> Toolbox:
    return Toolbox(user=user, tools=EMPLOYEE_TOOLS, ids={"company_id": str(company_id)})


def manager_toolbox(user, company_id, location_id) -> Toolbox:
    return Toolbox(user=user, tools=MANAGER_TOOLS, ids={"company_id": str(company_id), "location_id": str(location_id)})


# --------------------------------------------------------------------------------------------- shaping results


WEEKDAYS = ("poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela")


def clean(value: Any) -> Any:
    """Without personal and screen-only fields, empty values and nulls: shorter for the model, same meaning.
    Every `date` gets its Polish weekday next to it, so the model never works out "sobota 21.11" by itself."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in DROPPED_KEYS:
                continue
            item = clean(item)
            if item is None or item == [] or item == {} or item == "":
                continue
            result[key] = item
        weekday = _weekday(result.get("date"))
        if weekday and "weekday" not in result:
            result["weekday"] = weekday
        return result
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def _field(item: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(item, dict):
            return None
        item = item.get(part)
    return item


def _parse_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _lists(body: Any, path: str):
    """Yield (container, key) pairs holding the lists at `path` ("" = the result itself, key None)."""
    if path == "":
        yield None, None
        return
    head, _, rest = path.partition(".")
    nested = head.endswith("[]")
    key = head.removesuffix("[]")
    if not isinstance(body, dict) or not isinstance(body.get(key), list):
        return
    if not rest:
        yield body, key
        return
    for item in body[key] if nested else []:
        yield from _lists(item, rest)


def _weekday(value: Any) -> str | None:
    day = _parse_day(value) if isinstance(value, str) and len(value) == 10 else None
    return WEEKDAYS[day.weekday()] if day else None


def narrowed(tool: ApiTool, body: Any, arguments: dict) -> Any:
    start, end = _parse_day(arguments.get("date_from")), _parse_day(arguments.get("date_to"))
    person = str(arguments.get("person") or "").strip().lower()
    if not (start or end or person):
        return body

    def keep(item, rule: Narrow) -> bool:
        if (start or end) and rule.date:
            day = _parse_day(_field(item, rule.date))
            if day is None or (start and day < start) or (end and day > end):
                return False
        if person and rule.person:
            words = " ".join(str(_field(item, f) or "") for f in rule.person).lower()
            if person not in words:
                return False
        return True

    for rule in tool.narrow:
        for container, key in _lists(body, rule.path):
            if container is None:
                if isinstance(body, list):
                    body = [item for item in body if keep(item, rule)]
            else:
                container[key] = [item for item in container[key] if keep(item, rule)]
    return body


def fit(body: Any, limit: int = MAX_RESULT_CHARS) -> str:
    """JSON text no longer than `limit`: the longest lists are cut in half until it fits, with a note."""
    text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= limit:
        return text
    cut = False
    for _ in range(40):
        longest = _longest_list(body)
        if longest is None:
            break
        container, key = longest
        items = body if container is None else container[key]
        half = items[: max(1, len(items) // 2)]
        if container is None:
            body = half
        else:
            container[key] = half
        cut = True
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if len(text) <= limit:
            break
    text = text[:limit]
    if cut:
        text += "\n[Wynik przycięty: część pozycji pominięto. Zawęź zapytanie (date_from, date_to, person).]"
    return text


def _longest_list(body: Any):
    best, best_len = None, 1

    def walk(value, container, key):
        nonlocal best, best_len
        if isinstance(value, list):
            if len(value) > best_len:
                best, best_len = (container, key), len(value)
            for item in value:
                _walk_children(item)
        elif isinstance(value, dict):
            _walk_children(value)

    def _walk_children(value):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, value, k)
        elif isinstance(value, list):
            for item in value:
                _walk_children(item)

    walk(body, None, None)
    return best
