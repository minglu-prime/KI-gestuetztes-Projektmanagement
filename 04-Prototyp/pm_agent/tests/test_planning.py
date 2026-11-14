import time
from datetime import date, timedelta

import pytest

from pm_agent.models import Assignment, Member, Plan, Project, Task
from pm_agent.planning import add_workdays, check_plan, count_workdays, workday_shift

MON = date(2026, 11, 9)
ANNA = Member(name="Anna", skills={"Python": 4}, hours_per_week=40)  # 8 h per workday
BEN = Member(name="Ben", skills={"React": 3}, hours_per_week=40)


def project(start=MON, deadline=date(2026, 12, 18)):
    return Project(idea="Lernplattform für Erstsemester", start_date=start, deadline=deadline)


def task(tid, hours, deps=(), skills=()):
    return Task(
        id=tid,
        title=f"Task {tid}",
        estimate_hours=hours,
        depends_on=list(deps),
        required_skills=list(skills),
    )


def plan(*tasks, owners):
    assignments = [Assignment(task_id=t, member=m, reason="passt") for t, m in owners.items()]
    return Plan(tasks=list(tasks), assignments=assignments)


def by_id(result):
    return {s.task_id: s for s in result.schedule}


def test_workday_helpers_skip_weekends():
    fri, sat, sun = date(2026, 11, 13), date(2026, 11, 14), date(2026, 11, 15)
    assert add_workdays(fri, 0) == fri
    assert add_workdays(fri, 1) == date(2026, 11, 16)
    assert add_workdays(sat, 0) == date(2026, 11, 16)
    assert count_workdays(MON, sun) == 5
    assert count_workdays(sun, MON) == 0


def test_workday_helpers_match_counting_day_by_day():
    for first in [MON + timedelta(days=i) for i in range(7)]:  # each weekday as the start
        days = [first + timedelta(days=i) for i in range(30)]
        workdays = [day for day in days if day.weekday() < 5]
        assert [add_workdays(first, n) for n in range(len(workdays))] == workdays
        expected_counts = [sum(x.weekday() < 5 for x in days[: i + 1]) for i in range(len(days))]
        assert [count_workdays(first, day) for day in days] == expected_counts


def test_a_huge_estimate_does_not_freeze_the_check():
    # 15,000,000 h is absurd but still ends before the year 9999. Walking day by day
    # through about 1.9 million workdays took seconds per task, so one typo froze the check.
    tasks = [task("A", 15_000_000)] + [task(f"B{i}", 8, deps=["A"]) for i in range(10)]
    p = plan(*tasks, owners={t.id: "Anna" for t in tasks})
    began = time.perf_counter()
    result = check_plan(p, [ANNA], project())
    assert time.perf_counter() - began < 1
    assert result.ok


def test_plan_beyond_the_calendar_is_an_error_not_a_crash():
    result = check_plan(plan(task("A", 1e300), owners={"A": "Anna"}), [ANNA], project())
    assert result.errors == [
        "Task 'A' würde erst nach dem 31.12.9999 enden, so weit reicht der Kalender nicht"
    ]


def test_chain_for_one_member_runs_back_to_back():
    p = plan(task("A", 8), task("B", 16, deps=["A"]), owners={"A": "Anna", "B": "Anna"})
    result = check_plan(p, [ANNA], project())
    assert result.ok
    assert result.warnings == []
    assert (by_id(result)["A"].start, by_id(result)["A"].end) == (MON, MON)
    assert (by_id(result)["B"].start, by_id(result)["B"].end) == (
        date(2026, 11, 10),
        date(2026, 11, 11),
    )
    assert result.end_date == date(2026, 11, 11)
    assert result.critical_path == ["A", "B"]
    # 30 workdays from Mon 09.11. to Fri 18.12. at 8 h each; weekends do not count.
    assert (result.load[0].assigned_hours, result.load[0].capacity_hours) == (24, 240)


def test_members_work_in_parallel_and_critical_path_follows_the_longer_branch():
    # C comes first on purpose: the order of tasks in the LLM's plan must not matter.
    p = plan(
        task("C", 8, deps=["A", "B"]),
        task("A", 8),
        task("B", 16),
        owners={"A": "Anna", "B": "Ben", "C": "Anna"},
    )
    result = check_plan(p, [ANNA, BEN], project())
    assert by_id(result)["A"].start == by_id(result)["B"].start == MON
    assert by_id(result)["C"].start == date(2026, 11, 11)  # waits two days for B
    assert result.end_date == date(2026, 11, 11)
    assert result.critical_path == ["B", "C"]


def test_one_member_does_one_task_at_a_time_and_that_wait_is_on_the_critical_path():
    p = plan(task("A", 16), task("B", 8), owners={"A": "Anna", "B": "Anna"})
    result = check_plan(p, [ANNA], project())
    assert by_id(result)["B"].start == date(2026, 11, 11)
    assert result.critical_path == ["A", "B"]


def test_part_time_member_takes_longer():
    clara = Member(name="Clara", hours_per_week=10)  # 2 h per workday
    result = check_plan(plan(task("A", 5), owners={"A": "Clara"}), [clara], project())
    assert result.schedule[0].end == date(2026, 11, 11)  # 2.5 workdays: Mon to Wed


def test_next_task_starts_on_the_day_the_previous_one_ends():
    dora = Member(name="Dora", hours_per_week=38.5)  # 7.7 h per workday
    p = plan(
        task("A", 3.5),
        task("B", 35, deps=["A"]),
        task("C", 1, deps=["B"]),
        owners={"A": "Dora", "B": "Dora", "C": "Dora"},
    )
    s = by_id(check_plan(p, [dora], project()))
    assert s["B"].start == MON  # A takes less than a day
    # A + B = 38.5 h = exactly 5 workdays; the float offset is 4.999999999999999.
    assert s["C"].start == date(2026, 11, 16)


def test_plan_that_exactly_fits_is_neither_late_nor_overloaded_despite_float_noise():
    # 7 h/week = 1.4 h/day, so each 2.1 h task takes 1.5 days and the plan fills Mon-Wed.
    # The float sum is 3.0000000000000004 and the load 1.0000000000000002: a plain ceil
    # would end on Thursday, and a plain '> 1' would report an overload.
    clara = Member(name="Clara", hours_per_week=7)
    p = plan(task("A", 2.1), task("B", 2.1, deps=["A"]), owners={"A": "Clara", "B": "Clara"})
    result = check_plan(p, [clara], project(deadline=date(2026, 11, 11)))
    assert result.end_date == date(2026, 11, 11)
    assert result.warnings == [
        "Der Plan endet am 11.11.2026, bis zur Deadline (11.11.2026) bleibt kein Arbeitstag Puffer"
    ]


def test_overload_and_missed_deadline_are_warnings_not_errors():
    clara = Member(name="Clara", hours_per_week=10)  # 10 h available until Friday
    p = plan(task("A", 15), owners={"A": "Clara"})
    result = check_plan(p, [clara], project(deadline=date(2026, 11, 13)))
    assert result.ok
    assert result.load[0].utilization == pytest.approx(1.5)
    # 15 h at 2 h/day = 7.5 workdays: ends Wed 18.11., three workdays after Fri 13.11.
    assert result.end_date == date(2026, 11, 18)
    assert result.warnings == [
        "Der Plan endet am 18.11.2026, 3 Arbeitstage nach der Deadline (13.11.2026)",
        "Clara ist überlastet: 15 h zugewiesen, bis zur Deadline sind 10 h verfügbar (150%)",
    ]


def test_slight_overload_reads_101_percent_and_one_day_late_is_singular():
    p = plan(task("A", 40.1), owners={"A": "Anna"})  # 5.0125 workdays: ends Mon 16.11.
    result = check_plan(p, [ANNA], project(deadline=date(2026, 11, 13)))
    assert result.warnings == [
        "Der Plan endet am 16.11.2026, 1 Arbeitstag nach der Deadline (13.11.2026)",
        "Anna ist überlastet: 40.1 h zugewiesen, bis zur Deadline sind 40 h verfügbar (101%)",
    ]


def test_a_plan_without_a_workday_of_buffer_before_the_deadline_is_a_warning():
    p = plan(task("A", 24), owners={"A": "Anna"})  # 3 workdays: Mon 09.11. to Wed 11.11.
    on_the_day = check_plan(p, [ANNA], project(deadline=date(2026, 11, 11)))
    assert on_the_day.warnings == [
        "Der Plan endet am 11.11.2026, bis zur Deadline (11.11.2026) bleibt kein Arbeitstag Puffer"
    ]
    one_day_left = check_plan(p, [ANNA], project(deadline=date(2026, 11, 12)))
    assert one_day_left.warnings == []


def test_a_weekend_before_the_deadline_is_no_buffer():
    p = plan(task("A", 40), owners={"A": "Anna"})  # Mon 09.11. to Fri 13.11.
    result = check_plan(p, [ANNA], project(deadline=date(2026, 11, 15)))  # a Sunday
    assert result.warnings == [
        "Der Plan endet am 13.11.2026, bis zur Deadline (15.11.2026) bleibt kein Arbeitstag Puffer"
    ]


def test_missing_skill_of_the_assignee_is_a_warning_and_case_is_ignored():
    # Ben knows React, but the task is Anna's. 'PYTHON' matches Anna's 'Python'.
    p = plan(task("A", 8, skills=["PYTHON", "React"]), owners={"A": "Anna"})
    result = check_plan(p, [ANNA, BEN], project())
    assert result.warnings == ["Task 'A' braucht 'React', Anna hat diese Fähigkeit nicht angegeben"]


def test_structural_errors_are_all_reported_and_stop_scheduling():
    p = Plan(
        tasks=[task("A", 8, deps=["X"]), task("A", 8), task("B", 8)],
        assignments=[
            Assignment(task_id="A", member="Anna", reason="passt"),
            Assignment(task_id="A", member="Anna", reason="passt"),
            Assignment(task_id="Z", member="Zoe", reason="passt"),
        ],
    )
    result = check_plan(p, [ANNA, ANNA], project())
    assert not result.ok
    assert result.schedule == []
    assert sorted(result.errors) == sorted(
        [
            "Der Name 'Anna' kommt im Team mehrfach vor",
            "Die Task-ID 'A' ist mehrfach vergeben",
            "Task 'A' hängt von der unbekannten Task 'X' ab",
            "Zuweisung für die unbekannte Task 'Z'",
            "Task 'Z' ist 'Zoe' zugewiesen, diese Person ist nicht im Team",
            "Task 'A' ist mehrfach zugewiesen",
            "Task 'B' ist niemandem zugewiesen",
        ]
    )


def test_duplicate_ids_do_not_add_a_cycle_error():
    # Merged into one graph, A -> B -> A would look like a cycle. Which A is meant is unclear.
    p = plan(
        task("A", 8),
        task("B", 8, deps=["A"]),
        task("A", 8, deps=["B"]),
        owners={"A": "Anna", "B": "Anna"},
    )
    assert check_plan(p, [ANNA], project()).errors == ["Die Task-ID 'A' ist mehrfach vergeben"]


def test_cycle_is_reported_with_its_path():
    p = plan(task("A", 8, deps=["B"]), task("B", 8, deps=["A"]), owners={"A": "Anna", "B": "Anna"})
    [error] = check_plan(p, [ANNA], project()).errors
    prefix = "Zyklische Abhängigkeit: "
    assert error.startswith(prefix)
    assert set(error.removeprefix(prefix).split(" → ")) == {"A", "B"}


def test_self_dependency_is_a_cycle():
    p = plan(task("A", 8, deps=["A"]), owners={"A": "Anna"})
    assert check_plan(p, [ANNA], project()).errors == ["Zyklische Abhängigkeit: A → A"]


def test_no_workday_between_start_and_deadline_is_an_error():
    weekend = project(start=date(2026, 11, 14), deadline=date(2026, 11, 15))
    result = check_plan(plan(task("A", 8), owners={"A": "Anna"}), [ANNA], weekend)
    assert result.errors == [
        "Zwischen Start (14.11.2026) und Deadline (15.11.2026) liegt kein Arbeitstag"
    ]


def test_empty_team_is_an_error():
    result = check_plan(plan(task("A", 8), owners={"A": "Anna"}), [], project())
    assert "Das Team ist leer" in result.errors


def test_workday_shift_counts_workdays_between_two_dates_with_a_sign():
    assert workday_shift(date(2026, 11, 11), date(2026, 11, 12)) == 1
    assert workday_shift(date(2026, 11, 12), date(2026, 11, 11)) == -1
    assert workday_shift(date(2026, 11, 13), date(2026, 11, 16)) == 1  # Friday to Monday
    assert workday_shift(MON, MON) == 0
