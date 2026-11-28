"""The whole agent loop offline: the real SDK client talks to a scripted fake API."""

import json
import os
from datetime import date, datetime

import pytest
from conftest import response as reply
from test_tools import PROJECT, TEAM, plan_input

from pm_agent import agent
from pm_agent.agent import PlanningError, run_planning, run_replanning
from pm_agent.models import Plan
from pm_agent.planning import check_plan
from pm_agent.workbench import load_run


def submit(plan, call_id):
    return {"type": "tool_use", "id": call_id, "name": "submit_plan", "input": plan}


def read_log(log_dir, prefix="run"):
    (path,) = log_dir.glob(f"{prefix}-*.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_two_runs_that_start_in_the_same_second_keep_both_logs(tmp_path):
    # Two browser sessions can start a run at the same moment; the log name has seconds only.
    started = datetime(2026, 11, 16, 9, 0, 0)
    first = agent._write_log(tmp_path, "run", started, {"n": 1})
    second = agent._write_log(tmp_path, "run", started, {"n": 2})
    assert first != second
    logs = [json.loads(p.read_text(encoding="utf-8")) for p in tmp_path.glob("run-*.json")]
    assert sorted(log["n"] for log in logs) == [1, 2]


def test_a_rejected_plan_goes_back_to_claude_and_every_round_is_logged(api, tmp_path):
    replies, requests = api
    replies += [
        reply([submit(plan_input(member="Zoe"), "call_1")]),  # Zoe is not in the team
        reply([{"type": "text", "text": "Korrigiert."}, submit(plan_input(), "call_2")]),
    ]

    seen = []
    plan = run_planning(PROJECT, TEAM, log_dir=tmp_path, on_round=seen.append)

    assert plan == Plan.model_validate(plan_input())
    # The UI shows each round while the run goes on, with the tool results already filled in.
    assert [r["tool_results"][0]["is_error"] for r in seen] == [True, False]
    rejection = requests[1]["input"][-1]
    assert (rejection["type"], rejection["call_id"]) == ("function_call_output", "call_1")
    assert "Plan abgelehnt" in rejection["output"]

    log = read_log(tmp_path)
    assert log["outcome"] == "plan"
    assert log["plan"] == plan.model_dump(mode="json")
    # Project and team are kept so that a run can be reopened in the UI.
    assert log["project"] == PROJECT.model_dump(mode="json")
    assert log["team"] == [m.model_dump(mode="json") for m in TEAM]
    first, second = log["rounds"]
    assert first["tool_calls"][0]["name"] == "submit_plan"
    assert first["tool_results"][0]["is_error"] is True
    assert "Zoe" in first["tool_results"][0]["content"]
    assert second["text"] == "Korrigiert."
    assert second["tool_results"] == [
        {"tool": "submit_plan", "is_error": False, "content": "Plan angenommen."}
    ]
    assert first["usage"]["input_tokens"] == 1200


def check(plan, call_id):
    return {"type": "tool_use", "id": call_id, "name": "check_plan", "input": plan}


def test_the_run_stops_after_the_last_round_without_an_accepted_plan(api, tmp_path):
    replies, requests = api
    # The agent keeps checking and never submits.
    replies += [reply([check(plan_input(), f"call_{n}")]) for n in range(agent.MAX_ROUNDS)]

    with pytest.raises(PlanningError, match=f"nach {agent.MAX_ROUNDS} Runden"):
        run_planning(PROJECT, TEAM, log_dir=tmp_path)

    assert len(requests) == agent.MAX_ROUNDS
    assert len(read_log(tmp_path)["rounds"]) == agent.MAX_ROUNDS


def test_the_last_rejection_is_named_when_the_rounds_run_out(api, tmp_path):
    replies, _ = api
    # Ten rejected plans: the project lead reads why below the box, not only in round ten.
    replies += [
        reply([submit(plan_input(member="Zoe"), f"call_{n}")]) for n in range(agent.MAX_ROUNDS)
    ]

    with pytest.raises(PlanningError) as err:
        run_planning(PROJECT, TEAM, log_dir=tmp_path)

    message = str(err.value)
    assert f"nach {agent.MAX_ROUNDS} Runden" in message
    assert "Zuletzt abgelehnt:" in message
    assert "Zoe" in message


def test_missing_credentials_are_a_planning_error_in_german(monkeypatch, tmp_path):
    for name in [n for n in os.environ if n.startswith("OPENAI_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("PM_AGENT_MODEL", "gpt-test")

    with pytest.raises(PlanningError, match="OPENAI_API_KEY"):
        run_planning(PROJECT, TEAM, log_dir=tmp_path)

    assert read_log(tmp_path)["outcome"] == "error"


def test_a_run_without_plan_is_logged_with_the_error(api, tmp_path):
    replies, _ = api
    replies.append(reply([{"type": "text", "text": "Ich brauche mehr Infos."}]))

    with pytest.raises(PlanningError, match="ohne einen Plan einzureichen"):
        run_planning(PROJECT, TEAM, log_dir=tmp_path)

    log = read_log(tmp_path)
    assert log["outcome"] == "error"
    assert "ohne einen Plan einzureichen" in log["error"]
    assert log["plan"] is None
    assert log["rounds"][0]["stop_reason"] == "completed"


def test_replanning_sends_the_current_plan_and_the_wish_and_logs_both(api, tmp_path):
    replies, requests = api
    longer = plan_input(hours=16)
    replies += [reply([submit(longer, "call_1")])]
    current = Plan.model_validate(plan_input())

    plan, absences = run_replanning(
        PROJECT, TEAM, current, "Das Datenmodell braucht doppelt so lange.", log_dir=tmp_path
    )

    assert (plan, absences) == (Plan.model_validate(longer), [])
    (request,) = requests
    system, asked = request["instructions"], request["input"][0]["content"]
    assert "Das Datenmodell braucht doppelt so lange." in asked
    assert '"title": "Datenmodell"' in asked  # the current plan goes along
    assert "Änderung eines bestehenden Plans" in system
    assert "Inhalt des Plans" in system  # the rules for a plan still apply
    log = read_log(tmp_path)
    assert log["wish"] == "Das Datenmodell braucht doppelt so lange."
    assert log["plan"] == plan.model_dump(mode="json")
    assert log["project"] == PROJECT.model_dump(mode="json")


def test_replanning_needs_a_wish(api, tmp_path):
    replies, requests = api
    with pytest.raises(PlanningError, match="Beschreibe, was sich ändern soll"):
        run_replanning(PROJECT, TEAM, Plan.model_validate(plan_input()), "  ", log_dir=tmp_path)
    assert requests == []  # nothing was sent


def test_planning_sends_the_requirements_and_logs_them(api, tmp_path):
    from test_tools import NEEDS

    replies, requests = api
    replies += [reply([submit(plan_input(), "call_1")])]
    run_planning(PROJECT, TEAM, log_dir=tmp_path, requirements=NEEDS, covered=frozenset({"R7"}))
    sent = requests[0]["input"][0]["content"]
    sent = sent if isinstance(sent, str) else json.dumps(sent, ensure_ascii=False)
    assert "Freigegebene Anforderungen" in sent and "Raum buchen" in sent
    assert "Schon durch fertige Arbeit erfüllt: R7" in sent
    assert read_log(tmp_path)["requirements"] == [n.model_dump(mode="json") for n in NEEDS]


def test_planning_without_requirements_sends_and_logs_none(api, tmp_path):
    replies, requests = api
    replies += [reply([submit(plan_input(), "call_1")])]
    run_planning(PROJECT, TEAM, log_dir=tmp_path)
    assert "Anforderungen" not in json.dumps(requests[0]["input"], ensure_ascii=False)
    assert "requirements" not in read_log(tmp_path)


def test_an_approved_design_goes_to_the_planner_without_its_flows(api, tmp_path):
    from test_lifecycle import design

    replies, requests = api
    replies += [reply([submit(plan_input(), "call_1")])] * 2
    run_planning(PROJECT, TEAM, log_dir=tmp_path, design=design())
    plan = Plan.model_validate(plan_input())
    run_replanning(PROJECT, TEAM, plan, "Schneller.", log_dir=tmp_path, design=design())
    for request in requests:
        sent = json.dumps(request["input"][0], ensure_ascii=False)
        assert "Freigegebener Entwurf" in sent and "Buchung anlegen" in sent
        # The flows name requirements the planner may not see.
        assert "Raum buchen" not in sent and "A1" not in sent


def test_without_a_design_the_planner_hears_nothing_of_it(api, tmp_path):
    replies, requests = api
    replies += [reply([submit(plan_input(), "call_1")])]
    run_planning(PROJECT, TEAM, log_dir=tmp_path)
    assert "Entwurf" not in json.dumps(requests[0]["input"], ensure_ascii=False)


def test_replanning_can_set_the_absence_a_wish_names_and_logs_it(api, tmp_path):
    from pm_agent.models import MemberAbsence

    replies, requests = api
    away = {"member": "Anna", "first": "2026-11-09", "last": "2026-11-10"}
    replies += [
        reply([{"type": "tool_use", "id": "call_1", "name": "set_absence", "input": away}]),
        reply([submit(plan_input(), "call_2")]),
    ]
    result = run_replanning(
        PROJECT,
        TEAM,
        Plan.model_validate(plan_input()),
        "Anna fehlt am 9. und 10.11.",
        log_dir=tmp_path,
    )
    assert result.absences == [MemberAbsence.model_validate(away)]
    assert "set_absence" in [tool["name"] for tool in requests[0]["tools"]]
    assert read_log(tmp_path)["absences"] == [away]

    (path,) = tmp_path.glob("run-*.json")
    project, team, plan, _record = load_run(path)
    assert [a.model_dump(mode="json") for a in team[0].absences] == [
        {"first": away["first"], "last": away["last"]}
    ]
    assert check_plan(plan, team, project).end_date == date(2026, 11, 13)


def test_a_new_plan_gets_no_tool_for_absences(api, tmp_path):
    replies, requests = api
    replies += [reply([submit(plan_input(), "call_1")])]
    run_planning(PROJECT, TEAM, log_dir=tmp_path)
    assert "set_absence" not in [tool["name"] for tool in requests[0]["tools"]]
    assert "absences" not in read_log(tmp_path)


def test_input_that_is_no_json_object_and_an_unknown_tool_go_back_as_errors(api, tmp_path):
    # The API sends tool input as text. Broken text must not end the run: the model corrects it.
    replies, requests = api
    broken = reply([submit(plan_input(), "call_1")])
    broken["output"][0]["arguments"] = '{"tasks": ['
    unknown = reply([{"type": "tool_use", "id": "call_2", "name": "delete_plan", "input": {}}])
    replies += [broken, unknown, reply([submit(plan_input(), "call_3")])]

    run_planning(PROJECT, TEAM, log_dir=tmp_path)

    first, second, third = read_log(tmp_path)["rounds"]
    assert first["tool_results"][0] == {
        "tool": "submit_plan",
        "is_error": True,
        "content": "Ungültige Eingabe: kein gültiges JSON-Objekt.",
    }
    assert second["tool_results"][0]["content"] == "Dieses Werkzeug gibt es nicht."
    assert third["tool_results"][0]["is_error"] is False
    assert requests[1]["input"][-1]["output"] == first["tool_results"][0]["content"]


def test_without_a_model_name_nothing_is_sent(api, monkeypatch, tmp_path):
    _, requests = api
    monkeypatch.delenv("PM_AGENT_MODEL")
    monkeypatch.delenv("PM_MODEL", raising=False)
    with pytest.raises(PlanningError, match="PM_AGENT_MODEL ist nicht gesetzt"):
        run_planning(PROJECT, TEAM, log_dir=tmp_path)
    assert requests == []
    monkeypatch.setenv("PM_MODEL", "gpt-lab")  # the KI-Lab's setting serves both
    requests_before = len(requests)
    with pytest.raises(IndexError):  # the fake has no reply scripted: the request went out
        run_planning(PROJECT, TEAM, log_dir=tmp_path / "second")
    assert requests[requests_before]["model"] == "gpt-lab"


def test_the_reasoning_effort_is_medium_unless_the_setting_says_otherwise(
    api, monkeypatch, tmp_path
):
    # Function tools need reasoning with the Responses API (not "none", which the chat
    # completions endpoint of the model required); "medium" is the default.
    replies, requests = api
    replies += [reply([submit(plan_input(), "call_1")])] * 2
    run_planning(PROJECT, TEAM, log_dir=tmp_path)
    monkeypatch.setenv("PM_AGENT_REASONING_EFFORT", "high")
    run_planning(PROJECT, TEAM, log_dir=tmp_path)
    assert [r["reasoning"]["effort"] for r in requests] == ["medium", "high"]
    assert all(r["store"] is False for r in requests)
    assert all("reasoning.encrypted_content" in r["include"] for r in requests)


def test_a_run_without_log_dir_writes_where_agent_log_dir_points_now(api, monkeypatch, tmp_path):
    # LOG_DIR was bound as the default at import: pointing agent.LOG_DIR elsewhere afterwards
    # still wrote into the real logs/.
    replies, _ = api
    replies.append(reply([submit(plan_input(), "call_1")]))
    monkeypatch.setattr(agent, "LOG_DIR", tmp_path / "logs")
    run_planning(PROJECT, TEAM)
    assert len(list((tmp_path / "logs").glob("run-*.json"))) == 1


def test_openai_client_receives_explicit_timeout_and_retry_limit(monkeypatch, tmp_path):
    import httpx2 as httpx
    import openai

    captured = {}

    def handle(_request):
        return httpx.Response(200, json=reply([submit(plan_input(), "call_1")]))

    def fake_openai(*args, **kwargs):
        captured.update(kwargs)
        return openai.OpenAI(
            api_key="test",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        )

    monkeypatch.setattr(agent, "OpenAI", fake_openai)
    monkeypatch.setenv("PM_AGENT_MODEL", "gpt-test")
    monkeypatch.delenv("PM_AGENT_TIMEOUT", raising=False)

    plan = run_planning(PROJECT, TEAM, log_dir=tmp_path)

    assert plan == Plan.model_validate(plan_input())
    assert isinstance(captured.get("timeout"), openai.Timeout)
    assert 0 < captured["timeout"].read <= 180.0
    assert 0 < captured["timeout"].connect <= 15.0
    assert captured.get("max_retries") == agent.MAX_RETRIES


@pytest.mark.parametrize(
    "outcome, error_type, expected_fragment",
    [
        (401, "AuthenticationError", "HTTP 401"),
        (403, "PermissionDeniedError", "HTTP 403"),
        (404, "NotFoundError", "HTTP 404"),
        (429, "RateLimitError", "HTTP 429"),
        (500, "InternalServerError", "HTTP 500"),
        ("timeout", "APITimeoutError", "Zeitüberschreitung"),
        ("connect", "APIConnectionError", "Verbindung"),
    ],
)
def test_real_sdk_errors_propagate_get_logged_and_format_in_german(
    monkeypatch, tmp_path, outcome, error_type, expected_fragment
):
    import httpx2 as httpx
    import openai

    def handle(request):
        if outcome == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if outcome == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(
            outcome, json={"error": {"message": f"raw {outcome}", "type": "api_error"}}
        )

    client = openai.OpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(agent, "OpenAI", lambda *args, **kwargs: client)
    monkeypatch.setenv("PM_AGENT_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ki.beispiel.test/v1")

    expected_cls = getattr(openai, error_type)
    with pytest.raises(expected_cls) as exc_info:
        run_planning(PROJECT, TEAM, log_dir=tmp_path)

    text = agent.describe_api_error(exc_info.value)
    assert expected_fragment in text
    assert "ki.beispiel.test" in text
    assert "OpenAI API" not in text

    log = read_log(tmp_path)
    assert log["outcome"] == "error"
    assert error_type in log["error"]


def test_missing_key_and_model_errors_name_configured_service_not_openai_api(monkeypatch, tmp_path):
    for name in [n for n in os.environ if n.startswith("OPENAI_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ki.beispiel.test/v1")
    monkeypatch.setenv("PM_AGENT_MODEL", "gpt-test")

    with pytest.raises(PlanningError) as key_err:
        run_planning(PROJECT, TEAM, log_dir=tmp_path / "key")
    assert "ki.beispiel.test" in str(key_err.value)
    assert "OPENAI_API_KEY" in str(key_err.value)
    assert "OpenAI API" not in str(key_err.value)

    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    monkeypatch.delenv("PM_AGENT_MODEL")
    monkeypatch.delenv("PM_MODEL", raising=False)
    with pytest.raises(PlanningError) as model_err:
        run_planning(PROJECT, TEAM, log_dir=tmp_path / "model")
    assert "ki.beispiel.test" in str(model_err.value)
    assert "PM_AGENT_MODEL" in str(model_err.value)
    assert "OpenAI-Modells" not in str(model_err.value)


def test_log_write_oserror_keeps_accepted_plan_and_reports_warning(
    api, monkeypatch, tmp_path, caplog
):
    replies, _ = api
    replies.append(reply([submit(plan_input(), "call_1")]))

    def deny(*args, **kwargs):
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr(agent, "_write_log", deny)
    seen_errors = []
    with caplog.at_level("WARNING", logger="pm_agent.agent"):
        with agent.collect_log_errors() as collected:
            plan = run_planning(PROJECT, TEAM, log_dir=tmp_path, on_log_error=seen_errors.append)

    assert plan == Plan.model_validate(plan_input())
    assert len(seen_errors) == 1 and isinstance(seen_errors[0], PermissionError)
    assert len(collected) == 1 and "Laufprotokoll" in collected[0]
    assert "Zugriff verweigert" in collected[0]
    assert any("Laufprotokoll" in rec.message for rec in caplog.records)


def test_uncreatable_log_dir_keeps_accepted_result(api, tmp_path, caplog):
    replies, _ = api
    replies.append(reply([submit(plan_input(), "call_1")]))
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file", encoding="utf-8")

    with caplog.at_level("WARNING", logger="pm_agent.agent"):
        with agent.collect_log_errors() as collected:
            plan = run_planning(PROJECT, TEAM, log_dir=blocker)

    assert plan == Plan.model_validate(plan_input())
    assert len(collected) == 1 and "Laufprotokoll" in collected[0]
    assert any("Laufprotokoll" in rec.message for rec in caplog.records)


def test_log_write_oserror_does_not_mask_original_agent_failure(api, monkeypatch, tmp_path, caplog):
    replies, _ = api
    replies.append(reply([{"type": "text", "text": "Ich höre auf."}]))

    def deny(*args, **kwargs):
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr(agent, "_write_log", deny)
    with caplog.at_level("WARNING", logger="pm_agent.agent"):
        with agent.collect_log_errors() as collected:
            with pytest.raises(PlanningError, match="ohne einen Plan einzureichen"):
                run_planning(PROJECT, TEAM, log_dir=tmp_path)

    assert len(collected) == 1 and "Laufprotokoll" in collected[0]
    assert any("Laufprotokoll" in rec.message for rec in caplog.records)
