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

from pm_agent.models import CheckResult, Member, MemberLoad, Plan, Project, ScheduledTask

WORKDAYS_PER_WEEK = 5
# Workday offsets are floats. Round before floor/ceil so noise like 0.9999999999999999
# cannot move a date by one day.
_DIGITS = 9


def check_plan(
    plan: Plan,
    team: list[Member],
    project: Project,
    dates_only: bool = False,
) -> CheckResult:
    """Structural errors stop the check. Otherwise the plan is scheduled, and the warnings
    say what the project lead has to decide (deadline, buffer, overload, missing skills).

    `dates_only=True` leaves CheckResult.slack and critical_path empty. Both schedule the
    plan again and again; who only wants the dates saves most of the time."""
    errors = _structural_errors(plan, team, project)
    if errors:
        return CheckResult(errors=errors)

    members = {m.name: m for m in team}
    owner = {a.task_id: a.member for a in plan.assignments}
    away = {m.name: _away(m, project.start_date) for m in team}
    start, end, waits_for, order = _schedule(plan, members, owner, away)
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
    # ponytail: the slack schedules the whole plan a few times per task. 30 tasks take
    # 12 ms, 100 tasks 0.3 s; schedule only from the held-back task on if that matters.
    if not dates_only:
        slack = {
            task.id: _slack(task.id, plan, members, owner, away, order, start, end)
            for task in plan.tasks
        }

    # Critical path: walk back from the task that finishes last along whatever set each start.
    node = None if dates_only else last
    critical_path = []
    while node is not None:
        critical_path.append(node)
        # Which task before it does the task really wait for? The first one, from the
        # latest end on, that moves its start when held back a day. None of them if the
        # task waits for the end of an absence anyway.
        for before in waits_for[node]:
            later = _schedule(plan, members, owner, away, order, (before, 1))[0]
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
        order=order,
        end_date=end_date,
        critical_path=critical_path,
        slack=slack,
        load=load,
    )


def planned_work(plan: Plan, team: list[Member], project: Project) -> list[tuple[date, float]]:
    """The hours of work the plan has done by the end of each workday, from the first day of
    the project to the last day of the plan. From the schedule itself, so a task that begins
    at noon counts with half a day. Empty for a plan check_plan would refuse."""
    if check_plan(plan, team, project, dates_only=True).errors:
        return []
    members = {m.name: m for m in team}
    owner = {a.task_id: a.member for a in plan.assignments}
    away = {m.name: _away(m, project.start_date) for m in team}
    start, end, _, _ = _schedule(plan, members, owner, away)
    last_day = max(_days(start[t.id], end[t.id])[1] for t in plan.tasks)
    done = []
    # ponytail: one step per workday of the plan. A plan that ends in the year 9999 takes
    # seconds; skip the stretches where nobody works if that ever matters.
    for day in range(last_day + 1):
        total = 0.0
        for task in plan.tasks:
            member = owner[task.id]
            until = min(end[task.id], day + 1)
            worked = until - start[task.id]
            if worked <= 0:
                continue
            for first, last in away[member]:  # no task starts or ends inside an absence
                worked -= max(0.0, min(until, last + 1) - max(start[task.id], first))
            total += worked * members[member].hours_per_week / WORKDAYS_PER_WEEK
        done.append((add_workdays(project.start_date, day), round(total, 6)))
    return done


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
    Found by scheduling again in the same sequence (`order`) with the task held back: a
    later start never ends the plan earlier then, so the largest harmless delay can be
    searched by halving. In the same sequence, because the question is what a delay does
    to this plan, not which other plan would be better then."""

    def final(first: dict[str, float], last: dict[str, float]) -> int:
        return max(_days(first[t], last[t])[1] for t in last)

    planned = final(start, end)
    # Held back by more days than the plan has, the task starts after its last day. A tighter
    # bound from the room behind the task is wrong: a delay can fall into the person's absence
    # or into the rest of a day and cost nothing.
    harmless, harmful = 0, planned + 1

    def moves_the_end(days: int) -> bool:
        first, last, _, _ = _schedule(plan, members, owner, away, order, (tid, days))
        return final(first, last) != planned

    # Most tasks have no slack at all: one schedule settles those.
    if moves_the_end(1):
        return 0
    harmless = 1
    while harmful - harmless > 1:
        middle = (harmless + harmful) // 2
        if moves_the_end(middle):
            harmful = middle
        else:
            harmless = middle
    return harmless


def _away(member: Member, start: date) -> list[tuple[int, int]]:
    """The member's absences as ranges of workday offsets (first, last), sorted and merged.
    Ranges, not single days: an absence can be as long as the calendar."""
    day0 = _next_workday(start)
    ranges = []
    for absence in member.absences:
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
    fixed: list[str] | None = None,
    held_back: tuple[str, int] | None = None,
) -> tuple[dict[str, float], dict[str, float], dict[str, list[str]], list[str]]:
    """Start and end of each task in workday offsets; the tasks it could start after (its
    dependencies and the member's previous task, the one that ends last first); and the
    order in which the tasks were scheduled.

    Of the tasks whose dependencies are scheduled, the one that can start earliest goes
    next; of two that can start at the same time, the one listed first in the plan. So
    nobody waits for a task while another of their tasks could run. Whether a task really
    waited for one of the tasks before it or for the end of an absence decides check_plan.

    `fixed` schedules the tasks in this sequence instead: the one a first run returned.
    `held_back` makes one task start that many workdays later than it could. Together they
    answer what a delay does to the plan as it stands."""
    # ponytail: a dispatch rule, not an optimal schedule. It never looks ahead, so a short
    # task can go before the one a long chain waits for. Upgrade to a priority by the work
    # behind a task if plans come out visibly too long.
    tasks = {t.id: t for t in plan.tasks}
    free_at: dict[str, tuple[float, str]] = {}  # member -> (offset, task that ends there)
    start: dict[str, float] = {}
    end: dict[str, float] = {}
    waits_for: dict[str, list[str]] = {}
    order: list[str] = []

    def option(tid: str) -> tuple[float, float, list[tuple[float, str]]]:
        """When the task would run if it were scheduled now, and what it would wait for."""
        task, member = tasks[tid], owner[tid]
        candidates = [(end[dep], dep) for dep in task.depends_on]
        if member in free_at:
            candidates.append(free_at[member])
        earliest = max(candidates, default=(0.0, None))[0]
        daily_hours = members[member].hours_per_week / WORKDAYS_PER_WEEK
        first, last = _work(earliest, task.estimate_hours, daily_hours, away[member])
        if held_back and held_back[0] == tid:
            # Later than its real start. Counted from `earliest`, a task that waits for the
            # end of an absence anyway would seem free to slip for as long as that lasts.
            first, last = _work(
                first + held_back[1], task.estimate_hours, daily_hours, away[member]
            )
        return first, last, candidates

    def place(tid: str, first: float, last: float, candidates: list[tuple[float, str]]) -> None:
        start[tid], end[tid] = first, last
        waits_for[tid] = list(dict.fromkeys(c for _, c in sorted(candidates, reverse=True)))
        free_at[owner[tid]] = (last, tid)
        order.append(tid)

    if fixed:
        for tid in fixed:
            place(tid, *option(tid))
        return start, end, waits_for, order

    position = {t.id: number for number, t in enumerate(plan.tasks)}
    open_deps = {t.id: set(t.depends_on) for t in plan.tasks}
    followers: dict[str, list[str]] = {t.id: [] for t in plan.tasks}
    for t in plan.tasks:
        for dep in open_deps[t.id]:
            followers[dep].append(t.id)

    def key(tid: str) -> tuple[float, int]:
        return round(options[tid][0], _DIGITS), position[tid]

    # The tasks whose dependencies are scheduled. An option changes only when its person
    # gets another task, so only those are computed again.
    options = {t.id: option(t.id) for t in plan.tasks if not t.depends_on}
    while options:
        tid = min(options, key=key)
        place(tid, *options.pop(tid))
        for other in options:
            if owner[other] == owner[tid]:
                options[other] = option(other)
        for follower in followers[tid]:
            open_deps[follower].remove(tid)
            if not open_deps[follower]:
                options[follower] = option(follower)
    return start, end, waits_for, order


def _topo_order(plan: Plan) -> list[str]:
    return list(TopologicalSorter({t.id: t.depends_on for t in plan.tasks}).static_order())


def _duplicates(items: list[str]) -> list[str]:
    return [item for item, n in Counter(items).items() if n > 1]


def _fmt(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _hours(value: float) -> str:
    return f"{round(value, 1):g}"
