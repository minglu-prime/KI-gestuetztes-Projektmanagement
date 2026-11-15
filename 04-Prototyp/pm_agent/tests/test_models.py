from datetime import date

import pytest
from pydantic import ValidationError

from pm_agent.models import Absence, Assignment, Member, Plan, Project, Task


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


@pytest.mark.parametrize("hours", [0, 0.5, 169, float("inf")])
def test_weekly_hours_must_fit_into_a_week(hours):
    with pytest.raises(ValidationError):
        Member(name="Anna", hours_per_week=hours)


@pytest.mark.parametrize("hours", [1, 168])
def test_weekly_hours_from_1_to_168_are_valid(hours):
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
