"""What changed between two plans, and what the progress view says about one agent round."""

from test_tools import PROJECT, TEAM, plan_input

from pm_agent.models import Member, Plan
from pm_agent.planning import check_plan
from pm_agent.workbench import check_changes, describe_round, plan_changes

BEN = Member(name="Ben", skills={"SQL": 3}, hours_per_week=20)
PLAN = Plan.model_validate(plan_input())


def changed(**task_b):
    """The plan with task B changed and, optionally, given to someone else."""
    data = plan_input()
    member = task_b.pop("member", None)
    data["tasks"][1].update(task_b)
    if member:
        data["assignments"][1].update(member=member, reason="hat Zeit")
    return Plan.model_validate(data)


def test_an_unchanged_plan_has_no_changes():
    assert plan_changes(PLAN, Plan.model_validate(plan_input())) == []


def test_person_hours_title_and_dependencies_of_a_task_are_one_line():
    after = changed(member="Ben", estimate_hours=20, title="REST-API", depends_on=[])
    assert plan_changes(PLAN, after) == [
        "B · API: heißt jetzt „REST-API“; Anna → Ben; 16 h → 20 h; hängt ab von nichts (vorher A)"
    ]


def test_renumbered_tasks_are_matched_by_title_and_not_reported_as_renamed():
    # Claude puts a kickoff first and renumbers: A becomes B, B becomes C.
    data = plan_input()
    model, api = data["tasks"]
    data["tasks"] = [
        {"id": "A", "title": "Kickoff", "estimate_hours": 2},
        {**model, "id": "B", "depends_on": ["A"]},
        {**api, "id": "C", "depends_on": ["B"], "estimate_hours": 20},
    ]
    data["assignments"] = [
        {"task_id": tid, "member": "Anna", "reason": "kennt das Projekt"} for tid in "ABC"
    ]
    assert plan_changes(PLAN, Plan.model_validate(data)) == [
        "Neu: A · Kickoff (Anna, 2 h)",
        "B (vorher A) · Datenmodell: hängt ab von A (vorher nichts)",
        "C (vorher B) · API: 16 h → 20 h",
        "2 Aufgaben haben eine neue ID",
    ]


def test_new_and_removed_tasks_and_risks_are_named():
    data = plan_input()
    del data["tasks"][1], data["assignments"][1]
    data["tasks"].append({"id": "C", "title": "Tests", "estimate_hours": 4})
    data["assignments"].append({"task_id": "C", "member": "Anna", "reason": "kennt den Code"})
    data["risks"] = ["Zu wenig Zeit für Tests"]
    assert plan_changes(PLAN, Plan.model_validate(data)) == [
        "Neu: C · Tests (Anna, 4 h)",
        "Entfernt: B · API",
        "Neues Risiko: Zu wenig Zeit für Tests",
        "Risiko entfällt: Die Hochschule liefert die Raumdaten zu spät",
    ]


def test_the_check_says_how_the_end_the_warnings_and_the_dates_move():
    team = [*TEAM, BEN]
    before = check_plan(PLAN, team, PROJECT)
    # Ben takes A: he knows SQL, but has 4 h a day, so A takes two days and B starts later.
    data = plan_input(member="Ben")
    after = check_plan(Plan.model_validate(data), team, PROJECT)

    assert check_changes(before, after) == [
        "Planende: 11.11.2026 → 12.11.2026 (1 Arbeitstag später)",
        "Behoben: Task 'A' braucht 'SQL', Anna hat diese Fähigkeit nicht angegeben",
        "Termine von 2 Aufgaben verschieben sich",
    ]
    assert check_changes(after, before)[0] == (
        "Planende: 12.11.2026 → 11.11.2026 (1 Arbeitstag früher)"
    )
    assert check_changes(before, before) == []


def test_a_round_shows_the_draft_and_what_claude_changed_since_the_round_before():
    record = {
        "text": "Ben kennt SQL, ich gebe ihm das Datenmodell.",
        "tool_calls": [{"name": "submit_plan", "input": plan_input(member="Ben")}],
        "tool_results": [{"tool": "submit_plan", "is_error": False, "content": "Plan angenommen."}],
    }
    view = describe_round(2, record, PLAN)
    assert view["headline"] == "Runde 2 · submit_plan: Plan angenommen."
    assert view["said"] == "Ben kennt SQL, ich gebe ihm das Datenmodell."
    assert view["size"] == "2 Aufgaben, 24 h"
    assert view["changes"] == ["A · Datenmodell: Anna → Ben"]
    assert view["draft"] == Plan.model_validate(plan_input(member="Ben"))

    first = describe_round(1, record, None)  # nothing to compare the first draft with
    assert first["changes"] == [] and first["size"] == "2 Aufgaben, 24 h"


def test_a_round_without_a_readable_draft_keeps_the_tool_message():
    record = {
        "text": "",
        "tool_calls": [{"name": "check_plan", "input": {"tasks": []}}],
        "tool_results": [
            {
                "tool": "check_plan",
                "is_error": False,
                "content": '{"errors": ["x"], "warnings": []}',
            }
        ],
    }
    view = describe_round(1, record, PLAN)
    assert view["draft"] is None and view["size"] == "" and view["changes"] == []
    assert view["messages"] == ["x"]
