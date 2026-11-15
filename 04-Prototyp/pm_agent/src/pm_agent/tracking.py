"""Execution and control of an adopted plan: the baseline, the progress the project lead
records, the plan/actual comparison and the documents filled from both.

No Streamlit and no LLM in here. Every number comes from the adopted plan and the recorded
progress. The file lives in data/ like the team file: it holds personal data and is git-ignored.
"""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from string import Template
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pm_agent.agent import LOG_DIR
from pm_agent.models import (
    ControlReport,
    Member,
    Plan,
    Project,
    ScheduledTask,
    StatusSummary,
    Task,
)
from pm_agent.planning import (
    WORKDAYS_PER_WEEK,
    add_workdays,
    check_plan,
    count_workdays,
    workday_shift,
)
from pm_agent.workbench import DATA_DIR, InputError, _cell, _date, _md, _reason, bar_end

PROJECT_FILE = DATA_DIR / "projekt.json"
TEMPLATES = Path(__file__).parent / "templates"

Status = Literal["offen", "in Arbeit", "fertig"]
STATUSES = list(get_args(Status))
# Log file prefix of each agent (agent.run_agent) and its name in the UI.
AGENTS = {"run": "Planung", "durchfuehrung": "Durchführung", "kontrolle": "Kontrolle"}
PROGRESS_COLUMNS = [
    "ID",
    "Aufgabe",
    "Person",
    "Plan (h)",
    "Geplantes Ende",
    "Prognose Ende",
    "Status",
    "Ist (h)",
    "Rest (h)",
    "Notiz",
]


class Progress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status = "offen"
    actual_hours: float = Field(default=0, ge=0, allow_inf_nan=False)
    # What the project lead expects is still to do. None: not said; the forecast then takes
    # the estimate, less the booked hours for a started task.
    remaining_hours: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    note: str = ""


class Tracking(BaseModel):
    """The plan the project lead adopted, and what happened to each task since."""

    model_config = ConfigDict(extra="forbid")

    adopted: datetime
    project: Project
    team: list[Member]
    plan: Plan
    progress: dict[str, Progress]


@dataclass(frozen=True)
class TaskState:
    id: str
    title: str
    member: str
    planned_hours: float
    planned_start: date
    planned_end: date
    status: str
    actual_hours: float
    remaining_hours: float | None  # the project lead's own estimate of what is left
    note: str
    overdue: bool  # planned end is past and the task is not finished


@dataclass(frozen=True)
class Evaluation:
    today: date
    tasks: list[TaskState]
    planned_hours: float
    actual_hours: float
    progress: float  # planned hours of finished tasks / all planned hours
    finished_deviation: float  # actual - planned, finished tasks only
    by_member: list[dict[str, Any]]

    @property
    def overdue(self) -> list[TaskState]:
        return [t for t in self.tasks if t.overdue]


def adopt(project: Project, team: list[Member], plan: Plan, path: Path | None = None) -> Tracking:
    """Make the plan the baseline. Replaces an adopted project and its progress."""
    errors = check_plan(plan, team, project).errors
    if errors:
        raise InputError("Der Plan hat noch Fehler: " + "; ".join(errors))
    tracking = Tracking(
        adopted=datetime.now().astimezone().replace(microsecond=0),
        project=project,
        team=team,
        plan=plan,
        progress={t.id: Progress() for t in plan.tasks},
    )
    save(tracking, path)
    return tracking


def load(path: Path | None = None) -> Tracking | None:
    """None if no plan was adopted yet. A damaged file is an error, not an empty project."""
    path = path or PROJECT_FILE
    if not path.exists():
        return None
    try:
        return Tracking.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, ValidationError) as err:
        raise InputError(f"{path.name} ist beschädigt: {_reason(err)}") from err


def save(tracking: Tracking, path: Path | None = None) -> None:
    path = path or PROJECT_FILE  # read at call time: tests point it to a temporary folder
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tracking.model_dump_json(indent=2), encoding="utf-8")


def percent(share: float) -> str:
    """0.333 -> "33 %", the German way."""
    return f"{share:.0%}".replace("%", " %")


def euro(amount: float) -> str:
    """1600 -> "1.600,00 €", the German way."""
    return f"{amount:,.2f} €".translate(str.maketrans(",.", ".,"))


def has_progress(tracking: Tracking) -> bool:
    return any(p != Progress() for p in tracking.progress.values())


def apply_rows(tracking: Tracking, rows: list[dict[str, Any]]) -> Tracking:
    """The progress table as the project lead edited it. Tasks without a row keep their state."""
    progress = dict(tracking.progress)
    for number, row in enumerate(rows, start=1):
        task_id = _cell(row.get("ID"))
        where = f"Zeile {number} ({task_id})"
        if task_id not in progress:
            raise InputError(f"{where}: Aufgabe nicht im Plan")
        status = _cell(row.get("Status")) or "offen"
        if status not in STATUSES:
            raise InputError(
                f"{where}: Status '{status}' unbekannt, erlaubt: {', '.join(STATUSES)}"
            )
        try:
            hours = float(_cell(row.get("Ist (h)")) or 0)
        except ValueError:
            hours = math.nan
        if not 0 <= hours < math.inf:  # also false for NaN
            raise InputError(f"{where}: Ist-Stunden müssen eine Zahl ab 0 sein")
        left = _cell(row.get("Rest (h)"))
        try:
            rest = float(left) if left else None
        except ValueError:
            rest = math.nan
        if rest is not None and not 0 <= rest < math.inf:
            raise InputError(f"{where}: Rest-Stunden müssen eine Zahl ab 0 sein")
        if status == "fertig":
            rest = None  # nothing is left of a finished task
        elif rest == 0:
            raise InputError(
                f"{where}: Rest 0 h, aber Status '{status}'. Setze den Status auf fertig "
                "oder trage ein, was noch zu tun ist"
            )
        progress[task_id] = Progress(
            status=status, actual_hours=hours, remaining_hours=rest, note=_cell(row.get("Notiz"))
        )
    return tracking.model_copy(update={"progress": progress})


def evaluate(tracking: Tracking, today: date) -> Evaluation:
    schedule = check_plan(tracking.plan, tracking.team, tracking.project, dates_only=True).schedule
    dates = {s.task_id: s for s in schedule}
    tasks = []
    for task in tracking.plan.tasks:
        planned, done = dates[task.id], tracking.progress[task.id]
        tasks.append(
            TaskState(
                id=task.id,
                title=task.title,
                member=planned.member,
                planned_hours=task.estimate_hours,
                planned_start=planned.start,
                planned_end=planned.end,
                status=done.status,
                actual_hours=done.actual_hours,
                remaining_hours=done.remaining_hours,
                note=done.note,
                overdue=planned.end < today and done.status != "fertig",
            )
        )
    finished = [t for t in tasks if t.status == "fertig"]
    planned_hours = sum(t.planned_hours for t in tasks)
    return Evaluation(
        today=today,
        tasks=tasks,
        planned_hours=planned_hours,
        actual_hours=sum(t.actual_hours for t in tasks),
        progress=sum(t.planned_hours for t in finished) / planned_hours,
        finished_deviation=sum(t.actual_hours - t.planned_hours for t in finished),
        by_member=[
            {
                "Person": member,
                "Plan (h)": sum(t.planned_hours for t in tasks if t.member == member),
                "Ist (h)": sum(t.actual_hours for t in tasks if t.member == member),
                "Fertig (Plan-h)": sum(t.planned_hours for t in finished if t.member == member),
            }
            for member in dict.fromkeys(t.member for t in tasks)
        ],
    )


@dataclass(frozen=True)
class EarnedValue:
    """Earned value analysis in hours, by the 0/100 rule: a task earns its planned hours when
    it is finished, and nothing before."""

    planned: float  # PV: what the plan wanted done by the end of today
    earned: float  # EV: planned hours of the finished tasks
    actual: float  # AC: hours booked so far, on all tasks

    @property
    def schedule_index(self) -> float | None:
        """SPI: below 1 the project is behind the plan. None before the plan's first day."""
        return self.earned / self.planned if self.planned else None

    @property
    def cost_index(self) -> float | None:
        """CPI: below 1 the work takes more hours than planned. None without booked hours."""
        return self.earned / self.actual if self.actual else None


def planned_curve(tracking: Tracking, evaluation: Evaluation) -> list[dict[str, Any]]:
    """The planned value over the plan: the hours the plan wanted done by the end of a
    workday. Only the days where the curve bends, and the first and the last one.

    Each person works their daily hours on their tasks in planned order, a task not before
    its planned start and not while the person is away. That is the plan day by day; spread
    evenly over a task's days, hours would count on days the plan gives to another task or
    to an absence."""
    people = {member.name: member for member in tracking.team}
    queue: dict[str, list[TaskState]] = {}
    for task in sorted(evaluation.tasks, key=lambda t: t.planned_start):  # stable
        queue.setdefault(task.member, []).append(task)
    left = {task.id: task.planned_hours for task in evaluation.tasks}
    first = min(t.planned_start for t in evaluation.tasks)
    last = max(t.planned_end for t in evaluation.tasks)
    total, values = 0.0, []
    # ponytail: one step per workday of the plan. A plan that ends in the year 9999 takes
    # seconds; skip the stretches where nobody works if that ever matters.
    for number in range(count_workdays(first, last)):
        day = add_workdays(first, number)
        for name, tasks in queue.items():
            if any(a.first <= day <= a.last for a in people[name].absences):
                continue
            budget = people[name].hours_per_week / WORKDAYS_PER_WEEK
            for task in tasks:
                if task.planned_start <= day and left[task.id] > 0:
                    done = min(budget, left[task.id])
                    left[task.id] -= done
                    budget -= done
                    total += done
        for task in evaluation.tasks:
            # The plan has the task done on its last day, whatever the walk above made of
            # a day shared with other tasks.
            if task.planned_end <= day and left[task.id] > 0:
                total += left[task.id]
                left[task.id] = 0.0
        values.append((day, round(total, 6)))
    return [
        {"Tag": day, "Stunden": hours}
        for number, (day, hours) in enumerate(values)
        if number in (0, len(values) - 1)
        or hours != values[number - 1][1]
        or hours != values[number + 1][1]
    ]


def earned_value(tracking: Tracking, evaluation: Evaluation) -> EarnedValue:
    reached = [
        point["Stunden"]
        for point in planned_curve(tracking, evaluation)
        if point["Tag"] <= evaluation.today
    ]
    return EarnedValue(
        # Between two kept days the curve is flat or the later day is kept too.
        planned=reached[-1] if reached else 0.0,
        earned=sum(t.planned_hours for t in evaluation.tasks if t.status == "fertig"),
        actual=evaluation.actual_hours,
    )


def hours_text(value: float) -> str:
    """Hours with at most one decimal, the German way: 41.6 -> "41,6", 8.0 -> "8"."""
    # "+ 0.0" turns a rounded -0.0 into 0.0.
    return f"{round(value, 1) + 0.0:.1f}".removesuffix(".0").replace(".", ",")


def index_text(value: float | None, missing: str) -> str:
    """An index of the earned value analysis, the German way: 0.5 -> "0,50"."""
    return missing if value is None else f"{value:.2f}".replace(".", ",")


NO_SCHEDULE_INDEX = "nicht berechenbar, der Plan hat noch nicht begonnen"
NO_COST_INDEX = "nicht berechenbar, keine Ist-Stunden erfasst"


# When the booked hours reach the estimate and the project lead has entered no remaining
# estimate (Progress.remaining_hours), nobody knows what is left. One hour keeps the task in
# the forecast.
MIN_REST_HOURS = 1.0


@dataclass(frozen=True)
class Forecast:
    """Where the project ends if the remaining work starts today."""

    planned_end: date
    end: date | None  # None: every task is finished
    shift: int  # workdays the end lies behind the planned end; negative: ahead of it
    deadline_gap: int  # workdays the end lies behind the deadline; negative: buffer left
    blocked: dict[str, list[str]]  # overdue task -> unfinished tasks that wait for it
    # The forecast dates of the unfinished tasks, in the order they are worked on.
    schedule: list[ScheduledTask]
    # Why there is no forecast although tasks are unfinished: what is left does not fit
    # the calendar, or cannot be scheduled as asked. `end` is None then as well.
    problem: str | None = None


def rest_plan(tracking: Tracking, reassign: dict[str, str] | None = None) -> Plan | None:
    """The unfinished tasks as a plan of their own; None if every task is finished.

    A task counts with what the project lead says is left of it. Without that, an open task
    counts with its full estimate and a started one with the estimate minus the booked
    hours. Dependencies on finished tasks are gone. `reassign` (task ID -> member) gives
    tasks to someone else."""
    state = tracking.progress

    def left(task: Task) -> float:
        done = state[task.id]
        if done.remaining_hours is not None:
            return done.remaining_hours
        if done.status == "in Arbeit":
            left = round(task.estimate_hours - done.actual_hours, 6)
            # Only when nothing is left by the numbers. A rest under an hour is a rest;
            # and never more than the task itself, if that is shorter than the hour.
            return left if left > 0 else min(MIN_REST_HOURS, task.estimate_hours)
        return task.estimate_hours

    open_ids = {task.id for task in tracking.plan.tasks if state[task.id].status != "fertig"}
    if not open_ids:
        return None
    return Plan(
        tasks=[
            task.model_copy(
                update={
                    "estimate_hours": left(task),
                    "depends_on": [dep for dep in task.depends_on if dep in open_ids],
                }
            )
            # What is started comes first: of two tasks a person could begin with at the
            # same time, the one in progress goes on. (sorted is stable: otherwise the
            # order of the plan.) Not more than that: a begun task that still waits for
            # another one does not hold back what can start now.
            for task in sorted(tracking.plan.tasks, key=lambda t: state[t.id].status != "in Arbeit")
            if task.id in open_ids
        ],
        assignments=[
            a.model_copy(update={"member": (reassign or {}).get(a.task_id, a.member)})
            for a in tracking.plan.assignments
            if a.task_id in open_ids
        ],
        risks=tracking.plan.risks,
    )


def rest_project(tracking: Tracking, today: date) -> tuple[Project, Plan]:
    """What is left of the adopted project as a project of its own, to plan it again: it
    starts today and keeps the deadline. Raises InputError if there is nothing to plan."""
    rest = rest_plan(tracking)
    project = tracking.project
    if rest is None:
        raise InputError("Alle Aufgaben sind fertig: Es gibt nichts umzuplanen")
    if today > project.deadline:
        raise InputError(
            f"Die Deadline ({_date(project.deadline)}) liegt in der Vergangenheit: Bis dahin "
            "lässt sich nichts mehr planen"
        )
    start = max(today, project.start_date)
    return Project(idea=project.idea, start_date=start, deadline=project.deadline), rest


def forecast(tracking: Tracking, today: date, reassign: dict[str, str] | None = None) -> Forecast:
    """Schedule what is not finished (rest_plan) from today on and compare it with the plan.
    The same scheduling as for the plan itself (planning.check_plan), so both ends are
    comparable.

    `reassign` (task ID -> member) answers "what if": the forecast with these unfinished tasks
    given to someone else. The names must be team members."""
    project, plan = tracking.project, tracking.plan
    planned_end = check_plan(plan, tracking.team, project, dates_only=True).end_date
    rest = rest_plan(tracking, reassign)
    if rest is None:
        return Forecast(
            planned_end=planned_end, end=None, shift=0, deadline_gap=0, blocked={}, schedule=[]
        )
    # The last possible date as deadline: only the dates are wanted here. Today can lie
    # behind the real deadline, and check_plan would then find no workday to plan in.
    open_end = Project(
        idea=project.idea, start_date=max(today, project.start_date), deadline=date.max
    )
    # Scheduled like any plan: the Planung says the same about the rest when it is
    # loaded there ("Rest mit Claude umplanen").
    expected = check_plan(rest, tracking.team, open_end, dates_only=True)
    if expected.errors:
        return Forecast(
            planned_end=planned_end,
            end=None,
            shift=0,
            deadline_gap=0,
            blocked={},
            schedule=[],
            problem="; ".join(expected.errors),
        )
    end = expected.end_date

    # In the order of the plan; the rest lists what is begun first.
    left = {task.id for task in rest.tasks}
    unfinished = [task for task in plan.tasks if task.id in left]
    waiting: dict[str, list[str]] = {}
    for late in evaluate(tracking, today).overdue:
        reached, queue = [], [late.id]
        while queue:
            current = queue.pop(0)
            for task in unfinished:
                if current in task.depends_on and task.id not in reached:
                    reached.append(task.id)
                    queue.append(task.id)
        waiting[late.id] = [task.id for task in unfinished if task.id in reached]
    return Forecast(
        planned_end=planned_end,
        end=end,
        shift=workday_shift(planned_end, end),
        deadline_gap=workday_shift(project.deadline, end),
        blocked=waiting,
        schedule=sorted(expected.schedule, key=lambda s: expected.order.index(s.task_id)),
    )


NOTHING_LEFT = "Alle Aufgaben sind fertig: Es steht nichts mehr an."
NOTHING_AHEAD = "In den nächsten fünf Arbeitstagen beginnt laut Prognose keine Aufgabe."
NO_WEEK_AHEAD = "Ohne Prognose lässt sich nicht sagen, was ansteht."


def week_ahead(tracking: Tracking, today: date, days: int = 5) -> list[dict[str, Any]]:
    """Who does what next: the unfinished tasks the forecast starts within the next `days`
    workdays (today counts), by person and start. Empty if nothing is left or the forecast
    has a problem; forecast() says which."""
    horizon = add_workdays(today, days - 1)
    titles = {task.id: task.title for task in tracking.plan.tasks}
    ahead = [s for s in forecast(tracking, today).schedule if s.start <= horizon]
    return [
        {
            "Person": s.member,
            "ID": s.task_id,
            "Aufgabe": titles[s.task_id],
            "Beginn": _date(s.start),
            "Ende": _date(s.end),
            "Status": tracking.progress[s.task_id].status,
        }
        # Stable: two tasks of one person on the same day stay in the order they are
        # worked on, which is the order of the forecast's schedule.
        for s in sorted(ahead, key=lambda s: (s.member, s.start))
    ]


def reassignment_effect(tracking: Tracking, today: date, task_ids: list[str], member: str) -> str:
    """What giving these tasks to `member` does to the forecast, as one sentence. Finished
    tasks stay where they are."""
    people = {m.name: m for m in tracking.team}
    if member not in people:
        return f"Nicht prüfbar: {member} ist nicht im Team"
    tasks = {task.id: task for task in tracking.plan.tasks}
    unknown = [tid for tid in task_ids if tid not in tasks]
    if unknown:
        noun = "Aufgabe" if len(unknown) == 1 else "Aufgaben"
        verb = "ist" if len(unknown) == 1 else "sind"
        return f"Nicht prüfbar: {noun} {', '.join(unknown)} {verb} nicht im Plan"
    moved = [tid for tid in task_ids if tracking.progress[tid].status != "fertig"]
    before = forecast(tracking, today)
    if before.problem:
        return f"Nicht prüfbar: {before.problem}"
    if before.end is None:
        return "Alle Aufgaben sind fertig."
    after = forecast(tracking, today, reassign=dict.fromkeys(moved, member))
    if after.problem:
        return f"Nicht prüfbar: {after.problem}"
    shift = workday_shift(before.end, after.end)
    if shift:
        days = f"{abs(shift)} Arbeitstag{'' if abs(shift) == 1 else 'e'}"
        text = (
            f"Voraussichtliches Ende {_date(after.end)} statt {_date(before.end)} "
            f"({days} {'früher' if shift < 0 else 'später'})"
        )
    else:
        text = f"Das voraussichtliche Ende bleibt der {_date(before.end)}"
    known = {skill.casefold() for skill in people[member].skills}
    for tid in moved:
        missing = [s for s in tasks[tid].required_skills if s.casefold() not in known]
        if missing:
            text += f". {member} hat {', '.join(missing)} nicht angegeben ({tid})"
    return text


def next_step(tracking: Tracking, today: date) -> tuple[str, str]:
    """What the project lead should look at next, and on which page ("durchfuehrung" or
    "kontrolle"). The most urgent reason wins."""
    outlook = forecast(tracking, today)
    late = len(evaluate(tracking, today).overdue)
    if outlook.problem:
        return (
            f"Die Prognose lässt sich nicht berechnen: {outlook.problem}. Prüfe Status und "
            "Rest-Stunden auf der Seite Durchführung.",
            "durchfuehrung",
        )
    if outlook.end is None:
        return (
            "Alle Aufgaben sind fertig. Der Statusbericht auf der Seite Durchführung hält den "
            "Abschluss fest.",
            "durchfuehrung",
        )
    if outlook.deadline_gap > 0:
        return (
            "Nach heutigem Stand wird die Deadline verpasst. Die Seite Kontrolle zeigt, welche "
            "Aufgaben das Ende verschieben.",
            "kontrolle",
        )
    if late:
        count = "1 Aufgabe ist" if late == 1 else f"{late} Aufgaben sind"
        return (
            f"{count} im Verzug. Die Seite Kontrolle zeigt, was daran hängt und wohin das "
            "Ende rückt.",
            "kontrolle",
        )
    if not has_progress(tracking):
        return (
            "Noch kein Fortschritt erfasst. Trage Status und Ist-Stunden auf der Seite "
            "Durchführung ein.",
            "durchfuehrung",
        )
    return (
        "Das Projekt liegt im Plan. Halte den Fortschritt auf der Seite Durchführung aktuell.",
        "durchfuehrung",
    )


def forecast_text(outlook: Forecast, deadline: date) -> str:
    """The forecast as one sentence, for the status report and the Startseite."""
    if outlook.problem:
        return f"Nicht berechenbar: {outlook.problem}"
    if outlook.end is None:
        return "Alle Aufgaben sind fertig."

    def days(count: int) -> str:
        return f"{abs(count)} Arbeitstag{'' if abs(count) == 1 else 'e'}"

    if outlook.shift:
        against_plan = (
            f"{days(outlook.shift)} {'später' if outlook.shift > 0 else 'früher'} als geplant"
        )
    else:
        against_plan = "wie geplant"
    if outlook.deadline_gap > 0:
        against_deadline = (
            f"die Deadline ({_date(deadline)}) wird um {days(outlook.deadline_gap)} verpasst"
        )
    elif outlook.deadline_gap < 0:
        left = "bleibt" if outlook.deadline_gap == -1 else "bleiben"
        against_deadline = (
            f"bis zur Deadline ({_date(deadline)}) {left} {days(outlook.deadline_gap)} Puffer"
        )
    else:
        against_deadline = f"bis zur Deadline ({_date(deadline)}) bleibt kein Puffer"
    return f"Voraussichtliches Ende {_date(outlook.end)}, {against_plan}; {against_deadline}"


def forecast_bars(evaluation: Evaluation, outlook: Forecast) -> list[dict[str, Any]]:
    """Two bars per unfinished task for a chart: where the plan had it and where the forecast
    puts it."""
    planned = {t.id: t for t in evaluation.tasks}
    bars = []
    for expected in outlook.schedule:
        task = planned[expected.task_id]
        for kind, first, last in [
            ("Plan", task.planned_start, task.planned_end),
            ("Prognose", expected.start, expected.end),
        ]:
            bars.append(
                {
                    "Aufgabe": f"{task.id} · {task.title}",
                    "Art": kind,
                    "Start": first,
                    "Ende": bar_end(last),
                    "Zeitraum": f"{first:%d.%m.} – {last:%d.%m.}",
                }
            )
    return bars


# The columns of the progress table that the project lead cannot change.
PROGRESS_READ_ONLY = PROGRESS_COLUMNS[:6]


def progress_rows(tracking: Tracking, today: date | None = None) -> list[dict[str, Any]]:
    """One row per task for the progress table. Status, Ist (h), Rest (h) and Notiz are
    edited; "Prognose Ende" is where the forecast puts the task."""
    today = today or date.today()
    outlook = forecast(tracking, today)
    expected = {s.task_id: _date(s.end) for s in outlook.schedule}
    return [
        dict(
            zip(
                PROGRESS_COLUMNS,
                [
                    t.id,
                    t.title,
                    t.member,
                    t.planned_hours,
                    _date(t.planned_end),
                    "fertig" if t.status == "fertig" else expected.get(t.id, "nicht berechenbar"),
                    t.status,
                    t.actual_hours,
                    t.remaining_hours,
                    t.note,
                ],
                strict=True,
            )
        )
        for t in evaluate(tracking, today).tasks
    ]


def status_report(
    tracking: Tracking, evaluation: Evaluation, summary: StatusSummary | None = None
) -> str:
    """The status report. `summary` is the text part the Durchführung agent proposed."""
    project, tasks = tracking.project, evaluation.tasks
    if summary is None:
        text = (
            "Noch nicht erstellt. Der Durchführungs-Agent schlägt sie auf der Seite "
            "Durchführung vor."
        )
    else:
        steps = "\n".join(f"- **{step.task_id}:** {step.action}" for step in summary.next_steps)
        note = "*Vorschlag des Durchführungs-Agenten (Claude), von der Projektleitung zu prüfen.*"
        text = "\n\n".join(filter(None, [summary.summary, steps, note]))
    count = {status: sum(t.status == status for t in tasks) for status in STATUSES}
    outlook = forecast(tracking, evaluation.today)
    ahead = week_ahead(tracking, evaluation.today)
    if outlook.problem:
        coming = NO_WEEK_AHEAD  # the reason stands next to "Prognose" above
    elif outlook.end is None:
        coming = NOTHING_LEFT
    elif not ahead:
        coming = NOTHING_AHEAD
    else:
        rows = ["| " + " | ".join(_md(str(cell)) for cell in row.values()) + " |" for row in ahead]
        head = ["| Person | ID | Aufgabe | Beginn | Ende | Status |", "|---|---|---|---|---|---|"]
        coming = "\n".join(head + rows)
    overdue = [
        f"- {t.id} · {t.title} ({t.member}), geplant bis {_date(t.planned_end)}, Status: {t.status}"
        for t in evaluation.overdue
    ]
    return _fill(
        "statusbericht.md",
        projekt=project.idea,
        stand=_date(evaluation.today),
        start=_date(project.start_date),
        deadline=_date(project.deadline),
        planende=_date(max(t.planned_end for t in tasks)),
        prognose=forecast_text(outlook, project.deadline),
        naechste=coming,
        fortschritt=percent(evaluation.progress),
        fertig=count["fertig"],
        in_arbeit=count["in Arbeit"],
        offen=count["offen"],
        plan_h=f"{evaluation.planned_hours:g}",
        ist_h=f"{evaluation.actual_hours:g}",
        abweichung=f"{evaluation.finished_deviation:+g}",
        zusammenfassung=text,
        verzug="\n".join(overdue) or "Keine Aufgabe im Verzug.",
        aufgaben="\n".join(
            f"| {t.id} | {_md(t.title)} | {t.member} | {t.status} | {t.planned_hours:g} | "
            f"{t.actual_hours:g} | {_md(t.note)} |"
            for t in tasks
        ),
        risiken="\n".join(f"- {r}" for r in tracking.plan.risks) or "Keine Risiken erfasst.",
    )


NOT_COMPUTABLE = "Keine Umverteilung: nicht nachrechenbar"


def measure_effect(tracking: Tracking, today: date, task_ids: list[str], member: str | None) -> str:
    """What Python can say about a countermeasure: the effect of its reassignment on the
    forecast, or that there is nothing to compute."""
    if member is None:
        return NOT_COMPUTABLE
    return reassignment_effect(tracking, today, task_ids, member)


def control_document(
    tracking: Tracking,
    evaluation: Evaluation,
    report: ControlReport | None = None,
    rate: float | None = None,
) -> str:
    """The control report. `report` is what the Kontrolle agent proposed, `rate` the hourly
    rate for the cost lines; both can be missing."""
    project, today = tracking.project, evaluation.today
    outlook = forecast(tracking, today)
    value = earned_value(tracking, evaluation)
    overdue = [
        f"- {_md(t.id)} · {_md(t.title)} ({_md(t.member)}), geplant bis "
        f"{_date(t.planned_end)}, Status: "
        f"{t.status}; hält auf: {', '.join(outlook.blocked.get(t.id, [])) or 'nichts'}"
        for t in evaluation.overdue
    ]
    if rate is not None:  # 0 € is a rate, as on the Kontrolle page
        cost = (
            f"- Plankosten gesamt: {euro(evaluation.planned_hours * rate)}\n"
            f"- Ist-Kosten bisher: {euro(evaluation.actual_hours * rate)}"
        )
    else:
        cost = "- Kosten: kein Stundensatz gesetzt"
    if report is None:
        judgement = (
            "Noch nicht erstellt. Der Kontroll-Agent schlägt sie auf der Seite Kontrolle vor."
        )
    else:
        findings = "\n".join(
            "- "
            + (f"**{_md(', '.join(finding.task_ids))}:** " if finding.task_ids else "")
            + _md(finding.observation)
            for finding in report.findings
        )
        measures = "\n".join(
            f"| {_md(', '.join(m.task_ids))} | {_md(m.action)} | {_md(m.effect)} | "
            f"{_md(measure_effect(tracking, today, m.task_ids, m.reassign_to))} |"
            for m in report.measures
        )
        table = (
            "| Aufgaben | Maßnahme | Erwartete Wirkung (Claude) | Nachgerechnet (Python) |\n"
            f"|---|---|---|---|\n{measures}"
            if report.measures
            else "Keine Gegenmaßnahmen vorgeschlagen."
        )
        note = "*Vorschlag des Kontroll-Agenten (Claude), von der Projektleitung zu prüfen.*"
        judgement = "\n\n".join([f"**Bewertung:** {report.assessment}", findings, table, note])
    return _fill(
        "kontrollbericht.md",
        projekt=project.idea,
        stand=_date(today),
        start=_date(project.start_date),
        deadline=_date(project.deadline),
        planende=_date(max(t.planned_end for t in evaluation.tasks)),
        prognose=forecast_text(outlook, project.deadline),
        fortschritt=percent(evaluation.progress),
        plan_h=f"{evaluation.planned_hours:g}",
        ist_h=f"{evaluation.actual_hours:g}",
        abweichung=f"{evaluation.finished_deviation:+g}",
        kosten=cost,
        planwert=hours_text(value.planned),
        fertigwert=hours_text(value.earned),
        spi=index_text(value.schedule_index, NO_SCHEDULE_INDEX),
        cpi=index_text(value.cost_index, NO_COST_INDEX),
        verzug="\n".join(overdue) or "Keine Aufgabe im Verzug.",
        personen="\n".join(
            f"| {_md(row['Person'])} | {row['Plan (h)']:g} | {row['Ist (h)']:g} | "
            f"{row['Fertig (Plan-h)']:g} |"
            for row in evaluation.by_member
        ),
        bewertung=judgement,
    )


def work_packages(tracking: Tracking) -> str:
    project = tracking.project
    reasons = {a.task_id: a.reason for a in tracking.plan.assignments}
    states = {t.id: t for t in evaluate(tracking, date.today()).tasks}
    packages = []
    for task in tracking.plan.tasks:
        state = states[task.id]
        packages.append(
            "\n".join(
                [
                    f"## {task.id} · {task.title}",
                    "",
                    "| | |",
                    "|---|---|",
                    f"| Verantwortlich | {state.member} |",
                    f"| Aufwand | {task.estimate_hours:g} h |",
                    f"| Zeitraum | {_date(state.planned_start)} bis {_date(state.planned_end)} |",
                    f"| Abhängig von | {', '.join(task.depends_on) or '–'} |",
                    f"| Benötigte Skills | {_md(', '.join(task.required_skills)) or '–'} |",
                    "",
                    f"**Beschreibung:** {task.description or '–'}",
                    "",
                    f"**Begründung der Zuweisung:** {reasons[task.id]}",
                ]
            )
        )
    return _fill(
        "arbeitspakete.md",
        projekt=project.idea,
        start=_date(project.start_date),
        deadline=_date(project.deadline),
        pakete="\n\n".join(packages),
    )


def agent_runs(log_dir: Path | None = None) -> list[dict[str, Any]]:
    """What every logged agent run cost in time and tokens, newest first. Failed runs count
    too: they also took time and tokens."""
    paths = [
        (path.name.removeprefix(f"{prefix}-"), agent, path)
        for prefix, agent in AGENTS.items()
        for path in (log_dir or LOG_DIR).glob(f"{prefix}-*.json")
    ]
    runs = []
    for _, agent, path in sorted(paths, key=lambda item: item[0], reverse=True):
        record = json.loads(path.read_text(encoding="utf-8"))
        usages = [r.get("usage", {}) for r in record.get("rounds", [])]
        outcome = record.get("outcome", "error")
        runs.append(
            {
                "Lauf": path.name,
                "Agent": agent,
                "Ergebnis": "Fehler" if outcome == "error" else outcome.capitalize(),
                "Dauer (s)": record.get("seconds"),
                "Runden": len(usages),
                # Cached parts of the history are input too; the API reports them separately.
                "Eingabe-Token": sum(
                    u.get(key, 0)
                    for u in usages
                    for key in (
                        "input_tokens",
                        "cache_creation_input_tokens",
                        "cache_read_input_tokens",
                    )
                ),
                "Ausgabe-Token": sum(u.get("output_tokens", 0) for u in usages),
            }
        )
    return runs


def _fill(template: str, **values: Any) -> str:
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    return Template(text).substitute(values)
