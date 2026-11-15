"""Adopting the rest of a project again keeps the work done so far as history."""

import json
from datetime import date

import pytest
from test_tools import PROJECT, TEAM, plan_input

from pm_agent.followup import facts
from pm_agent.models import Plan
from pm_agent.tracking import (
    Earlier,
    adopt,
    apply_rows,
    control_document,
    earned_value,
    evaluate,
    finished_again,
    has_progress,
    load,
    progress_rows,
    rest_project,
    save,
    status_report,
)
from pm_agent.workbench import InputError

# Anna, 8 h a workday. A (8 h) on Mon 09.11., B (16 h, after A) on 10.–11.11.
PLAN = Plan.model_validate(plan_input())
THURSDAY = date(2026, 11, 12)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "projekt.json"


@pytest.fixture
def replanned(path):
    """Thu 12.11.: A is done with 10 h, B has 4 of its 16 h booked. The rest (B with 12 h,
    from today) is adopted again and keeps what was done."""
    first = adopt(PROJECT, TEAM, PLAN, path=path)
    first = apply_rows(
        first,
        [
            {"ID": "A", "Status": "fertig", "Ist (h)": 10, "Notiz": "Schema zweimal geändert"},
            {"ID": "B", "Status": "in Arbeit", "Ist (h)": 4, "Notiz": "Auth fehlt"},
        ],
    )
    project, rest = rest_project(first, THURSDAY)
    return adopt(project, TEAM, rest, path=path, keep=first)


def test_the_work_before_the_new_plan_is_kept_as_history(replanned, path):
    day = replanned.adopted.date()
    assert replanned.history == [
        Earlier(
            id="A",
            title="Datenmodell",
            member="Anna",
            planned_hours=8,
            actual_hours=10,
            finished=True,
            note="Schema zweimal geändert",
            until=day,
        ),
        # The part of B's estimate the 4 booked hours stood for; 12 h are in the new plan.
        Earlier(
            id="B",
            title="API",
            member="Anna",
            planned_hours=4,
            actual_hours=4,
            finished=False,
            note="Auth fehlt",
            until=day,
        ),
    ]
    assert load(path) == replanned
    assert has_progress(replanned)


def test_a_started_task_goes_on_in_the_new_plan_with_its_booked_hours_in_the_history(replanned):
    (row,) = progress_rows(replanned, THURSDAY)
    assert (row["ID"], row["Plan (h)"], row["Status"], row["Ist (h)"], row["Notiz"]) == (
        "B",
        12,
        "in Arbeit",
        0,
        "Auth fehlt",
    )


def test_the_numbers_count_the_history_and_nothing_twice(replanned):
    result = evaluate(replanned, THURSDAY)
    assert result.planned_hours == 24  # 8 + 4 + 12: as much as the first plan had
    assert result.actual_hours == 14
    assert result.earned == 8  # A; B's part counts when B is finished
    assert result.progress == pytest.approx(8 / 24)
    assert result.finished_deviation == 2
    assert result.by_member == [
        {"Person": "Anna", "Plan (h)": 24, "Ist (h)": 14, "Fertig (Plan-h)": 8}
    ]

    finished = apply_rows(replanned, [{"ID": "B", "Status": "fertig", "Ist (h)": 13}])
    done = evaluate(finished, THURSDAY)
    assert (done.earned, done.progress, done.actual_hours) == (24, 1, 27)
    assert done.finished_deviation == 3  # A +2, B 4 + 13 against 4 + 12: +1


def test_the_planned_value_includes_the_planned_hours_of_the_history(replanned):
    # The new plan starts on Thursday: 8 h are due by its end, and 12 h before it.
    value = earned_value(replanned, evaluate(replanned, THURSDAY))
    assert (value.planned, value.earned, value.actual) == (20, 8, 14)


def test_adopting_again_and_again_keeps_the_whole_estimate(replanned, path):
    # Fri 13.11.: B has 6 h booked and 3 h left. Its rest is adopted once more.
    later = apply_rows(replanned, [{"ID": "B", "Status": "in Arbeit", "Ist (h)": 6, "Rest (h)": 3}])
    project, rest = rest_project(later, date(2026, 11, 13))
    again = adopt(project, TEAM, rest, path=path, keep=later)
    assert [(e.id, e.planned_hours, e.actual_hours, e.finished) for e in again.history] == [
        ("A", 8, 10, True),
        ("B", 4, 4, False),
        ("B", 9, 6, False),
    ]
    assert evaluate(again, date(2026, 11, 13)).planned_hours == 24


def test_a_finished_task_cannot_come_back_in_the_plan_that_keeps_it(path):
    # The whole plan again instead of its rest: A would count twice.
    first = apply_rows(
        adopt(PROJECT, TEAM, PLAN, path=path), [{"ID": "A", "Status": "fertig", "Ist (h)": 9}]
    )
    save(first, path)
    assert finished_again(first, PLAN) == ["A"]
    with pytest.raises(InputError, match="Fertige Aufgabe wieder im Plan: A"):
        adopt(PROJECT, TEAM, PLAN, path=path, keep=first)
    assert load(path) == first  # nothing was saved


def test_without_keep_the_new_plan_starts_without_history(replanned, path):
    fresh = adopt(PROJECT, TEAM, PLAN, path=path)
    assert fresh.history == []
    assert not has_progress(fresh)


def test_a_project_saved_before_the_history_existed_still_loads(path):
    saved = json.loads(adopt(PROJECT, TEAM, PLAN, path=path).model_dump_json())
    del saved["history"]
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert load(path).history == []


def test_the_documents_and_the_agents_see_the_history(replanned):
    result = evaluate(replanned, THURSDAY)
    report = status_report(replanned, result)
    assert "## Aus früheren Plänen" in report
    assert "| A | Datenmodell | Anna | fertig | 8 | 10 | Schema zweimal geändert |" in report
    assert "| B | API | Anna | Teil, ging weiter | 4 | 4 | Auth fehlt |" in report
    assert "## Aus früheren Plänen" in control_document(replanned, result)
    sent = json.loads(facts(replanned, result))
    assert [(e["id"], e["finished"]) for e in sent["frueher"]] == [("A", True), ("B", False)]
