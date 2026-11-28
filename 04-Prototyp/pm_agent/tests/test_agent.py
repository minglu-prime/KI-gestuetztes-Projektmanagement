import httpx2 as httpx
import openai
import pytest

from pm_agent import agent, ui
from pm_agent.agent import AgentError, PlanningError, raise_for_stop_reason


@pytest.mark.parametrize(
    "stop_reason, category, message",
    [
        ("length", None, "Die Antwort vom Agenten wurde abgeschnitten"),
        ("content_filter", None, r"Der Agent hat die Anfrage abgelehnt\."),
        (
            "stop",
            "Das kann ich nicht.",
            r"Der Agent hat die Anfrage abgelehnt: Das kann ich nicht\.",
        ),
    ],
)
def test_a_reply_that_cannot_lead_to_a_plan_is_an_error(stop_reason, category, message):
    # Without the check such a reply would end the run with "no result" and no reason.
    with pytest.raises(PlanningError, match=message):
        raise_for_stop_reason(stop_reason, category)


@pytest.mark.parametrize("stop_reason", ["tool_calls", "stop"])
def test_regular_replies_pass(stop_reason):
    raise_for_stop_reason(stop_reason, None)


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://ki.beispiel.test/v1/responses")


def _status(cls: type[openai.APIStatusError], code: int) -> openai.APIStatusError:
    req = _req()
    return cls(
        f"Error code: {code}",
        response=httpx.Response(code, request=req),
        body={"error": {"message": "raw english"}},
    )


@pytest.mark.parametrize(
    "make_error, expected",
    [
        (
            lambda: _status(openai.AuthenticationError, 401),
            ("HTTP 401", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
        ),
        (
            lambda: _status(openai.PermissionDeniedError, 403),
            ("HTTP 403", "OPENAI_API_KEY", "PM_AGENT_MODEL"),
        ),
        (
            lambda: _status(openai.NotFoundError, 404),
            ("HTTP 404", "PM_AGENT_MODEL", "OPENAI_BASE_URL", "gpt-test"),
        ),
        (lambda: _status(openai.RateLimitError, 429), ("HTTP 429", "Kontingent")),
        (
            lambda: openai.APITimeoutError(request=_req()),
            ("Zeitüberschreitung", "PM_AGENT_TIMEOUT"),
        ),
        (lambda: openai.APIConnectionError(request=_req()), ("Verbindung", "OPENAI_BASE_URL")),
        (lambda: _status(openai.InternalServerError, 500), ("HTTP 500", "vorübergehend")),
        (lambda: _status(openai.InternalServerError, 503), ("HTTP 503", "vorübergehend")),
        (lambda: _status(openai.BadRequestError, 400), ("HTTP 400", "abgewiesen")),
        (lambda: openai.APIError("unexpected", _req(), body=None), ("unerwarteten Fehler",)),
    ],
)
def test_describe_api_error_gives_actionable_german_messages(monkeypatch, make_error, expected):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ki.beispiel.test/v1")
    monkeypatch.setenv("PM_AGENT_MODEL", "gpt-test")
    text = agent.describe_api_error(make_error())
    assert "ki.beispiel.test" in text and "OpenAI API" not in text and "raw english" not in text
    for fragment in expected:
        assert fragment in text, f"Missing {fragment!r} in {text!r}"


def test_describe_api_error_falls_back_to_api_openai_com(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    text = agent.describe_api_error(_status(openai.AuthenticationError, 401))
    assert "api.openai.com" in text and "OpenAI API" not in text
    assert agent.service_host() == "api.openai.com"
    assert ui.ai_service() == "den KI-Dienst api.openai.com"


def test_timeout_uses_explicit_default_and_respects_env_override(monkeypatch):
    monkeypatch.delenv("PM_AGENT_TIMEOUT", raising=False)
    default = agent._timeout()
    assert isinstance(default, openai.Timeout)
    assert 0 < default.read <= 180.0 and 0 < default.connect <= 15.0

    monkeypatch.setenv("PM_AGENT_TIMEOUT", "45")
    custom = agent._timeout()
    assert custom.read == 45.0 and custom.connect == min(agent.CONNECT_TIMEOUT, 45.0)

    monkeypatch.setenv("PM_AGENT_TIMEOUT", "4")
    short = agent._timeout()
    assert short.read == 4.0 and short.connect == 4.0


@pytest.mark.parametrize("bad_value", ["abc", "0", "-5", "nan", "inf"])
def test_invalid_timeout_setting_is_an_agent_error(monkeypatch, bad_value):
    monkeypatch.setenv("PM_AGENT_TIMEOUT", bad_value)
    with pytest.raises(AgentError, match="PM_AGENT_TIMEOUT"):
        agent._timeout()


@pytest.mark.parametrize("count, expected", [(0, "0 Runden"), (1, "1 Runde"), (2, "2 Runden")])
def test_rounds_text_uses_german_singular_and_plural(count, expected):
    assert ui.rounds_text(count) == expected
