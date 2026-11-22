"""The employee's assistant asks one question back instead of guessing, and saves nothing until the person answers."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.assistant import context, llm, services
from apps.assistant.management.commands.assistant_misses import misses
from apps.availability.models import TextRequest
from apps.scheduling.problem_builder import build_problem
from tests.test_assistant import add_worker, reading, send_request
from tests.test_assistant import shop as shop
from tests.test_assistant import with_key as with_key


def asking(question: str, answer: str = "", **preference) -> llm.EmployeeReply:
    """The assistant's answer with a question back (and, when given, a preference it would have saved)."""
    reply = reading(**preference) if preference else reading(type="inne", weekdays=[])
    return reply.model_copy(update={"question": question, "answer": answer, "leave_to_manager": False})


def answering(reply: llm.EmployeeReply, number: int = 1) -> llm.EmployeeReply:
    return reply.model_copy(update={"answers_question": number})


class Model:
    """A fake `llm.read_request` that answers each message in turn and keeps what it was sent."""

    def __init__(self, monkeypatch, *answers: llm.EmployeeReply):
        self.answers, self.seen = list(answers), []
        monkeypatch.setattr(llm, "read_request", self)

    def __call__(self, text, context, toolbox=None):
        self.seen.append((text, context))
        return self.answers.pop(0)


def write(api, shop, text: str) -> TextRequest:
    pk = send_request(api, shop, text).json()["id"]
    services.interpret_request(pk)
    return TextRequest.objects.get(pk=pk)


def my_requests(api, shop) -> list[dict]:
    return api.get(f"/api/me/requests?company_id={shop['company'].pk}&period_id={shop['period'].pk}").json()


def manager_requests(api, shop) -> list[dict]:
    api.login(shop["manager"])
    return api.get(f"/api/periods/{shop['period'].pk}/requests").json()


@pytest.fixture
def two_anias(shop):
    shop["ania_k"] = add_worker(shop, "Ania", "Kowalska")
    shop["ania_m"] = add_worker(shop, "Ania", "Mazur")
    return shop


def test_less_work_is_asked_about_and_the_answer_is_saved_with_the_first_message(api, shop, with_key, monkeypatch):
    model = Model(
        monkeypatch,
        asking("Ile najwyżej godzin w tygodniu chcesz pracować?"),
        answering(reading(type="limit_godzin", max_hours=30, hours_period="week", weekdays=[])),
    )
    api.login(shop["worker"])
    first = write(api, shop, "Chcę mniej pracować.")
    assert first.status == "answered" and first.interpretation is None
    assert first.question == "Ile najwyżej godzin w tygodniu chcesz pracować?"
    # Nothing is saved: no request for the generator, nothing for the manager.
    assert build_problem([shop["period"]]).problem.requests == ()
    [shown] = my_requests(api, shop)
    assert shown["question"] == first.question and shown["summary"] is None and shown["waiting"] is True
    assert manager_requests(api, shop) == []

    api.login(shop["worker"])
    second = write(api, shop, "Najwyżej 30 godzin.")
    text, context = model.seen[1]
    assert text == "Najwyżej 30 godzin."
    assert "Twoje pytania do tej osoby" in context and "Chcę mniej pracować." in context
    assert second.status == "interpreted" and second.answer_to_id == first.pk
    assert [r["waiting"] for r in my_requests(api, shop)] == [False, False]  # answered
    [request] = build_problem([shop["period"]]).problem.requests
    assert request.type == "hours_limit" and request.max_hours == 30
    [listed] = manager_requests(api, shop)
    assert listed["text"] == "Najwyżej 30 godzin."
    assert listed["asked"] == {"text": "Chcę mniej pracować.", "question": first.question}


def test_a_name_two_people_share_is_asked_about_even_if_the_model_guessed(api, two_anias, with_key, monkeypatch):
    shop = two_anias
    model = Model(
        monkeypatch,
        reading(type="unikaj_osoby", person="Ania", weekdays=[]),  # the model did not ask
        answering(reading(type="unikaj_osoby", person="Ania M.", weekdays=[])),
    )
    api.login(shop["worker"])
    first = write(api, shop, "Nie mogę z Anią.")
    assert first.status == "answered" and first.question == "O którą osobę chodzi: Ania K. czy Ania M.?"
    assert "Ania K." in model.seen[0][1] and "Ania M." in model.seen[0][1]  # the model sees both
    assert build_problem([shop["period"]]).problem.requests == ()

    second = write(api, shop, "Ania Mazur.")
    assert second.status == "interpreted"
    assert second.interpretation["subject_employee"] == str(shop["ania_m"].pk)


def test_what_is_still_unclear_after_the_answer_goes_to_the_manager_with_both_messages(
    api, shop, with_key, monkeypatch
):
    question = "Od kiedy i na których zmianach nie możesz dźwigać?"
    Model(
        monkeypatch,
        asking(question),
        answering(reading(type="inne", weekdays=[], answer="Kierownik przeczyta to sam.")),
    )
    api.login(shop["worker"])
    first = write(api, shop, "Po zabiegu kolana nie mogę dźwigać blach przez dwa tygodnie.")
    assert first.status == "answered" and first.question == question
    second = write(api, shop, "Od poniedziałku, przy piecu.")
    assert second.status == "needs_manager" and second.unread_reason == "unsure"
    assert second.answer_to_id == first.pk
    [listed] = manager_requests(api, shop)
    assert listed["text"] == "Od poniedziałku, przy piecu." and listed["unread_reason"] == "unsure"
    assert listed["asked"] == {
        "text": "Po zabiegu kolana nie mogę dźwigać blach przez dwa tygodnie.",
        "question": question,
    }
    # The list of misses has the whole exchange; the question alone is no miss.
    [miss] = [m for m in misses(timezone.now() - timedelta(days=1)) if m[1] == "request"]
    assert miss[4] == f"{first.text} | pytanie: {question} | odpowiedź: {second.text}" and miss[5] == "unsure"


def test_the_assistant_asks_only_once(api, two_anias, with_key, monkeypatch):
    shop = two_anias
    Model(
        monkeypatch,
        asking("Ile godzin?"),
        answering(asking("A w które dni?")),
    )
    api.login(shop["worker"])
    first = write(api, shop, "Chcę mniej pracować.")
    second = write(api, shop, "Trochę mniej.")
    assert second.status == "needs_manager" and second.unread_reason == "unsure" and second.question == ""
    assert second.assistant_answer["why"] == "drugie pytanie" and second.answer_to_id == first.pk


def test_an_answer_naming_a_namesake_again_is_not_asked_twice(api, two_anias, with_key, monkeypatch):
    shop = two_anias
    Model(
        monkeypatch,
        asking("O którą osobę chodzi: Ania K. czy Ania M.?"),
        answering(reading(type="unikaj_osoby", person="Ania", weekdays=[])),
    )
    api.login(shop["worker"])
    write(api, shop, "Nie mogę z Anią.")
    second = write(api, shop, "Z Anią.")
    assert second.status == "needs_manager" and second.question == ""


def test_a_question_saves_nothing_even_of_what_the_model_was_sure_of(api, shop, with_key, monkeypatch):
    Model(monkeypatch, asking("Którą zmianę masz na myśli?", answer="Masz zmianę w sobotę.", weekdays=[5]))
    api.login(shop["worker"])
    row = write(api, shop, "Kiedy pracuję? I nie chcę tej zmiany w piątki.")
    assert row.status == "answered" and row.interpretation is None
    assert row.reply == "Masz zmianę w sobotę." and row.question == "Którą zmianę masz na myśli?"
    assert build_problem([shop["period"]]).problem.requests == ()


def test_the_question_waits_while_the_person_writes_about_something_else(api, shop, with_key, monkeypatch):
    model = Model(
        monkeypatch,
        asking("Ile godzin?"),
        reading(),  # about something else: the question waits
        answering(reading(type="limit_godzin", max_hours=30, hours_period="week", weekdays=[])),
    )
    api.login(shop["worker"])
    first = write(api, shop, "Chcę mniej pracować.")
    other = write(api, shop, "Wolałabym nie pracować w piątki.")
    assert other.status == "interpreted" and other.answer_to_id is None
    assert "Twoje pytania do tej osoby" in model.seen[1][1]
    assert [(r["waiting"], r["can_answer"]) for r in my_requests(api, shop)] == [(True, True), (False, False)]

    third = write(api, shop, "Najwyżej 30 godzin.")
    assert "Chcę mniej pracować." in model.seen[2][1] and "Twoje pytania do tej osoby" in model.seen[2][1]
    assert third.status == "interpreted" and third.answer_to_id == first.pk
    assert [r["waiting"] for r in my_requests(api, shop)] == [False, False, False]


def test_a_question_waits_only_as_long_as_the_assistant_remembers_it(api, shop, with_key, monkeypatch):
    model = Model(monkeypatch, asking("Ile godzin?"), *[reading()] * (context.MAX_CONVERSATION + 1))
    api.login(shop["worker"])
    write(api, shop, "Chcę mniej pracować.")
    for _ in range(context.MAX_CONVERSATION - 1):
        write(api, shop, "Wolałabym nie pracować w piątki.")
    assert my_requests(api, shop)[0]["can_answer"] is True
    write(api, shop, "Wolałabym nie pracować w piątki.")
    assert "Twoje pytania do tej osoby" in model.seen[-1][1]  # the tenth message still saw it
    [oldest, *_] = my_requests(api, shop)
    assert oldest["waiting"] is True and oldest["can_answer"] is False  # written again from "Twoje prośby"
    write(api, shop, "Wolałabym nie pracować w piątki.")
    assert "Twoje pytania do tej osoby" not in model.seen[-1][1]


def test_an_answer_to_an_unknown_question_number_is_read_as_a_new_message(api, shop, with_key, monkeypatch):
    Model(monkeypatch, asking("Ile godzin?"), answering(reading(), number=5))
    api.login(shop["worker"])
    write(api, shop, "Chcę mniej pracować.")
    second = write(api, shop, "Wolałabym nie pracować w piątki.")
    assert second.status == "interpreted" and second.answer_to_id is None


def test_the_question_can_go_to_the_manager_instead_and_is_reset_when_rewritten(api, shop, with_key, monkeypatch):
    Model(monkeypatch, asking("Ile godzin?"), reading())
    api.login(shop["worker"])
    first = write(api, shop, "Chcę mniej pracować.")
    body = api.patch(f"/api/me/requests/{first.pk}", {"text": "Wolałabym nie pracować w piątki."}).json()
    assert body["status"] == "new" and body["question"] is None
    assert TextRequest.objects.get(pk=first.pk).question == ""
    assert services.interpret_request(str(first.pk)) == "interpreted"

    Model(monkeypatch, asking("Ile godzin?"))
    second = write(api, shop, "Chcę mniej pracować.")
    body = api.patch(f"/api/me/requests/{second.pk}", {"understood": False}).json()
    assert body["status"] == "needs_manager" and body["question"] is None
