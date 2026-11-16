import json
from datetime import date

import pytest
from anthropic.lib.tools import ToolError

from pm_agent.models import Member, Plan, Project
from pm_agent.tools import PlanningTools

PROJECT = Project(
    idea="Raumbuchung für Lerngruppen", start_date=date(2026, 11, 9), deadline=date(2026, 12, 18)
)
TEAM = [Member(name="Anna", skills={"Python": 4}, hours_per_week=40)]  # 8 h per workday


def plan_input(member="Anna", hours=8):
    """A plan the way Claude sends it as tool input: plain JSON, B depends on A."""
    return {
        "tasks": [
            {
                "id": "A",
                "title": "Datenmodell",
                "estimate_hours": hours,
                "required_skills": ["SQL"],
            },
            {"id": "B", "title": "API", "estimate_hours": 16, "depends_on": ["A"]},
        ],
        "assignments": [
            {"task_id": "A", "member": member, "reason": "kennt die Raumdaten"},
            {"task_id": "B", "member": "Anna", "reason": "kennt Python"},
        ],
        "risks": ["Die Hochschule liefert die Raumdaten zu spät"],
    }


def test_check_plan_reports_errors_warnings_critical_path_and_load():
    report = json.loads(PlanningTools(PROJECT, TEAM).check_plan.call(plan_input()))
    assert report == {
        "errors": [],
        "warnings": ["Task 'A' braucht 'SQL', Anna hat diese Fähigkeit nicht angegeben"],
        "end_date": "2026-11-11",
        "critical_path": ["A", "B"],
        "load": [
            {"member": "Anna", "assigned_hours": 24, "capacity_hours": 240, "utilization": 0.1}
        ],
    }


def test_check_plan_reports_invalid_input_as_errors():
    # A typical slip: the LLM names the field "hours". Claude must learn what to fix.
    broken = plan_input()
    broken["tasks"][0]["hours"] = broken["tasks"][0].pop("estimate_hours")
    report = json.loads(PlanningTools(PROJECT, TEAM).check_plan.call(broken))
    assert report["errors"] == [
        "Ungültige Eingabe bei tasks.0.estimate_hours: Feld fehlt",
        "Ungültige Eingabe bei tasks.0.hours: Feld ist nicht vorgesehen",
    ]


@pytest.mark.parametrize(
    "plan, reason",
    [
        (plan_input(member="Zoe"), "Task 'A' ist 'Zoe' zugewiesen, diese Person ist nicht im Team"),
        (plan_input(hours=0), "tasks.0.estimate_hours: muss größer als 0 sein"),
    ],
)
def test_submit_plan_rejects_a_broken_plan_and_says_why(plan, reason):
    tools = PlanningTools(PROJECT, TEAM)
    with pytest.raises(ToolError) as rejected:
        tools.submit_plan.call(plan)
    assert reason in rejected.value.content
    assert tools.plan is None


def test_input_that_is_no_plan_at_all_gets_a_message_with_a_place():
    # Not an object: the error has no field, and the message must not end in "bei :".
    report = json.loads(PlanningTools(PROJECT, TEAM).check_plan.call({"tasks": "A, B"}))
    assert report["errors"] == [
        "Ungültige Eingabe bei tasks: muss eine Liste sein",
        "Ungültige Eingabe bei assignments: Feld fehlt",
    ]
    from pydantic import ValidationError

    from pm_agent.tools import invalid_input

    with pytest.raises(ValidationError) as err:
        Plan.model_validate("kein Plan")
    assert invalid_input(err.value) == ["Ungültige Eingabe: muss ein Objekt sein"]


def test_a_field_named_self_is_an_unknown_field_not_a_crash():
    # The tool functions took "self" as a keyword: Claude got a Python TypeError.
    tools = PlanningTools(PROJECT, TEAM)
    with pytest.raises(ToolError) as rejected:
        tools.submit_plan.call({**plan_input(), "self": 1})
    assert "Ungültige Eingabe bei self: Feld ist nicht vorgesehen" in rejected.value.content


def test_submit_plan_accepts_a_plan_with_warnings_because_the_project_lead_decides():
    tools = PlanningTools(PROJECT, TEAM)
    tools.submit_plan.call(plan_input())  # warning: Anna has no SQL
    assert tools.plan == Plan.model_validate(plan_input())


def test_both_tools_show_claude_the_plan_schema():
    tools = PlanningTools(PROJECT, TEAM)
    definitions = [tools.check_plan.to_dict(), tools.submit_plan.to_dict()]
    assert {d["name"]: d["input_schema"] for d in definitions} == {
        "check_plan": Plan.model_json_schema(),
        "submit_plan": Plan.model_json_schema(),
    }
