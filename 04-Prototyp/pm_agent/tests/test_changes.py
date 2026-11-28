"""What changed between two plans, and what the progress view says about one agent round."""

from datetime import date

from test_tools import PROJECT, TEAM, plan_input

from pm_agent.models import Member, Plan, Project
from pm_agent.planning import check_plan
from pm_agent.workbench import check_changes, describe_round, pair_tasks, plan_changes

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
    # The agent puts a kickoff first and renumbers: A becomes B, B becomes C.
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


def simple(*tasks):
    """A plan from (id, title, member, hours, depends_on) tuples."""
    return Plan.model_validate(
        {
            "tasks": [
                {"id": i, "title": title, "estimate_hours": hours, "depends_on": deps}
                for i, title, _, hours, deps in tasks
            ],
            "assignments": [
                {"task_id": i, "member": member, "reason": "r"} for i, _, member, _, _ in tasks
            ],
        }
    )


def test_a_warning_whose_numbers_change_stays_a_warning():
    # Clara has 10 h until Friday. 15 h are too much, and so are 12 h.
    clara = Member(name="Clara", hours_per_week=10)
    week = Project(idea="x", start_date=date(2026, 11, 9), deadline=date(2026, 11, 13))
    before = check_plan(simple(("A", "Bericht", "Clara", 15, [])), [clara], week)
    after = check_plan(simple(("A", "Bericht", "Clara", 12, [])), [clara], week)

    assert check_changes(before, after) == [
        "Planende: 18.11.2026 → 16.11.2026 (2 Arbeitstage früher)",
        "Warnung bleibt: Der Plan endet am 16.11.2026, 1 Arbeitstag nach der Deadline (13.11.2026)",
        "Warnung bleibt: Clara ist überlastet: 12 h zugewiesen, bis zur Deadline sind 10 h "
        "verfügbar (120 %)",
        "Termine von einer Aufgabe verschieben sich",
    ]


def test_a_dependency_on_a_removed_task_is_not_hidden_by_a_reused_id():
    before = simple(
        ("T1", "A", "Anna", 8, []), ("T2", "B", "Anna", 8, []), ("T3", "C", "Anna", 8, ["T2"])
    )
    # B is gone, A has taken its ID: C now waits for A instead of B.
    after = simple(("T2", "A", "Anna", 8, []), ("T3", "C", "Anna", 8, ["T2"]))
    assert plan_changes(before, after) == [
        "Entfernt: T2 · B",
        "T3 · C: hängt ab von T2 (vorher T2 [entfernt])",
        "Eine Aufgabe hat eine neue ID",
    ]


def test_tasks_with_the_same_title_are_not_paired_by_title():
    before = simple(("T1", "Test", "Anna", 8, []), ("T2", "Test", "Ben", 4, []))
    after = simple(("T3", "Test", "Anna", 8, []), ("T4", "Test", "Ben", 4, []))
    assert pair_tasks(before, after) == {}
    # Which is which cannot be known: no invented reassignment, the tasks are listed.
    assert plan_changes(before, after) == [
        "Neu: T3 · Test (Anna, 8 h)",
        "Neu: T4 · Test (Ben, 4 h)",
        "Entfernt: T1 · Test",
        "Entfernt: T2 · Test",
    ]


def test_renumbering_alone_changes_nothing_in_the_check():
    renumbered = plan_input()
    renumbered["tasks"][0]["id"] = "X1"
    renumbered["tasks"][1].update(id="X2", depends_on=["X1"])
    renumbered["assignments"][0]["task_id"] = "X1"
    renumbered["assignments"][1]["task_id"] = "X2"
    after = Plan.model_validate(renumbered)
    pairs = pair_tasks(PLAN, after)
    assert pairs == {"A": "X1", "B": "X2"}
    # Same dates, and the missing skill is the same warning about the same task.
    assert (
        check_changes(check_plan(PLAN, TEAM, PROJECT), check_plan(after, TEAM, PROJECT), pairs)
        == []
    )


def skilled(*tasks):
    """A plan of 8 h tasks from (ID, title, member, skills)."""
    return Plan.model_validate(
        {
            "tasks": [
                {"id": i, "title": title, "estimate_hours": 8, "required_skills": skills}
                for i, title, _, skills in tasks
            ],
            "assignments": [
                {"task_id": i, "member": member, "reason": "r"} for i, _, member, _ in tasks
            ],
        }
    )


def test_a_warning_about_a_removed_task_is_not_taken_for_the_task_with_its_id():
    team = [*TEAM, BEN]  # Anna has not named SQL, Ben has
    before = skilled(
        ("T1", "A", "Anna", []), ("T2", "B", "Anna", ["SQL"]), ("T3", "C", "Ben", ["SQL"])
    )
    # B is gone. C has taken its ID and went from Ben to Anna, who has not named SQL.
    after = skilled(("T1", "A", "Anna", []), ("T2", "C", "Anna", ["SQL"]))
    pairs = pair_tasks(before, after)
    assert pairs == {"T1": "T1", "T3": "T2"}
    lines = check_changes(
        check_plan(before, team, PROJECT), check_plan(after, team, PROJECT), pairs
    )
    assert (
        "Neue Warnung: Task 'T2' braucht 'SQL', Anna hat diese Fähigkeit nicht angegeben" in lines
    )
    # The warning about B went with B ("Entfernt: T2 · B" says so): nobody solved it.
    assert not any(line.startswith("Behoben") for line in lines)


def test_a_colon_in_an_id_or_a_skill_does_not_mix_up_the_warnings():
    def check(plan):
        return check_plan(plan, TEAM, PROJECT)

    before = skilled(("A", "Entwurf", "Anna", []), ("A:1", "Abfragen", "Anna", ["SQL"]))
    after = skilled(("X", "Entwurf", "Anna", []), ("A:1", "Abfragen", "Anna", ["SQL"]))
    assert check_changes(check(before), check(after), pair_tasks(before, after)) == []
    # "A" needing "1:SQL" and "A:1" needing "SQL" are two warnings.
    both = skilled(("A", "Entwurf", "Anna", ["1:SQL"]), ("A:1", "Abfragen", "Anna", ["SQL"]))
    assert check_changes(check(both), check(before)) == [
        "Behoben: Task 'A' braucht '1:SQL', Anna hat diese Fähigkeit nicht angegeben"
    ]


def test_a_dependency_on_a_task_that_never_existed_is_not_called_removed():
    # Two drafts in a row with the same mistake: T2 waits for T9, which is in neither.
    before = simple(("T1", "A", "Anna", 8, []), ("T2", "B", "Anna", 8, ["T9"]))
    after = simple(("T1", "A", "Anna", 4, []), ("T2", "B", "Anna", 8, ["T9"]))
    assert plan_changes(before, after) == ["T1 · A: 8 h → 4 h"]


def test_without_pairs_a_removed_task_takes_its_warning_along_as_well():
    before = skilled(("A", "Entwurf", "Anna", []), ("B", "Abfragen", "Anna", ["SQL"]))
    after = skilled(("A", "Entwurf", "Anna", []))
    lines = check_changes(check_plan(before, TEAM, PROJECT), check_plan(after, TEAM, PROJECT))
    assert not any(line.startswith("Behoben") for line in lines)


def test_the_same_tasks_in_another_order_are_a_change():
    # The order decides which of two tasks goes first when both could start: the dates can
    # move although no task changed.
    before = simple(("T1", "A", "Anna", 8, []), ("T2", "B", "Anna", 8, []))
    after = simple(("T2", "B", "Anna", 8, []), ("T1", "A", "Anna", 8, []))
    assert plan_changes(before, after) == [
        "Reihenfolge der Aufgaben geändert: Können zwei Aufgaben gleichzeitig beginnen, "
        "wird zuerst eingeplant, was weiter oben steht"
    ]
    # A task in between changes nobody's place.
    more = simple(
        ("T1", "A", "Anna", 8, []), ("T3", "C", "Anna", 4, []), ("T2", "B", "Anna", 8, [])
    )
    assert plan_changes(before, more) == ["Neu: T3 · C (Anna, 4 h)"]


def test_the_end_of_a_proposal_moves_in_working_days_of_the_project():
    # 24.12.2026 to 01.01.2027 is free for everybody. 24 h end on 23.12., 32 h on the first
    # day after the break: one working day later, eight Mon-Fri days.
    winter = Project(
        idea="x",
        start_date=date(2026, 12, 21),
        deadline=date(2027, 1, 8),
        free_days=[{"first": date(2026, 12, 24), "last": date(2027, 1, 1)}],
    )
    before = check_plan(simple(("A", "a", "Anna", 24, [])), TEAM, winter)
    after = check_plan(simple(("A", "a", "Anna", 32, [])), TEAM, winter)
    assert check_changes(before, after, project=winter)[0] == (
        "Planende: 23.12.2026 → 04.01.2027 (1 Arbeitstag später)"
    )
    # Without the project nothing is known about free days.
    assert check_changes(before, after)[0] == (
        "Planende: 23.12.2026 → 04.01.2027 (8 Arbeitstage später)"
    )


def test_a_changed_trace_is_a_change():
    # A proposal that only links tasks to requirements must not read as "no change".
    assert plan_changes(PLAN, changed(requirement_ids=["R1"])) == [
        "B · API: dient R1 (vorher keiner Anforderung)"
    ]


def test_changed_demos_are_listed():
    def plan(*demos):
        return Plan.model_validate({**plan_input(), "demos": list(demos)})

    one = {"week": 1, "title": "API zeigen", "task_ids": ["B"]}
    before = plan(one, {"week": 2, "title": "Liste zeigen", "task_ids": ["A"]})
    after = plan(
        {**one, "task_ids": ["A", "B"]}, {"week": 3, "title": "Login zeigen", "task_ids": ["A"]}
    )
    assert [line for line in plan_changes(before, after) if "Demo" in line] == [
        "Neue Demo in Woche 3: Login zeigen (A)",
        "Demo der Woche 2 entfällt: Liste zeigen",
        "Demo der Woche 1 (API zeigen): braucht jetzt A, B (vorher B)",
    ]
