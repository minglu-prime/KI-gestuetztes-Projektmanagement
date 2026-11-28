"""UI integration tests for API error formatting, consent accuracy, and log-write warnings."""

import httpx2 as httpx
import openai
import pytest
from conftest import response as reply
from test_app import (  # noqa: F401
    PLAN,
    PLANUNG,
    app,
    button,
    fill_project,
    local,
    site,
    tracked,
    with_plan,
)
from test_tools import plan_input

from pm_agent import agent, followup
from pm_agent.models import ControlReport


def _api_status(cls: type[openai.APIStatusError], code: int) -> openai.APIStatusError:
    req = httpx.Request("POST", "https://ki.beispiel.test/v1/responses")
    return cls(f"Error code: {code}", response=httpx.Response(code, request=req), body=None)


def _dummy_round() -> dict:
    return {"tool_results": [{"tool": "check_plan", "is_error": True, "content": "Fehler."}]}


def _deny_log(*_args, **_kwargs):
    raise PermissionError("gesperrt")


def test_consent_labels_for_team_sending_views_include_absences(tracked, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ki.beispiel.test/v1")
    for path, key in [
        (PLANUNG, "consent"),
        ("views/durchfuehrung.py", "consent_durchfuehrung"),
        ("views/kontrolle.py", "consent_kontrolle"),
    ]:
        label = tracked.switch_page(path).run().checkbox(key=key).label
        assert "Abwesenheiten" in label and "ki.beispiel.test" in label and "OpenAI" not in label


@pytest.mark.parametrize(
    "make_error, rounds_before, expected_error, expected_label",
    [
        (
            lambda: _api_status(openai.AuthenticationError, 401),
            0,
            "HTTP 401",
            "Kein Ergebnis nach 0 Runden",
        ),
        (
            lambda: _api_status(openai.RateLimitError, 429),
            1,
            "HTTP 429",
            "Kein Ergebnis nach 1 Runde",
        ),
        (
            lambda: openai.APITimeoutError(
                request=httpx.Request("POST", "https://ki.beispiel.test/v1/responses")
            ),
            2,
            "Zeitüberschreitung",
            "Kein Ergebnis nach 2 Runden",
        ),
    ],
)
def test_run_with_progress_formats_api_errors_and_round_plural(
    tracked,  # noqa: F811
    monkeypatch,
    make_error,
    rounds_before,
    expected_error,
    expected_label,
):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ki.beispiel.test/v1")

    def failing(adopted, today, on_round=None):
        for _ in range(rounds_before):
            on_round(_dummy_round())
        raise make_error()

    monkeypatch.setattr(followup, "run_control_report", failing)
    at = tracked.switch_page("views/kontrolle.py").run()
    at.checkbox(key="consent_kontrolle").check().run()
    button(at, "Stand mit dem Agenten bewerten").click().run()

    assert not at.exception and len(at.error) == 1
    shown = at.error[0].value.replace("\\_", "_")
    assert expected_error in shown and "ki.beispiel.test" in shown and "OpenAI API" not in shown
    assert [s.label for s in at.status] == [expected_label]


def test_planung_step3_formats_api_error_and_singular_round(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ki.beispiel.test/v1")

    def failing(project, team, on_round=None):
        on_round(_dummy_round())
        raise _api_status(openai.RateLimitError, 429)

    monkeypatch.setattr(agent, "run_planning", failing)
    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click().run()

    assert not at.exception and len(at.error) == 1
    shown = at.error[0].value.replace("\\_", "_")
    assert "HTTP 429" in shown and "ki.beispiel.test" in shown and "OpenAI API" not in shown
    assert [s.label for s in at.status] == ["Kein Plan nach 1 Runde"]


def test_planung_step3_success_uses_singular_round(app, monkeypatch):  # noqa: F811
    def one_round(project, team, on_round=None):
        on_round({"tool_results": [{"tool": "submit_plan", "is_error": False, "content": "OK"}]})
        return PLAN

    monkeypatch.setattr(agent, "run_planning", one_round)
    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click().run()
    assert not at.exception and not at.error
    assert any("Plan angenommen nach 1 Runde." in s.value for s in at.success)


def test_planung_step5_formats_api_error_and_singular_round(with_plan, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ki.beispiel.test/v1")

    def failing(project, team, plan, wish, on_round=None):
        on_round(_dummy_round())
        raise openai.APITimeoutError(
            request=httpx.Request("POST", "https://ki.beispiel.test/v1/responses")
        )

    monkeypatch.setattr(agent, "run_replanning", failing)
    at = with_plan.chat_input(key="wish").set_value("Ben hilft mit.").run()

    assert not at.exception and len(at.error) == 1
    shown = at.error[0].value.replace("\\_", "_")
    assert "Zeitüberschreitung" in shown and "ki.beispiel.test" in shown
    assert "OpenAI API" not in shown
    assert [s.label for s in at.status] == ["Kein Vorschlag nach 1 Runde"]


def test_planung_keeps_plan_and_proposal_and_warns_on_log_write_error(
    app,  # noqa: F811
    api,
    monkeypatch,
):
    replies, _ = api
    replies.extend(
        [
            reply([{"type": "tool_use", "id": "c1", "name": "submit_plan", "input": plan_input()}]),
            reply(
                [
                    {
                        "type": "tool_use",
                        "id": "c2",
                        "name": "submit_plan",
                        "input": plan_input(hours=12),
                    }
                ]
            ),
        ]
    )
    monkeypatch.setattr(agent, "_write_log", _deny_log)

    at = fill_project(app)
    button(at, "Plan mit dem Agenten erstellen").click().run()
    assert not at.exception and not at.error and at.session_state["plan"] == PLAN
    assert any("Laufprotokoll" in w.value and "gesperrt" in w.value for w in at.warning)

    at = at.chat_input(key="wish").set_value("Länger planen.").run()
    assert not at.exception and not at.error and at.session_state["proposal"] is not None
    assert any("Laufprotokoll" in w.value and "gesperrt" in w.value for w in at.warning)


def test_run_with_progress_keeps_result_and_warns_on_log_write_error(
    tracked,  # noqa: F811
    api,
    monkeypatch,
):
    replies, _ = api
    report = ControlReport(
        assessment="gefährdet",
        findings=[{"task_ids": ["A", "B"], "observation": "A und B sind im Verzug."}],
        measures=[{"task_ids": ["A", "B"], "action": "Priorisieren.", "effect": "Verzug sinkt."}],
    )
    replies.append(
        reply(
            [
                {
                    "type": "tool_use",
                    "id": "c1",
                    "name": "submit_control",
                    "input": report.model_dump(mode="json"),
                }
            ]
        )
    )
    monkeypatch.setattr(agent, "_write_log", _deny_log)

    at = tracked.switch_page("views/kontrolle.py").run()
    at.checkbox(key="consent_kontrolle").check().run()
    button(at, "Stand mit dem Agenten bewerten").click().run()

    assert not at.exception and not at.error and "Bewertung" in {m.label for m in at.metric}
    assert any("Laufprotokoll" in w.value and "gesperrt" in w.value for w in at.warning)
