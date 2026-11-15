import random
import time
from datetime import date, timedelta

import pytest

from pm_agent.models import Assignment, Member, Plan, Project, Task
from pm_agent.planning import (
    add_workdays,
    check_plan,
    count_workdays,
    planned_work,
    workday_shift,
)

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


def away(first, last=None, name="Anna", hours=40):
    """Anna (8 h per workday) with one absence."""
    absence = {"first": first, "last": last or first}
    return Member(name=name, skills={"Python": 4}, hours_per_week=hours, absences=[absence])


def test_work_starts_after_an_absence_on_the_first_day():
    p = plan(task("A", 8), owners={"A": "Anna"})
    s = by_id(check_plan(p, [away(MON)], project()))
    assert (s["A"].start, s["A"].end) == (date(2026, 11, 10), date(2026, 11, 10))


def test_an_absence_in_the_middle_of_a_task_stretches_it():
    p = plan(task("A", 24), owners={"A": "Anna"})  # three days of work
    s = by_id(check_plan(p, [away(date(2026, 11, 10))], project()))  # away on Tuesday
    assert (s["A"].start, s["A"].end) == (MON, date(2026, 11, 12))  # Mon, Wed, Thu


def test_an_absence_over_a_weekend_costs_its_workdays_only():
    p = plan(task("A", 40), owners={"A": "Anna"})  # one week of work
    friday_to_monday = away(date(2026, 11, 13), date(2026, 11, 16))
    s = by_id(check_plan(p, [friday_to_monday], project()))
    # Mon-Thu, then Tue 17.11.: Friday and Monday are gone.
    assert (s["A"].start, s["A"].end) == (MON, date(2026, 11, 17))


def test_the_rest_of_a_day_is_used_before_an_absence():
    # A takes the first half of Monday. B (8 h) gets the second half, waits out Tuesday and
    # ends on Wednesday at noon.
    p = plan(task("A", 4), task("B", 8, deps=["A"]), owners={"A": "Anna", "B": "Anna"})
    s = by_id(check_plan(p, [away(date(2026, 11, 10))], project()))
    assert (s["B"].start, s["B"].end) == (MON, date(2026, 11, 11))


def test_absences_outside_the_project_and_on_weekends_change_nothing():
    p = plan(task("A", 8), task("B", 16, deps=["A"]), owners={"A": "Anna", "B": "Anna"})
    plain = check_plan(p, [ANNA], project())
    for first, last in [
        (date(2026, 10, 1), date(2026, 11, 8)),  # before the start
        (date(2026, 11, 14), date(2026, 11, 15)),  # a weekend
        (date(2027, 1, 4), date(2027, 1, 8)),  # after the plan has ended
    ]:
        result = check_plan(p, [away(first, last)], project())
        assert result.schedule == plain.schedule, (first, last)


def test_an_absence_of_one_person_does_not_move_the_others():
    p = plan(task("A", 8), task("B", 8), owners={"A": "Anna", "B": "Ben"})
    s = by_id(check_plan(p, [away(MON), BEN], project()))
    assert s["A"].start == date(2026, 11, 10) and s["B"].start == MON


def test_absent_days_are_not_available_until_the_deadline():
    # Mon-Fri window, Anna is away on two of the five days: 24 h instead of 40 h.
    p = plan(task("A", 32), owners={"A": "Anna"})
    two_days = away(date(2026, 11, 10), date(2026, 11, 11))
    result = check_plan(p, [two_days], project(deadline=date(2026, 11, 13)))
    assert result.load[0].capacity_hours == 24
    assert result.load[0].utilization == pytest.approx(32 / 24)
    assert "Anna ist überlastet: 32 h zugewiesen, bis zur Deadline sind 24 h verfügbar (134%)" in (
        result.warnings
    )


def test_someone_away_for_the_whole_project_has_no_capacity_and_that_is_said():
    p = plan(task("A", 8), owners={"A": "Anna"})
    gone = away(date(2026, 11, 1), date(2026, 12, 31))
    result = check_plan(p, [gone], project())  # deadline 18.12.
    assert result.ok
    assert (result.load[0].capacity_hours, result.load[0].utilization) == (0, None)
    assert result.schedule[0].start == date(2027, 1, 1)
    assert (
        "Anna ist bis zur Deadline durchgehend abwesend, hat aber 8 h zugewiesen" in result.warnings
    )


def test_an_absence_to_the_end_of_the_calendar_is_an_error_not_an_endless_loop():
    p = plan(task("A", 8), owners={"A": "Anna"})
    result = check_plan(p, [away(MON, date.max)], project())
    assert result.errors == [
        "Task 'A' würde erst nach dem 31.12.9999 enden, so weit reicht der Kalender nicht"
    ]


def test_overlapping_and_unsorted_absences_count_once():
    anna = Member(
        name="Anna",
        hours_per_week=40,
        absences=[
            {"first": date(2026, 11, 11), "last": date(2026, 11, 12)},
            {"first": date(2026, 11, 10), "last": date(2026, 11, 11)},
        ],
    )
    p = plan(task("A", 16), owners={"A": "Anna"})
    result = check_plan(p, [anna], project(deadline=date(2026, 11, 13)))
    s = by_id(result)
    assert (s["A"].start, s["A"].end) == (MON, date(2026, 11, 13))  # Mon, then Fri
    assert result.load[0].capacity_hours == 16  # five days, three of them away


def test_slack_is_how_many_workdays_a_task_can_slip_without_moving_the_end():
    # Anna works Mon-Wed on A and C. Ben's B (one day) could also be done on Tue or Wed.
    p = plan(
        task("A", 8),
        task("B", 8),
        task("C", 16, deps=["A"]),
        owners={"A": "Anna", "B": "Ben", "C": "Anna"},
    )
    result = check_plan(p, [ANNA, BEN], project())
    assert result.end_date == date(2026, 11, 11)
    assert result.slack == {"A": 0, "B": 2, "C": 0}


def test_slack_is_shared_along_a_chain():
    # Ben: B then D, Mon and Tue. Either may slip one day, but not both.
    p = plan(
        task("A", 24),
        task("B", 8),
        task("D", 8, deps=["B"]),
        owners={"A": "Anna", "B": "Ben", "D": "Ben"},
    )
    assert check_plan(p, [ANNA, BEN], project()).slack == {"A": 0, "B": 1, "D": 1}


def test_slack_counts_whole_workdays_and_skips_absences():
    # Ben needs Mon-Wed. Anna's A takes Monday; she is away on Tuesday. Slipping one day
    # lands on Wednesday, slipping two days as well: only the third day moves the end.
    p = plan(task("A", 8), task("B", 24), owners={"A": "Anna", "B": "Ben"})
    result = check_plan(p, [away(date(2026, 11, 10)), BEN], project())
    assert result.slack == {"A": 2, "B": 0}
    # Half a day of room is no whole workday.
    half = plan(task("A", 4), task("B", 8), owners={"A": "Anna", "B": "Ben"})
    assert check_plan(half, [ANNA, BEN], project()).slack == {"A": 0, "B": 0}


def test_a_plan_with_errors_has_no_slack():
    p = plan(task("A", 8), owners={"A": "Zoe"})
    assert check_plan(p, [ANNA], project()).slack == {}


def test_a_task_that_only_waits_for_an_absence_is_not_on_the_critical_path():
    # Ben does A on Monday. Anna is away all week and does B (after A) from the next Monday,
    # whenever A is done that week. A can slip four days, so it is not critical.
    anna = away(MON, date(2026, 11, 13))
    p = plan(task("A", 8), task("B", 8, deps=["A"]), owners={"A": "Ben", "B": "Anna"})
    result = check_plan(p, [anna, BEN], project())
    assert by_id(result)["B"].start == date(2026, 11, 16)
    assert result.slack == {"A": 4, "B": 0}
    assert result.critical_path == ["B"]


def test_slack_counts_days_that_an_absence_makes_harmless():
    # Anna is away on Tuesday. A (16 h) runs Mon and Wed; Ben's B ends on Thursday. A can
    # also run Wed and Thu: two days later (one of them is the absence).
    anna = away(date(2026, 11, 10))
    p = plan(task("A", 16), task("B", 32), owners={"A": "Anna", "B": "Ben"})
    assert check_plan(p, [anna, BEN], project()).slack == {"A": 2, "B": 0}
    # C takes Monday morning, D (8 h) Monday afternoon and Wednesday morning. A day later D
    # is done within Wednesday, the day the plan ends anyway.
    q = plan(
        task("C", 4),
        task("D", 8, deps=["C"]),
        task("B", 24),
        owners={"C": "Anna", "D": "Anna", "B": "Ben"},
    )
    assert check_plan(q, [anna, BEN], project()).slack["D"] == 1


def test_every_warning_has_a_kind_that_survives_changing_numbers():
    clara = Member(name="Clara", hours_per_week=10)
    p = plan(task("A", 15, skills=["SQL"]), owners={"A": "Clara"})
    result = check_plan(p, [clara], project(deadline=date(2026, 11, 13)))
    assert result.warning_kinds == [
        ("late",),
        ("overload", "Clara"),
        ("skill", "A", "SQL"),
    ]
    assert len(result.warning_kinds) == len(result.warnings)
    on_the_day = check_plan(plan(task("A", 8), owners={"A": "Anna"}), [ANNA], project(deadline=MON))
    assert on_the_day.warning_kinds == [("buffer",)]
    gone = away(date(2026, 11, 1), date(2026, 12, 31))
    assert check_plan(
        plan(task("A", 8), owners={"A": "Anna"}), [gone], project()
    ).warning_kinds == [("late",), ("away", "Anna")]


def test_on_random_plans_with_absences_nothing_is_planned_into_an_absence():
    # The same seed every time: 200 small plans, two people who are sometimes away.
    rng = random.Random(7)
    for _ in range(200):
        team = []
        for name, hours in (("Anna", 40), ("Ben", 20)):
            absences = []
            if rng.random() < 0.6:
                first = MON + timedelta(days=rng.randrange(10))
                absences.append({"first": first, "last": first + timedelta(days=rng.randrange(4))})
            team.append(Member(name=name, hours_per_week=hours, absences=absences))
        ids = [f"T{n}" for n in range(rng.randrange(3, 7))]
        tasks = [
            task(tid, rng.choice([4, 8, 12, 16]), deps=[d for d in ids[:n] if rng.random() < 0.35])
            for n, tid in enumerate(ids)
        ]
        p = plan(*tasks, owners={tid: rng.choice(["Anna", "Ben"]) for tid in ids})
        result = check_plan(p, team, project())

        assert result.ok
        assert result.critical_path, p
        assert all(days >= 0 for days in result.slack.values())
        # No task is planned on a day its person is away.
        people = {m.name: m for m in team}
        for s in result.schedule:
            for absence in people[s.member].absences:
                assert not absence.first <= s.start <= absence.last, (s, absence)
                assert not absence.first <= s.end <= absence.last, (s, absence)


def test_the_last_task_of_the_chain_can_have_a_day_of_slack_when_days_are_not_full():
    # Found by the random plans. Ben works 4 h a day and is away on Monday 16.11. His D (12 h)
    # starts on Friday afternoon after Anna's C and ends on Thursday at noon. Started a day
    # later it fills Tue, Wed and Thu and ends on the same Thursday.
    ben = Member(
        name="Ben",
        hours_per_week=20,
        absences=[{"first": date(2026, 11, 16), "last": date(2026, 11, 16)}],
    )
    p = plan(
        task("C", 36),  # Anna: Mon to Fri noon
        task("D", 12, deps=["C"]),
        owners={"C": "Anna", "D": "Ben"},
    )
    result = check_plan(p, [ANNA, ben], project())
    assert by_id(result)["D"].end == date(2026, 11, 19)
    assert result.critical_path == ["C", "D"]  # the chain that sets the end
    # And still the plan has a whole day of room: C a day later ends on Monday noon, when
    # Ben is away anyway. The day is shared: either may slip, not both.
    assert result.slack == {"C": 1, "D": 1}


def test_a_task_that_would_slip_into_an_absence_stays_on_the_critical_path():
    # Anna is away on Tuesday and does A on Monday, B on Wednesday, C on Thursday. A day
    # later, A falls into the absence and pushes B and C: it has no slack and sets the end.
    anna = away(date(2026, 11, 10))
    p = plan(
        task("A", 8),
        task("B", 8, deps=["A"]),
        task("C", 8, deps=["B"]),
        owners={"A": "Anna", "B": "Anna", "C": "Anna"},
    )
    result = check_plan(p, [anna], project())
    assert result.slack == {"A": 0, "B": 0, "C": 0}
    assert result.critical_path == ["A", "B", "C"]

    # Ben's A (12 h) ends on Tuesday at noon, Anna does B on Wednesday. A day later, A ends
    # on Wednesday at noon and B has to wait for it.
    q = plan(task("A", 12), task("B", 8, deps=["A"]), owners={"A": "Ben", "B": "Anna"})
    result = check_plan(q, [anna, BEN], project())
    assert result.slack == {"A": 0, "B": 0}
    assert result.critical_path == ["A", "B"]


def test_the_check_can_give_the_dates_alone():
    # The forecast only wants dates. Slack and critical path are the expensive part of the
    # check: both schedule the plan again and again.
    p = plan(task("A", 8), task("B", 8, deps=["A"]), owners={"A": "Anna", "B": "Ben"})
    full = check_plan(p, [ANNA, BEN], project())
    assert full.slack == {"A": 0, "B": 0}
    assert full.critical_path == ["A", "B"]
    assert check_plan(p, [ANNA, BEN], project(), dates_only=True) == full.model_copy(
        update={"slack": {}, "critical_path": []}
    )


def test_the_critical_path_follows_whatever_really_holds_a_task():
    # Anna (away on Tuesday) does her first task on Monday and N on Wednesday. N also waits
    # for Ben's task, done on Monday too. Ben's task a day later changes nothing for N; Anna's
    # first task a day later falls into the absence and moves N. Whatever the IDs are.
    anna = away(date(2026, 11, 10))
    for own, other in [("A", "Z"), ("P", "D")]:
        p = plan(
            task(own, 8),
            task(other, 8),
            task("N", 8, deps=[other]),
            owners={own: "Anna", other: "Ben", "N": "Anna"},
        )
        result = check_plan(p, [anna, BEN], project())
        assert result.slack == {own: 0, other: 1, "N": 0}
        assert result.critical_path == [own, "N"]


def test_whatever_can_start_earliest_is_scheduled_next():
    # Anna has A, B (after A) and C; Ben's D waits for B. After A, both B and C can start:
    # the one listed first goes first. Scheduled level by level (A, C, B), Anna would do C
    # before B and hold Ben up for a day.
    p = plan(
        task("A", 8),
        task("B", 8, deps=["A"]),
        task("C", 8),
        task("D", 8, deps=["B"]),
        owners={"A": "Anna", "B": "Anna", "C": "Anna", "D": "Ben"},
    )
    result = check_plan(p, [ANNA, BEN], project())
    assert result.order == ["A", "B", "C", "D"]
    assert result.end_date == date(2026, 11, 11)
    assert result.slack == {"A": 0, "B": 0, "C": 0, "D": 0}


def test_nobody_waits_for_a_task_while_another_one_could_run():
    # Anna's X waits for Ben's B (three days). Y is listed after X but can start at once.
    p = plan(
        task("B", 24),
        task("X", 8, deps=["B"]),
        task("Y", 16),
        owners={"B": "Ben", "X": "Anna", "Y": "Anna"},
    )
    result = check_plan(p, [ANNA, BEN], project())
    assert result.order == ["B", "Y", "X"]
    assert by_id(result)["Y"].start == MON
    assert by_id(result)["X"].start == date(2026, 11, 12)


def test_slack_keeps_the_sequence_of_the_plan():
    # Anna does X on Monday and Y (three days) after it; Ben's Z (two days) waits for X;
    # Clara's long task ends the plan on Friday. X can slip a day: X on Tuesday, Y until
    # Friday. The question is not what happens if Anna then does Y first: that would be
    # another plan, in which Z ends on Monday.
    clara = Member(name="Clara", hours_per_week=40)
    p = plan(
        task("X", 8),
        task("Y", 24),
        task("Z", 16, deps=["X"]),
        task("L", 40),
        owners={"X": "Anna", "Y": "Anna", "Z": "Ben", "L": "Clara"},
    )
    result = check_plan(p, [ANNA, BEN, clara], project())
    assert result.end_date == date(2026, 11, 13)
    assert result.slack["X"] == 1


def test_planned_work_is_the_hours_done_by_the_end_of_each_workday():
    # Anna is away on Tuesday: A (12 h) takes Monday and Wednesday morning, B the rest of
    # Wednesday and Thursday morning.
    anna = away(date(2026, 11, 10))
    p = plan(task("A", 12), task("B", 8, deps=["A"]), owners={"A": "Anna", "B": "Anna"})
    assert planned_work(p, [anna], project()) == [
        (MON, 8),
        (date(2026, 11, 10), 8),
        (date(2026, 11, 11), 16),
        (date(2026, 11, 12), 20),
    ]
    # A plan with errors has no schedule.
    assert planned_work(plan(task("A", 8), owners={"A": "Zoe"}), [ANNA], project()) == []


def test_on_a_free_day_of_the_project_nobody_works():
    # Tuesday 10.11. is free for everybody. Anna's and Ben's two-day tasks take Monday and
    # Wednesday, and the free day is not counted as time until the deadline.
    free = Project(
        idea="Lernplattform für Erstsemester",
        start_date=MON,
        deadline=date(2026, 11, 13),
        free_days=[{"first": date(2026, 11, 10), "last": date(2026, 11, 10)}],
    )
    p = plan(task("A", 16), task("B", 16), owners={"A": "Anna", "B": "Ben"})
    result = check_plan(p, [ANNA, BEN], free)
    assert [(s.start, s.end) for s in result.schedule] == [(MON, date(2026, 11, 11))] * 2
    assert [item.capacity_hours for item in result.load] == [32, 32]  # four days, not five
    # A person's own absence and a free day add up.
    anna = away(date(2026, 11, 11))
    assert by_id(check_plan(p, [anna, BEN], free))["A"].end == date(2026, 11, 12)


def test_planned_work_stands_still_on_a_free_day_of_the_project():
    free = Project(
        idea="Lernplattform für Erstsemester",
        start_date=MON,
        deadline=date(2026, 11, 13),
        free_days=[{"first": date(2026, 11, 10), "last": date(2026, 11, 10)}],
    )
    p = plan(task("A", 16), owners={"A": "Anna"})
    assert planned_work(p, [ANNA], free) == [
        (MON, 8),
        (date(2026, 11, 10), 8),
        (date(2026, 11, 11), 16),
    ]
