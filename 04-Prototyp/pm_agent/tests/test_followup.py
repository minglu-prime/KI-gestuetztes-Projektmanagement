"""The agents for Durchführung and Kontrolle: their checks, and the whole loop offline."""

import json
from datetime import date

import pytest
from test_agent_loop import read_log, reply
from test_tools import PROJECT, TEAM, plan_input

from pm_agent.agent import AgentError
from pm_agent.followup import (
    check_report,
    check_summary,
    facts,
    run_control_report,
    run_status_summary,
)
from pm_agent.models import ControlReport, Plan, StatusSummary
from pm_agent.tracking import adopt, apply_rows, evaluate

TODAY = date(2026, 11, 12)  # A (planned 09.11.) is finished, B (planned until 11.11.) is late

SUMMARY = {
    "summary": "A ist fertig, B ist im Verzug.",
    "next_steps": [{"task_id": "B", "action": "Anna schließt die API bis Freitag ab."}],
}
REPORT = {
    "assessment": "gefährdet",
    "findings": [{"task_ids": ["B"], "observation": "B ist seit dem 11.11. überfällig."}],
    "measures": [
        {"task_ids": ["B"], "action": "Anna priorisiert B.", "effect": "B wird diese Woche fertig."}
    ],
}


@pytest.fixture
def tracking(tmp_path):
    adopted = adopt(PROJECT, TEAM, Plan.model_validate(plan_input()), path=tmp_path / "p.json")
    return apply_rows(
        adopted,
        [
            {"ID": "A", "Status": "fertig", "Ist (h)": 10},
            {"ID": "B", "Status": "in Arbeit", "Ist (h)": 4},
        ],
    )


def tool_call(name, data, call_id):
    return {"type": "tool_use", "id": call_id, "name": name, "input": data}


def test_a_status_summary_must_cover_overdue_tasks_and_only_open_known_ones(tracking):
    evaluation = evaluate(tracking, TODAY)
    assert check_summary(StatusSummary.model_validate(SUMMARY), evaluation) == []

    steps = [{"task_id": "A", "action": "x"}, {"task_id": "Z", "action": "y"}]
    broken = StatusSummary(summary="Alles gut.", next_steps=steps)
    assert check_summary(broken, evaluation) == [
        "Aufgabe 'A' ist fertig und braucht keinen nächsten Schritt",
        "Nächster Schritt nennt die unbekannte Aufgabe 'Z'",
        "Aufgabe 'B' ist im Verzug, aber kein nächster Schritt nennt sie",
    ]


def test_a_control_report_must_answer_every_overdue_task(tracking):
    evaluation = evaluate(tracking, TODAY)
    assert check_report(ControlReport.model_validate(REPORT), evaluation) == []

    calm = ControlReport(
        assessment="im Plan",
        findings=[{"task_ids": ["Z"], "observation": "Läuft."}],
    )
    assert check_report(calm, evaluation) == [
        "Feststellung nennt die unbekannte Aufgabe 'Z'",
        "Aufgabe 'B' ist im Verzug, aber keine Gegenmaßnahme nennt sie",
        "Es gibt Aufgaben im Verzug, die Bewertung kann nicht 'im Plan' sein",
    ]


def test_without_overdue_tasks_im_plan_is_a_valid_assessment(tracking):
    early = evaluate(tracking, date(2026, 11, 10))
    calm = ControlReport(assessment="im Plan", findings=[{"observation": "Im Zeitplan."}])
    assert check_report(calm, early) == []


def test_the_agents_get_the_computed_numbers_not_raw_material_to_compute(tracking):
    data = json.loads(facts(tracking, evaluate(tracking, TODAY)))

    assert data["stand"] == "2026-11-12"
    assert data["kennzahlen"] == {
        "planstunden": 24,
        "ist_stunden": 14,
        "fortschritt": 0.333,
        "abweichung_fertiger_aufgaben": 2,
        "im_verzug": ["B"],
    }
    b = data["aufgaben"][1]
    assert (b["id"], b["overdue"], b["planned_end"], b["depends_on"]) == (
        "B",
        True,
        "2026-11-11",
        ["A"],
    )


def test_a_rejected_status_summary_goes_back_to_claude_until_it_is_accepted(
    api, tracking, tmp_path
):
    replies, requests = api
    forgot_b = {"summary": "A ist fertig.", "next_steps": []}
    replies += [
        reply([tool_call("submit_status", forgot_b, "call_1")]),
        reply([tool_call("submit_status", SUMMARY, "call_2")]),
    ]

    seen = []
    summary = run_status_summary(tracking, TODAY, log_dir=tmp_path, on_round=seen.append)

    assert summary == StatusSummary.model_validate(SUMMARY)
    assert [r["tool_results"][0]["is_error"] for r in seen] == [True, False]
    # Claude gets the plan, the progress and the numbers, and the rule it broke.
    assert '"im_verzug": [\n      "B"' in requests[0]["messages"][0]["content"]
    assert "studentischen Projektgruppe während der Durchführung" in json.dumps(
        requests[0]["system"], ensure_ascii=False
    )
    (rejection,) = requests[1]["messages"][-1]["content"]
    assert "Statusbericht abgelehnt" in json.dumps(rejection, ensure_ascii=False)
    assert "Aufgabe 'B' ist im Verzug" in json.dumps(rejection, ensure_ascii=False)

    log = read_log(tmp_path, "durchfuehrung")
    assert log["outcome"] == "statusbericht"
    assert log["result"] == SUMMARY
    assert log["input"]["kennzahlen"]["im_verzug"] == ["B"]
    assert len(log["rounds"]) == 2


def test_the_control_agent_returns_the_report_its_check_accepts(api, tracking, tmp_path):
    replies, requests = api
    replies.append(reply([tool_call("submit_control", REPORT, "call_1")]))

    report = run_control_report(tracking, TODAY, log_dir=tmp_path)

    assert report == ControlReport.model_validate(REPORT)
    assert [tool["name"] for tool in requests[0]["tools"]] == ["submit_control"]
    log = read_log(tmp_path, "kontrolle")
    assert (log["outcome"], log["result"]["assessment"]) == ("kontrollbericht", "gefährdet")


def test_an_agent_that_stops_without_a_result_is_an_error_naming_the_result(
    api, tracking, tmp_path
):
    replies, _ = api
    replies.append(reply([{"type": "text", "text": "Mir fehlen Angaben."}], "end_turn"))

    with pytest.raises(AgentError, match="ohne einen Kontrollbericht einzureichen"):
        run_control_report(tracking, TODAY, log_dir=tmp_path)

    log = read_log(tmp_path, "kontrolle")
    assert (log["outcome"], log["result"]) == ("error", None)


def test_input_that_does_not_parse_is_rejected_with_the_field(api, tracking, tmp_path):
    replies, requests = api
    replies += [
        reply([tool_call("submit_control", {"assessment": "super"}, "call_1")]),
        reply([tool_call("submit_control", REPORT, "call_2")]),
    ]

    run_control_report(tracking, TODAY, log_dir=tmp_path)

    rejection = json.dumps(requests[1]["messages"][-1]["content"], ensure_ascii=False)
    assert "Kontrollbericht abgelehnt" in rejection
    assert "Ungültige Eingabe bei assessment" in rejection
