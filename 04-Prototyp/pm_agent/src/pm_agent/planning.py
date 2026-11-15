"""Deterministic plan check and scheduling. No LLM in here: the agent proposes, this code
verifies, so dates, loads and the critical path are exact and unit-tested.

Time model: workdays Mon-Fri, no holidays. A member works hours_per_week / 5 hours per
workday, on one task at a time, and not at all on the days of their absences. Workday 0 is the
first Mon-Fri on or after the start date.
"""

import math
from collections import Counter
from datetime import date, timedelta
from graphlib import CycleError, TopologicalSorter

from pm_agent.models import (
    Absence,
    CheckResult,
    Member,
    MemberLoad,
    Plan,
    Project,
    ScheduledTask,
)

WORKDAYS_PER_WEEK = 5
# Workday offsets are floats. Round before floor/ceil so noise like 0.9999999999999999
# cannot move a date by one day.
_DIGITS = 9


def check_plan(
    plan: Plan,
    team: list[Member],
    project: Project,
    order: list[str] | None = None,
    with_slack: bool = True,
) -> CheckResult:
    """Structural errors stop the check. Otherwise the plan is scheduled, and the warnings
    say what the project lead has to decide (deadline, buffer, overload, missing skills).

    `order` schedules the tasks in this order instead of scheduling_order(plan). It has to
    name every task once, each after the tasks it depends on (ValueError otherwise). The
    forecast uses it to keep the order of the plan when finished tasks have dropped out.

    `with_slack=False` leaves CheckResult.slack empty. The slack schedules the plan again
    several times per task; who only wants the dates saves most of the time."""
    errors = _structural_errors(plan, team, project)
    if errors:
        return CheckResult(errors=errors)
    if order is None:
        order = scheduling_order(plan)
    else:
        position = {tid: number for number, tid in enumerate(order)}
        complete = sorted(order) == sorted(task.id for task in plan.tasks)
        if not complete or any(
            position[dep] > position[task.id] for task in plan.tasks for dep in task.depends_on
        ):
            raise ValueError("order must name every task once, after the tasks it depends on")

    members = {m.name: m for m in team}
    owner = {a.task_id: a.member for a in plan.assignments}
    # A free day of the project is an absence of everybody.
    away = {m.name: _away([*m.absences, *project.free_days], project.start_date) for m in team}
    start, end, waits_for = _schedule(plan, members, owner, away, order)
    last = max(plan.tasks, key=lambda t: end[t.id]).id
    # Dates end on 31.12.9999. Written as "not <=" so that an infinite offset fails too.
    if not end[last] <= count_workdays(project.start_date, date.max):
        return CheckResult(
            errors=[
                f"Task '{last}' würde erst nach dem {_fmt(date.max)} enden, "
                "so weit reicht der Kalender nicht"
            ]
        )

    schedule = []
    for task in plan.tasks:
        first_day, last_day = _days(start[task.id], end[task.id])
        schedule.append(
            ScheduledTask(
                task_id=task.id,
                member=owner[task.id],
                start=add_workdays(project.start_date, first_day),
                end=add_workdays(project.start_date, last_day),
            )
        )
    end_date = max(s.end for s in schedule)
    slack = {}
    if with_slack:
        slack = {
            task.id: _slack(task.id, plan, members, owner, away, order, start, end)
            for task in plan.tasks
        }

    # Critical path: walk back from the task that finishes last along whatever set each start.
    node = last
    critical_path = []
    while node is not None:
        critical_path.append(node)
        # Which task before it does the task really wait for? The first one, from the
        # latest end on, that moves its start when held back a day. None of them if the
        # task waits for the end of an absence anyway.
        for before in waits_for[node]:
            later, _, _ = _schedule(plan, members, owner, away, order, held_back=(before, 1))
            if round(later[node] - start[node], _DIGITS) != 0:
                node = before
                break
        else:
            node = None
    critical_path.reverse()

    window = count_workdays(project.start_date, project.deadline)
    assigned = Counter()
    for task in plan.tasks:
        assigned[owner[task.id]] += task.estimate_hours
    load = []
    for member in team:
        # Workdays 0 to window - 1 lie before the deadline; the absent ones do not count.
        absent = sum(max(0, min(last, window - 1) - first + 1) for first, last in away[member.name])
        capacity = member.hours_per_week / WORKDAYS_PER_WEEK * (window - absent)
        load.append(
            MemberLoad(
                member=member.name,
                assigned_hours=assigned[member.name],
                capacity_hours=capacity,
                utilization=assigned[member.name] / capacity if capacity else None,
            )
        )

    warnings, kinds = [], []

    def warn(kind: tuple[str, ...], text: str) -> None:
        kinds.append(kind)
        warnings.append(text)

    if end_date > project.deadline:
        late = count_workdays(project.deadline + timedelta(days=1), end_date)
        warn(
            ("late",),
            f"Der Plan endet am {_fmt(end_date)}, {late} Arbeitstag{'' if late == 1 else 'e'} "
            f"nach der Deadline ({_fmt(project.deadline)})",
        )
    # end_date is a workday, so one workday in [end_date, deadline] is end_date itself: any
    # delay misses the deadline. Counted from end_date, not the day after, which does not
    # exist for 31.12.9999.
    elif count_workdays(end_date, project.deadline) == 1:
        warn(
            ("buffer",),
            f"Der Plan endet am {_fmt(end_date)}, bis zur Deadline ({_fmt(project.deadline)}) "
            "bleibt kein Arbeitstag Puffer",
        )
    for item in load:
        if item.utilization is None:
            if item.assigned_hours:
                warn(
                    ("away", item.member),
                    f"{item.member} ist bis zur Deadline durchgehend abwesend, hat aber "
                    f"{_hours(item.assigned_hours)} h zugewiesen",
                )
        elif round(item.utilization, _DIGITS) > 1:
            percent = math.ceil(round(item.utilization * 100, _DIGITS))  # never reads "100%"
            warn(
                ("overload", item.member),
                f"{item.member} ist überlastet: {_hours(item.assigned_hours)} h zugewiesen, "
                f"bis zur Deadline sind {_hours(item.capacity_hours)} h verfügbar ({percent}%)",
            )
    for task in plan.tasks:
        member = members[owner[task.id]]
        known = {skill.casefold() for skill in member.skills}
        for skill in task.required_skills:
            if skill.casefold() not in known:
                warn(
                    ("skill", task.id, skill),
                    f"Task '{task.id}' braucht '{skill}', "
                    f"{member.name} hat diese Fähigkeit nicht angegeben",
                )

    return CheckResult(
        warnings=warnings,
        warning_kinds=kinds,
        schedule=schedule,
        end_date=end_date,
        critical_path=critical_path,
        slack=slack,
        load=load,
    )


def add_workdays(start: date, n: int) -> date:
    """Date of workday n, where workday 0 is the first Mon-Fri on or after start."""
    day = _next_workday(start)
    weeks, weekday = divmod(day.weekday() + n, WORKDAYS_PER_WEEK)
    return day + timedelta(weeks=weeks, days=weekday - day.weekday())


def count_workdays(first: date, last: date) -> int:
    """Number of Mon-Fri dates in [first, last]; 0 if last is before first."""
    weeks, rest = divmod(max((last - first).days + 1, 0), 7)
    return weeks * WORKDAYS_PER_WEEK + sum((first.weekday() + i) % 7 < 5 for i in range(rest))


def workday_shift(before: date, after: date) -> int:
    """How many workdays `after` lies behind `before`; negative if it lies ahead of it."""
    if after >= before:
        return count_workdays(before + timedelta(days=1), after)
    return -count_workdays(after + timedelta(days=1), before)


def _next_workday(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def _structural_errors(plan: Plan, team: list[Member], project: Project) -> list[str]:
    errors = []
    if count_workdays(project.start_date, project.deadline) == 0:
        errors.append(
            f"Zwischen Start ({_fmt(project.start_date)}) und Deadline "
            f"({_fmt(project.deadline)}) liegt kein Arbeitstag"
        )

    names = [m.name for m in team]
    if not names:
        errors.append("Das Team ist leer")
    errors += [f"Der Name '{name}' kommt im Team mehrfach vor" for name in _duplicates(names)]

    task_ids = [t.id for t in plan.tasks]
    duplicate_ids = _duplicates(task_ids)
    errors += [f"Die Task-ID '{tid}' ist mehrfach vergeben" for tid in duplicate_ids]

    known_ids, known_names = set(task_ids), set(names)
    for task in plan.tasks:
        errors += [
            f"Task '{task.id}' hängt von der unbekannten Task '{dep}' ab"
            for dep in task.depends_on
            if dep not in known_ids
        ]
    for a in plan.assignments:
        if a.task_id not in known_ids:
            errors.append(f"Zuweisung für die unbekannte Task '{a.task_id}'")
        if a.member not in known_names:
            errors.append(
                f"Task '{a.task_id}' ist '{a.member}' zugewiesen, diese Person ist nicht im Team"
            )

    assignment_count = Counter(a.task_id for a in plan.assignments)
    for tid in dict.fromkeys(task_ids):
        if assignment_count[tid] == 0:
            errors.append(f"Task '{tid}' ist niemandem zugewiesen")
        elif assignment_count[tid] > 1:
            errors.append(f"Task '{tid}' ist mehrfach zugewiesen")

    if not duplicate_ids:  # with duplicate ids the dependency graph is ambiguous
        try:
            _topo_order(plan)
        except CycleError as cycle:
            errors.append("Zyklische Abhängigkeit: " + " → ".join(cycle.args[1]))
    return errors


def _days(start: float, end: float) -> tuple[int, int]:
    """The first and the last workday a task with these offsets touches."""
    first = math.floor(round(start, _DIGITS))
    return first, max(math.ceil(round(end, _DIGITS)) - 1, first)


def _slack(
    tid: str,
    plan: Plan,
    members: dict[str, Member],
    owner: dict[str, str],
    away: dict[str, list[tuple[int, int]]],
    order: list[str],
    start: dict[str, float],
    end: dict[str, float],
) -> int:
    """Whole workdays task `tid` can start later before the last day of the plan moves.
    Found by scheduling again with the task held back: a later start never ends the plan
    earlier, so the largest harmless delay can be searched by halving."""

    def final(first: dict[str, float], last: dict[str, float]) -> int:
        return max(_days(first[t], last[t])[1] for t in last)

    planned = final(start, end)
    # Held back by more days than the plan has, the task starts after its last day. A tighter
    # bound from the room behind the task is wrong: a delay can fall into the person's absence
    # or into the rest of a day and cost nothing.
    harmless, harmful = 0, planned + 1
    while harmful - harmless > 1:
        middle = (harmless + harmful) // 2
        first, last, _ = _schedule(plan, members, owner, away, order, held_back=(tid, middle))
        if final(first, last) == planned:
            harmless = middle
        else:
            harmful = middle
    return harmless


def _away(absences: list[Absence], start: date) -> list[tuple[int, int]]:
    """Absences as ranges of workday offsets (first, last), sorted and merged.
    Ranges, not single days: an absence can be as long as the calendar."""
    day0 = _next_workday(start)
    ranges = []
    for absence in absences:
        first = (
            0 if absence.first <= day0 else count_workdays(day0, absence.first - timedelta(days=1))
        )
        last = count_workdays(day0, absence.last) - 1
        if last >= first:  # otherwise no workday of the project lies in it
            ranges.append((first, last))
    merged: list[tuple[int, int]] = []
    for first, last in sorted(ranges):
        if merged and first <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))
    return merged


def _work(
    earliest: float, hours: float, daily_hours: float, away: list[tuple[int, int]]
) -> tuple[float, float]:
    """When `hours` of work that may begin at offset `earliest` really begin and end, with
    the workdays in `away` left out. Without absences this is earliest + hours / daily_hours."""
    at, begin, left = earliest, None, hours
    for first, last in away:
        day = round(at, _DIGITS)
        if day >= last + 1:
            continue  # this absence is over
        if day >= first:
            at = float(last + 1)  # in the middle of it: wait for its end
            continue
        room = (first - at) * daily_hours
        begin = at if begin is None else begin
        if round(left - room, _DIGITS) <= 0:
            return begin, at + left / daily_hours
        left -= room
        at = float(last + 1)
    return (at if begin is None else begin), at + left / daily_hours


def _schedule(
    plan: Plan,
    members: dict[str, Member],
    owner: dict[str, str],
    away: dict[str, list[tuple[int, int]]],
    order: list[str],
    held_back: tuple[str, int] | None = None,
) -> tuple[dict[str, float], dict[str, float], dict[str, list[str]]]:
    """Start and end of each task in workday offsets, plus the tasks it could start after:
    its dependencies and the member's previous task, the one that ends last first. Whether
    the task really waited for one of them or for the end of an absence decides check_plan.
    `held_back` makes one task start that many workdays later than it does, to see what
    that does."""
    # ponytail: greedy list scheduling in dependency order, not an optimal schedule. A member
    # can sit idle waiting for a dependency while another of their tasks could already run.
    # Upgrade to priority by remaining critical path if plans come out visibly too long.
    tasks = {t.id: t for t in plan.tasks}
    free_at: dict[str, tuple[float, str]] = {}  # member -> (offset, task that ends there)
    start: dict[str, float] = {}
    end: dict[str, float] = {}
    waits_for: dict[str, list[str]] = {}
    for tid in order:
        task, member = tasks[tid], owner[tid]
        candidates = [(end[dep], dep) for dep in task.depends_on]
        if member in free_at:
            candidates.append(free_at[member])
        earliest = max(candidates, default=(0.0, None))[0]
        waits_for[tid] = list(dict.fromkeys(c for _, c in sorted(candidates, reverse=True)))
        daily_hours = members[member].hours_per_week / WORKDAYS_PER_WEEK
        start[tid], end[tid] = _work(earliest, task.estimate_hours, daily_hours, away[member])
        if held_back and held_back[0] == tid:
            # Later than its real start. Counted from `earliest`, a task that waits for the
            # end of an absence anyway would seem free to slip for as long as that lasts.
            start[tid], end[tid] = _work(
                start[tid] + held_back[1], task.estimate_hours, daily_hours, away[member]
            )
        free_at[member] = (end[tid], tid)
    return start, end, waits_for


def scheduling_order(plan: Plan) -> list[str]:
    """The order in which check_plan schedules the tasks: every task after the tasks it
    depends on. For a plan with a cycle this raises graphlib.CycleError; check_plan reports
    that as an error before it gets here."""
    return _topo_order(plan)


def _topo_order(plan: Plan) -> list[str]:
    return list(TopologicalSorter({t.id: t.depends_on for t in plan.tasks}).static_order())


def _duplicates(items: list[str]) -> list[str]:
    return [item for item, n in Counter(items).items() if n > 1]


def _fmt(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _hours(value: float) -> str:
    return f"{round(value, 1):g}"
