"""The whole agent loop offline: the real SDK tool runner talks to a scripted fake API."""

import json

import pytest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent import agent
from pm_agent.agent import PlanningError, run_planning
from pm_agent.models import Plan


def reply(content, stop_reason="tool_use"):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 300},
    }


def submit(plan, call_id):
    return {"type": "tool_use", "id": call_id, "name": "submit_plan", "input": plan}


def read_log(log_dir, prefix="run"):
    (path,) = log_dir.glob(f"{prefix}-*.json")
    return json.loads(path.read_text(encoding="utf-8"))


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
    (rejection,) = requests[1]["messages"][-1]["content"]
    assert rejection["is_error"] is True
    assert "Plan abgelehnt" in json.dumps(rejection, ensure_ascii=False)

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
    # Claude keeps checking and never submits.
    replies += [reply([check(plan_input(), f"call_{n}")]) for n in range(agent.MAX_ROUNDS)]

    with pytest.raises(PlanningError, match=f"nach {agent.MAX_ROUNDS} Runden"):
        run_planning(PROJECT, TEAM, log_dir=tmp_path)

    assert len(requests) == agent.MAX_ROUNDS
    assert len(read_log(tmp_path)["rounds"]) == agent.MAX_ROUNDS


def test_missing_credentials_are_a_planning_error_in_german(monkeypatch, tmp_path):
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_PROFILE",
        "ANTHROPIC_IDENTITY_TOKEN",
        "ANTHROPIC_IDENTITY_TOKEN_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    for home in ("HOME", "USERPROFILE", "APPDATA", "XDG_CONFIG_HOME"):  # no saved login profile
        monkeypatch.setenv(home, str(tmp_path / "home"))

    with pytest.raises(PlanningError, match="ANTHROPIC_API_KEY"):
        run_planning(PROJECT, TEAM, log_dir=tmp_path)

    assert read_log(tmp_path)["outcome"] == "error"


def test_a_run_without_plan_is_logged_with_the_error(api, tmp_path):
    replies, _ = api
    replies.append(reply([{"type": "text", "text": "Ich brauche mehr Infos."}], "end_turn"))

    with pytest.raises(PlanningError, match="ohne einen Plan einzureichen"):
        run_planning(PROJECT, TEAM, log_dir=tmp_path)

    log = read_log(tmp_path)
    assert log["outcome"] == "error"
    assert "ohne einen Plan einzureichen" in log["error"]
    assert log["plan"] is None
    assert log["rounds"][0]["stop_reason"] == "end_turn"
