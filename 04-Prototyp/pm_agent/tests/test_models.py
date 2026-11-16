from datetime import date

import pytest
from pydantic import ValidationError

from pm_agent.models import (
    Absence,
    Assignment,
    Charter,
    Criterion,
    Member,
    Plan,
    Project,
    Requirement,
    Task,
)
from pm_agent.tools import invalid_input


@pytest.mark.parametrize("hours", [0, -4, float("inf")])
def test_task_estimate_must_be_positive_and_finite(hours):
    with pytest.raises(ValidationError):
        Task(id="A", title="Login", estimate_hours=hours)


@pytest.mark.parametrize("level", [0, 6])
def test_skill_level_is_between_1_and_5(level):
    with pytest.raises(ValidationError):
        Member(name="Anna", skills={"Python": level}, hours_per_week=10)


@pytest.mark.parametrize("level", [1, 5])
def test_skill_levels_1_and_5_are_valid(level):
    member = Member(name="Anna", skills={"Python": level}, hours_per_week=10)
    assert member.skills == {"Python": level}


# The plan spreads the weekly hours over Monday to Friday: more than 5 x 24 h would make a
# workday longer than a day (168 h gave 33.6 h a day).
@pytest.mark.parametrize("hours", [0, 0.5, 121, 168, float("inf")])
def test_weekly_hours_must_fit_into_five_workdays(hours):
    with pytest.raises(ValidationError):
        Member(name="Anna", hours_per_week=hours)


@pytest.mark.parametrize("hours", [1, 120])
def test_weekly_hours_from_1_to_120_are_valid(hours):
    assert Member(name="Anna", hours_per_week=hours).hours_per_week == hours


def test_blank_strings_are_rejected_and_whitespace_is_stripped():
    with pytest.raises(ValidationError):
        Member(name="   ", hours_per_week=10)
    assert Member(name="  Anna ", hours_per_week=10).name == "Anna"


def test_misspelled_field_from_the_llm_is_rejected():
    with pytest.raises(ValidationError) as err:
        Task.model_validate({"id": "A", "title": "Login", "estimate_hours": 8, "hours": 8})
    assert err.value.errors()[0]["type"] == "extra_forbidden"


def test_assignment_needs_a_reason():
    with pytest.raises(ValidationError):
        Assignment(task_id="A", member="Anna", reason="")
    with pytest.raises(ValidationError):
        Assignment.model_validate({"task_id": "A", "member": "Anna"})


def test_deadline_may_equal_the_start_but_not_precede_it():
    Project(idea="App", start_date=date(2026, 11, 9), deadline=date(2026, 11, 9))
    with pytest.raises(ValidationError, match="Deadline liegt vor dem Startdatum"):
        Project(idea="App", start_date=date(2026, 11, 9), deadline=date(2026, 11, 6))


def test_plan_needs_at_least_one_task():
    with pytest.raises(ValidationError):
        Plan(tasks=[], assignments=[])


def test_an_absence_is_a_day_or_a_range_and_cannot_end_before_it_starts():
    Absence(first=date(2026, 12, 1), last=date(2026, 12, 1))
    with pytest.raises(ValidationError, match="Ende der Abwesenheit liegt vor ihrem Beginn"):
        Absence(first=date(2026, 12, 5), last=date(2026, 12, 1))


def test_a_member_saved_before_absences_existed_still_loads():
    assert Member.model_validate({"name": "Anna", "hours_per_week": 20}).absences == []


def test_a_task_saved_before_requirements_existed_still_loads():
    task = Task.model_validate({"id": "A", "title": "Login", "estimate_hours": 4})
    assert task.requirement_ids == []


def requirement(**changes):
    data = {
        "id": "R1",
        "title": "Raum buchen",
        "story": "Als Studentin will ich einen Raum buchen, damit meine Gruppe arbeiten kann.",
        "priority": "Muss",
        "criteria": ["Eine Buchung erscheint sofort in der Liste"],
        "sources": ["K1"],
    }
    return {**data, **changes}


def test_a_requirement_needs_a_criterion_and_a_known_priority():
    assert Requirement.model_validate(requirement()).priority == "Muss"
    for broken in [requirement(criteria=[]), requirement(priority="Wichtig")]:
        with pytest.raises(ValidationError):
            Requirement.model_validate(broken)


@pytest.mark.parametrize("ref", ["R 1", "R1,R2", ""])
def test_ids_have_no_separator(ref):
    # The plan table lists several requirements in one cell, separated by commas.
    with pytest.raises(ValidationError):
        Requirement.model_validate(requirement(id=ref))
    with pytest.raises(ValidationError):
        Task(id="A", title="Login", estimate_hours=4, requirement_ids=[ref])
    with pytest.raises(ValidationError):
        Criterion(id=ref, text="Buchung in unter einer Minute")


def test_a_charter_needs_scope_and_a_success_criterion():
    charter = {
        "goal": "Gruppenräume online buchen",
        "benefit": "Weniger Wege zum Infoschalter",
        "in_scope": ["Buchen und Stornieren"],
        "success_criteria": [{"id": "K1", "text": "Buchung in unter einer Minute"}],
    }
    assert Charter.model_validate(charter).stakeholders == []
    for broken in [{**charter, "in_scope": []}, {**charter, "success_criteria": []}]:
        with pytest.raises(ValidationError):
            Charter.model_validate(broken)


def test_the_new_rules_are_explained_in_german():
    with pytest.raises(ValidationError) as bad_id:
        Requirement.model_validate(requirement(id="R 1"))
    with pytest.raises(ValidationError) as bad_priority:
        Requirement.model_validate(requirement(priority="Wichtig"))
    assert invalid_input(bad_id.value) == [
        "Ungültige Eingabe bei id: darf nur Buchstaben, Ziffern, Punkt, Binde- und "
        "Unterstrich enthalten"
    ]
    assert invalid_input(bad_priority.value) == [
        "Ungültige Eingabe bei priority: muss Muss, Soll oder Kann sein"
    ]
