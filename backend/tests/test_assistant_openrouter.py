"""The assistant on OpenRouter (21.11.2026): OpenAI-compatible chat completions with a fake HTTP transport."""

import json

import httpx2
import openai
import pytest
from openai import DefaultHttpxClient

from apps.assistant import llm
from tests.test_assistant import question, reading


def chat(*, calls=None, text="", finish="tool_calls", reasoning=True, provider="Fake", cost=0.0001):
    """One chat completion as OpenRouter returns it. `calls` = [(name, arguments as a dict or raw text)]."""
    message: dict = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = [
            {
                "id": f"call_{n}",
                "type": "function",
                "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)},
            }
            for n, (name, args) in enumerate(calls)
        ]
    if reasoning:
        message["reasoning_details"] = [{"type": "reasoning.text", "text": "Sprawdzę grafik.", "index": 0}]
    return {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 0,
        "model": llm.settings.OPENROUTER_MODEL,
        "provider": provider,
        "choices": [{"index": 0, "finish_reason": finish, "message": message}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110, "cost": cost},
    }


def answer(model) -> tuple[str, dict]:
    return (llm.ANSWER_TOOL, model.model_dump(mode="json"))


READ = ("my_schedule", {})


@pytest.fixture
def fake_openrouter(settings, monkeypatch):
    """Answers each request with the next given body (the last one repeats); returns the requests sent."""
    settings.OPENROUTER_API_KEY = "test-key"
    sent, replies = [], []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append({"url": str(request.url), "auth": request.headers["authorization"], **json.loads(request.content)})
        status, body = replies[min(len(sent), len(replies)) - 1]
        return httpx2.Response(status, json=body)

    def respond(*bodies):
        replies[:] = [body if isinstance(body, tuple) else (200, body) for body in bodies]
        return sent

    client = openai.OpenAI(
        base_url=llm.OPENROUTER_URL,
        api_key="test-key",
        max_retries=0,
        http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    monkeypatch.setattr(llm, "openrouter_client", lambda: client)
    return respond


class StubBox:
    def __init__(self):
        self.calls = []

    def definitions(self):
        return [{"name": "my_schedule", "description": "x", "input_schema": {"type": "object", "properties": {}}}]

    def run(self, name, arguments):
        self.calls.append((name, arguments))
        return '{"shifts":[{"date":"2026-11-21"}]}', False


def test_the_key_that_is_set_picks_the_api(settings):
    assert (llm.backend(), llm.is_enabled()) == (None, False)
    settings.ANTHROPIC_API_KEY = "a"
    assert llm.backend() == "anthropic"
    settings.OPENROUTER_API_KEY = "o"
    assert llm.backend() == "openrouter"  # both set: OpenRouter
    settings.ANTHROPIC_API_KEY = ""
    assert (llm.backend(), llm.is_enabled()) == ("openrouter", True)


def test_tool_results_and_reasoning_go_back_before_the_answer(fake_openrouter, settings):
    settings.OPENROUTER_EFFORT = "low"
    sent = fake_openrouter(chat(calls=[READ]), chat(calls=[answer(question("W sobotę 21.11."))]))
    box = StubBox()

    assert llm.read_request("Kiedy pracuję?", "Dzisiaj: …", box).answer == "W sobotę 21.11."

    assert box.calls == [("my_schedule", {})] and len(sent) == 2
    first, second = sent
    assert first["url"] == "https://openrouter.ai/api/v1/chat/completions" and first["auth"] == "Bearer test-key"
    assert first["model"] == "deepseek/deepseek-v4.1-flash"
    assert [t["function"]["name"] for t in first["tools"]] == ["my_schedule", llm.ANSWER_TOOL]
    assert first["tool_choice"] == "required"
    assert first["reasoning"] == {"effort": "low"}
    # Only providers that take every parameter sent and do not keep prompts: messages carry names and schedules.
    assert first["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert "response_format" not in first  # with tools it would force JSON on every round
    assert first["messages"][0]["role"] == "system" and llm.ANSWER_TOOL in first["messages"][0]["content"]
    assert "Kiedy pracuję?" in first["messages"][1]["content"]
    _, _, assistant, result = second["messages"]
    assert assistant["tool_calls"][0]["function"]["name"] == "my_schedule"
    assert assistant["reasoning_details"][0]["text"] == "Sprawdzę grafik."
    assert result == {"role": "tool", "tool_call_id": "call_0", "content": '{"shifts":[{"date":"2026-11-21"}]}'}


def test_after_the_last_round_only_the_answer_is_left(fake_openrouter):
    sent = fake_openrouter(*[chat(calls=[READ])] * llm.MAX_TOOL_ROUNDS, chat(calls=[answer(question())]))
    llm.read_request("Kiedy pracuję?", "Dzisiaj: …", StubBox())
    assert len(sent) == llm.MAX_TOOL_ROUNDS + 1
    assert sent[-1]["tool_choice"] == {"type": "function", "function": {"name": llm.ANSWER_TOOL}}
    assert {r["tool_choice"] for r in sent[:-1]} == {"required"}


def test_a_wrong_answer_goes_back_to_the_model_and_an_empty_list_may_be_null(fake_openrouter):
    """Tool arguments are not constrained to the schema: DeepSeek sometimes wrote null for a list (21.11.2026)."""
    wrong = reading().model_dump(mode="json")
    wrong["preferences"][0]["level"] = "pilne"
    right = reading().model_dump(mode="json")
    right["preferences"][0]["dates"] = None
    sent = fake_openrouter(chat(calls=[(llm.ANSWER_TOOL, wrong)]), chat(calls=[(llm.ANSWER_TOOL, right)]))

    result = llm.read_request("Wolałabym nie pracować w piątki.", "Okres grafiku: …")

    assert result == reading() and result.preferences[0].dates == []
    feedback = sent[1]["messages"][-1]
    assert feedback["role"] == "tool" and feedback["content"].startswith("Błąd: odpowiedź nie pasuje do schematu")
    assert "preferences.0.level" in feedback["content"]


def test_an_answer_that_stays_wrong_is_an_error(fake_openrouter):
    sent = fake_openrouter(chat(calls=[(llm.ANSWER_TOOL, "{nie json")]))
    with pytest.raises(llm.AssistantError, match="invalid answer"):
        llm.plan_command("x", "y")
    assert len(sent) == llm.MAX_TOOL_ROUNDS + 1


def test_a_provider_that_answers_in_text_is_read_or_asked_again(fake_openrouter):
    """`tool_choice` is honoured by the providers tried, but a text answer must not be lost or shown raw."""
    final = json.dumps(question("W sobotę.").model_dump(mode="json"))
    sent = fake_openrouter(
        chat(text="Masz zmianę w sobotę.", finish="stop"), chat(text=f"```json\n{final}\n```", finish="stop")
    )
    assert llm.read_request("Kiedy pracuję?", "Dzisiaj: …").answer == "W sobotę."
    assert sent[1]["messages"][-2:] == [
        {"role": "assistant", "content": "Masz zmianę w sobotę."},
        {"role": "user", "content": f"Zwróć odpowiedź wywołaniem narzędzia {llm.ANSWER_TOOL}."},
    ]


@pytest.mark.parametrize(
    "reply, error",
    [
        ((402, {"error": {"code": 402, "message": "Insufficient credits"}}), "status 402"),
        ((429, {"error": {"code": 429, "message": "Rate limited"}}), "rate limit"),
        ({"id": "gen-1", "object": "chat.completion", "created": 0, "model": "m", "error": {"code": 502}}, "provider"),
        (chat(text="{", finish="length"), "stopped: length"),
    ],
)
def test_a_failed_call_is_an_assistant_error(fake_openrouter, reply, error):
    fake_openrouter(reply)
    with pytest.raises(llm.AssistantError, match=error):
        llm.read_request("Kiedy pracuję?", "Dzisiaj: …")


def test_each_answer_logs_its_time_tools_providers_and_cost(fake_openrouter, settings, caplog):
    settings.OPENROUTER_EFFORT = "low"
    fake_openrouter(chat(calls=[READ], provider="Fake"), chat(calls=[answer(question())], provider="Other"))
    with caplog.at_level("INFO", logger="apps.assistant.llm"):
        llm.read_request("Kiedy pracuję?", "Dzisiaj: …", StubBox())
    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("assistant EmployeeReply")]
    assert "2 calls, tools my_schedule, 20 output tokens, effort low" in line
    assert "deepseek/deepseek-v4.1-flash via Fake,Other, $0.00020" in line


@pytest.mark.parametrize("value", ["", "fast"])
def test_an_empty_or_unknown_effort_leaves_the_model_default(settings, value, caplog):
    settings.OPENROUTER_EFFORT = value
    with caplog.at_level("WARNING", logger="apps.assistant.llm"):
        options = llm.openrouter_options()
    assert "reasoning" not in options and options["provider"]["data_collection"] == "deny"
    assert bool(caplog.records) == bool(value)


@pytest.mark.parametrize("output", [llm.EmployeeReply, llm.CommandPlan])
def test_the_answer_schema_is_closed_and_follows_the_model(output):
    """Built from the Pydantic model, so a new answer field reaches the model without a change in llm.py."""
    schema = llm.answer_schema(output)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text and '"title"' not in text and '"default"' not in text

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for value in node.values():
                yield from objects(value)
        elif isinstance(node, list):
            for value in node:
                yield from objects(value)

    for node in objects(schema):
        assert node["additionalProperties"] is False and node["required"] == list(node["properties"])
    assert list(schema["properties"]) == list(output.model_fields)

    class Wider(output):
        extra_changes: list[llm.RuleChange]

    wider = llm.answer_schema(Wider)
    assert wider["properties"]["extra_changes"]["items"]["properties"]["code"]["type"] == "string"
