"""Execution and control of an adopted plan: the baseline, the progress the project lead
records, the plan/actual comparison and the documents filled from both.

No Streamlit and no LLM in here. Every number comes from the adopted plan and the recorded
progress. The file lives in data/ like the team file: it holds personal data and is git-ignored.
"""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import islice
from pathlib import Path
from string import Template
from threading import RLock
from typing import Any, Literal, NamedTuple, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pm_agent import agent as agents
from pm_agent import workbench
from pm_agent.models import (
    Case,
    ControlReport,
    Lesson,
    Member,
    Plan,
    Project,
    Requirement,
    ScheduledTask,
    StatusSummary,
    Task,
)
from pm_agent.planning import (
    add_working_days,
    check_plan,
    planned_work,
    project_weeks,
    working_shift,
)
from pm_agent.workbench import (
    DATA_DIR,
    InputError,
    _cell,
    _date,
    _inert,
    _md,
    _reason,
    bar_end,
)

PROJECT_FILE = DATA_DIR / "projekt.json"
PROJECT_WRITE_LOCK = RLock()
TEMPLATES = Path(__file__).parent / "templates"

Status = Literal["offen", "in Arbeit", "fertig"]
STATUSES = list(get_args(Status))
# Log file prefix of each agent (agent.run_agent) and its name in the UI.
AGENTS = {
    "auftrag": "Projektauftrag",
    "anforderungen": "Anforderungen",
    "entwurf": "Entwurf",
    "testplan": "Testplan",
    "lessons": "Lessons Learned",
    "run": "Planung",
    "durchfuehrung": "Durchführung",
    "kontrolle": "Kontrolle",
}
PROGRESS_COLUMNS = [
    "ID",
    "Aufgabe",
    "Person",
    "Plan (h)",
    "Geplantes Ende",
    "Prognose Ende",
    "Status",
    "Fertig am",
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
    # The day the task was finished. None while it is not, and for tasks finished before
    # this was recorded: their day is unknown.
    finished_on: date | None = None


class Earlier(BaseModel):
    """Work done under an earlier adopted plan, kept when the rest of the project was adopted
    as a new plan. A finished task, or the booked part of a task that went on in the new
    plan under the same ID."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    member: str
    # A finished task: its estimate. A part: what the booked hours stood for, the estimate
    # less what was left of it (rest_plan); the new plan has the rest.
    planned_hours: float = Field(ge=0, allow_inf_nan=False)
    actual_hours: float = Field(ge=0, allow_inf_nan=False)
    finished: bool
    note: str = ""
    until: date  # the day the next plan was adopted
    requirement_ids: list[str] = Field(default_factory=list)  # what the task served
    superseded_requirement_ids: list[str] = Field(default_factory=list)
    finished_on: date | None = None  # a finished task: the day, if it was recorded
    planned_end: date | None = None  # where its plan had it; None in files saved before


class Retro(BaseModel):
    """The look back at one week: was its demo shown, and what follows from it.
    Entered by the project lead; nothing here is the agent's."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # The Monday of the calendar week. Not the week number: that counts from the start
    # of the plan, and the rest of a project, planned again, starts later.
    monday: date
    shown: Literal["ja", "teilweise", "nein"]
    went_wrong: str = ""
    cause: str = ""
    measure: str = ""
    measure_done: bool = False


class CaseResult(BaseModel):
    """What the team found when it ran a test case. Entered by the project lead."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str
    result: Literal["bestanden", "fehlgeschlagen", "blockiert"]
    on: date
    note: str = ""
    version: str | None = None  # historical results may lack the version they tested


class CasePlan(NamedTuple):
    cases: list[Case]
    versions: dict[str, str]


class Defect(BaseModel):
    """A defect found by a test case, with its suspected cause and the task to fix it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = ""  # F1 …, given by record_defect
    case_id: str
    severity: Literal["schwer", "mittel", "leicht"]
    cause: str
    task_id: str | None = None
    status: Literal["offen", "behoben"] = "offen"
    fixed_on: date | None = None


class Signoff(BaseModel):
    """The project lead's decision on a requirement at the end: accepted, or deferred with a
    reason (it goes into the next backlog)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    requirement_id: str
    decision: Literal["abgenommen", "zurückgestellt"]
    reason: str = ""
    superseded: bool = False  # the requirement changed or left the adopted plan


class Operation(BaseModel):
    """How one component of the design is run: who is responsible (a role, not a name),
    how it is deployed, watched and taken back."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    component_id: str
    owner: str = ""
    deployment: str = ""
    monitoring: str = ""
    rollback: str = ""


class Incident(BaseModel):
    """A disruption in operation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = ""  # S1 …, given by closing.record_incident
    on: date
    component_id: str
    impact: str
    cause: str = ""
    measure: str = ""
    status: Literal["offen", "behoben"] = "offen"


class Tracking(BaseModel):
    """The plan the project lead adopted, and what happened to each task since."""

    model_config = ConfigDict(extra="forbid")

    adopted: datetime
    project: Project
    team: list[Member]
    plan: Plan
    progress: dict[str, Progress]
    history: list[Earlier] = Field(default_factory=list)
    # The requirements approved when the plan was adopted. A snapshot like project and plan:
    # progress per requirement is measured against what the plan was traced to.
    requirements: list[Requirement] = Field(default_factory=list)
    # One per calendar week, kept when the rest is adopted again.
    retros: list[Retro] = Field(default_factory=list)
    # The latest result of each test case, and the defects found; kept like the retros.
    results: list[CaseResult] = Field(default_factory=list)
    defects: list[Defect] = Field(default_factory=list)
    # The decisions at the end, one per requirement (closing.record_signoff).
    signoffs: list[Signoff] = Field(default_factory=list)
    lessons: list[Lesson] = Field(default_factory=list)  # changed by the lead
    operations: list[Operation] = Field(default_factory=list)
    incidents: list[Incident] = Field(default_factory=list)
    # The planned end of the first plan adopted, kept when the rest is adopted again. None:
    # adopted before this was recorded.
    first_planned_end: date | None = None


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
    finished_on: date | None = None


@dataclass(frozen=True)
class Evaluation:
    """Plan and actual of the adopted plan and of the work kept from earlier plans."""

    today: date
    tasks: list[TaskState]
    history: list[Earlier]
    planned_hours: float
    actual_hours: float
    earned: float  # planned hours of what is finished (0/100 rule, see EarnedValue)
    progress: float  # earned / all planned hours
    finished_deviation: float  # actual - planned, finished work only
    by_member: list[dict[str, Any]]

    @property
    def overdue(self) -> list[TaskState]:
        return [t for t in self.tasks if t.overdue]


def adopt(
    project: Project,
    team: list[Member],
    plan: Plan,
    path: Path | None = None,
    keep: Tracking | None = None,
    requirements: list[Requirement] | None = None,
) -> Tracking:
    """Make the plan the baseline. Replaces an adopted project and its progress.

    With `keep`, the project adopted before, its work stays as history: finished tasks, and
    the booked part of every started task. A started task that is in the new plan under the
    same ID goes on there "in Arbeit"; its new estimate is what was left (rest_plan).

    `requirements`: the approved ones the plan is traced to; they are kept with it."""
    checked = check_plan(plan, team, project, requirements=requirements)
    errors = checked.errors
    if errors:
        raise InputError("Der Plan hat noch Fehler: " + "; ".join(errors))
    if keep is not None and (again := finished_again(keep, plan)):
        raise InputError(
            f"Fertige Aufgabe wieder im Plan: {', '.join(again)}. Sie würde doppelt zählen. "
            "Behalten passt zum neu geplanten Rest des Projekts"
        )
    adopted = datetime.now().astimezone().replace(microsecond=0)
    progress = {t.id: Progress() for t in plan.tasks}
    history: list[Earlier] = []
    signoffs: list[Signoff] = []
    # Without a new approved snapshot, the rest keeps the requirements it was traced to.
    if requirements is None:
        requirements = keep.requirements if keep is not None else []
    if keep is not None:
        previous = {need.id: need for need in keep.requirements}
        unchanged = {need.id for need in requirements if previous.get(need.id) == need}
        for entry in [*keep.history, *_closed(keep, adopted.date())]:
            obsolete = [
                rid
                for rid in entry.requirement_ids
                if rid in entry.superseded_requirement_ids or rid not in unchanged
            ]
            history.append(entry.model_copy(update={"superseded_requirement_ids": obsolete}))
        signoffs = [
            decision.model_copy(update={"superseded": True})
            if decision.requirement_id not in unchanged
            else decision
            for decision in keep.signoffs
        ]
        for task_id, done in keep.progress.items():
            if task_id in progress and done.status == "in Arbeit":
                progress[task_id] = Progress(status="in Arbeit", note=done.note)
    tracking = Tracking(
        adopted=adopted,
        project=project,
        team=team,
        plan=plan,
        progress=progress,
        history=history,
        requirements=requirements,
        retros=keep.retros if keep is not None else [],
        results=keep.results if keep is not None else [],
        defects=keep.defects if keep is not None else [],
        signoffs=signoffs,
        lessons=keep.lessons if keep is not None else [],
        operations=keep.operations if keep is not None else [],
        incidents=keep.incidents if keep is not None else [],
        first_planned_end=keep.first_planned_end if keep is not None else checked.end_date,
    )
    save(tracking, path)
    return tracking


def finished_again(tracking: Tracking, plan: Plan) -> list[str]:
    """IDs of tasks finished under `tracking` or under a plan before it that `plan` has
    again. Kept as history they would count twice; the rest of a project (rest_plan) has
    none."""
    done = {e.id for e in tracking.history if e.finished}
    done |= {task_id for task_id, p in tracking.progress.items() if p.status == "fertig"}
    return [t.id for t in plan.tasks if t.id in done]


def covered_requirements(
    tracking: Tracking, current: list[Requirement] | None = None
) -> frozenset[str]:
    """Requirements whose every task is finished, in this plan or in one before it: the rest
    of the project needs no new task for them. With `current` (the requirements approved
    now), only those that still read as they did when the plan was adopted: an ID used again
    for something else is not covered by the old work."""
    covered = {rid for rid, tasks in _requirement_tasks(tracking).items() if all(tasks.values())}
    if current is not None:
        then = {need.id: need for need in tracking.requirements}
        covered = {need.id for need in current if need.id in covered and then.get(need.id) == need}
    return frozenset(covered)


def requirement_progress(tracking: Tracking) -> list[dict[str, Any]]:
    """Per requirement adopted with the plan: its tasks, of this plan and finished ones of
    plans before it, and how many of them are finished. Empty without requirements."""
    if not tracking.requirements:
        return []
    rows = []
    by_requirement = _requirement_tasks(tracking)
    for need in tracking.requirements:
        tasks = by_requirement.get(need.id, {})
        rows.append(
            {
                "ID": need.id,
                "Anforderung": need.title,
                "Priorität": need.priority,
                "Aufgaben": ", ".join(tasks) or "keine",
                "Fertig": f"{sum(tasks.values())} von {len(tasks)}",
            }
        )
    return rows


def _requirement_tasks(tracking: Tracking) -> dict[str, dict[str, bool]]:
    by_requirement: dict[str, dict[str, bool]] = {}
    for entry in tracking.history:
        if entry.finished:
            for rid in entry.requirement_ids:
                if rid not in entry.superseded_requirement_ids:
                    by_requirement.setdefault(rid, {})[entry.id] = True
    for task in tracking.plan.tasks:
        if not task.requirement_ids:
            continue
        done = tracking.progress[task.id].status == "fertig"
        for rid in task.requirement_ids:
            by_requirement.setdefault(rid, {})[task.id] = done
    return by_requirement


def _closed(tracking: Tracking, day: date) -> list[Earlier]:
    """What was done under `tracking`, as history entries closed on `day`."""
    estimates = {t.id: t for t in tracking.plan.tasks}
    closed = []
    for state in evaluate(tracking, day).tasks:
        finished = state.status == "fertig"
        if not finished and state.status != "in Arbeit" and not state.actual_hours:
            continue  # nothing done: the task is simply in the new plan or gone
        left = _left(estimates[state.id], tracking.progress[state.id])
        closed.append(
            Earlier(
                id=state.id,
                title=state.title,
                member=state.member,
                planned_hours=(
                    state.planned_hours if finished else max(state.planned_hours - left, 0)
                ),
                actual_hours=state.actual_hours,
                finished=finished,
                note=state.note,
                until=day,
                requirement_ids=estimates[state.id].requirement_ids,
                finished_on=state.finished_on if finished else None,
                planned_end=state.planned_end,
            )
        )
    return closed


class RetroCheck(NamedTuple):
    errors: list[str]
    warnings: list[str]


def _weeks(tracking: Tracking) -> dict[int, tuple[date, date]]:
    """First and last day of each week that has a demo in the plan."""
    if not tracking.plan.demos:
        return {}
    count = max(d.week for d in tracking.plan.demos)
    project = tracking.project
    return {
        n: (first, last)
        for n, first, last in islice(project_weeks(project.start_date, project.deadline), count)
    }


def monday(day: date) -> date:
    """The Monday of the calendar week `day` lies in."""
    return day - timedelta(days=day.weekday())


def _retro_errors(retro: Retro) -> list[str]:
    if retro.shown != "ja" and not retro.measure:
        missed = "nur teilweise" if retro.shown == "teilweise" else "nicht"
        return [
            f"Woche ab {_date(retro.monday)}: Die Demo fand {missed} statt, es fehlt eine Maßnahme"
        ]
    return []


def check_retros(tracking: Tracking, today: date) -> RetroCheck:
    """Errors: a missed demo without a measure. Warnings: a week that is over and has a demo
    but no retro."""
    errors = [e for r in tracking.retros for e in _retro_errors(r)]
    done = {r.monday for r in tracking.retros}
    weeks = _weeks(tracking)
    warnings = [
        f"Woche {d.week} ({d.title}) hat noch keinen Rückblick"
        for d in sorted(tracking.plan.demos, key=lambda d: d.week)
        if d.week in weeks and weeks[d.week][1] < today and monday(weeks[d.week][0]) not in done
    ]
    return RetroCheck(errors, warnings)


def record_retro(tracking: Tracking, retro: Retro) -> Tracking:
    """The retro of its week, replacing an earlier one. Raises InputError while a missed
    demo has no measure. Not saved: the caller saves."""
    errors = _retro_errors(retro)
    if errors:
        raise InputError("\n".join(errors))
    others = [r for r in tracking.retros if r.monday != retro.monday]
    return tracking.model_copy(update={"retros": sorted([*others, retro], key=lambda r: r.monday)})


def open_measures(tracking: Tracking) -> list[Retro]:
    """Retros whose measure is not done yet."""
    return [r for r in tracking.retros if r.measure and not r.measure_done]


def demo_mondays(tracking: Tracking) -> dict[int, date]:
    """Week number of each demo -> the Monday of its calendar week (the key of its retro).
    A demo after the deadline has none."""
    return {n: monday(first) for n, (first, _) in _weeks(tracking).items()}


def demo_status(tracking: Tracking, today: date) -> list[dict[str, Any]]:
    """One row per demo of the plan: until when, how many of its tasks are done, and whether
    it was shown (from the retro), or that its week is still running or to come."""
    weeks = _weeks(tracking)
    shown = {r.monday: r.shown for r in tracking.retros}
    rows = []
    for demo in sorted(tracking.plan.demos, key=lambda d: d.week):
        first, last = weeks.get(demo.week, (None, None))
        done = sum(tracking.progress[tid].status == "fertig" for tid in demo.task_ids)
        if first is not None and monday(first) in shown:
            state = shown[monday(first)]
        elif last is None:
            state = "nach der Deadline"
        elif last < today:
            state = "offen"
        elif first <= today:
            state = "Woche läuft"
        else:
            state = "kommt"
        rows.append(
            {
                "Woche": demo.week,
                "Bis": _date(last) if last else "–",
                "Demo": demo.title,
                "Fertig": f"{done} von {len(demo.task_ids)}",
                "Gezeigt": state,
            }
        )
    return rows


def demo_this_week(tracking: Tracking, today: date) -> str | None:
    """One line on the demo of the week `today` lies in, or None (no demo, a weekend)."""
    for week, (first, last) in _weeks(tracking).items():
        if first <= today <= last:
            demo = next((d for d in tracking.plan.demos if d.week == week), None)
            if demo is None:
                return None
            done = sum(tracking.progress[tid].status == "fertig" for tid in demo.task_ids)
            return (
                f"Demo dieser Woche (bis {_date(last)}): {demo.title}, {done} von "
                f"{len(demo.task_ids)} Aufgaben fertig"
            )
    return None


def record_result(tracking: Tracking, result: CaseResult, plan: CasePlan) -> Tracking:
    """The result of a test case, replacing an earlier one of the same case."""
    version = plan.versions.get(result.case_id)
    if version is None:
        raise InputError(f"Testfall '{result.case_id}' ist nicht eindeutig im Testplan")
    result = result.model_copy(update={"version": version})
    others = [r for r in tracking.results if r.case_id != result.case_id]
    return tracking.model_copy(update={"results": [*others, result]})


def current_results(tracking: Tracking, plan: CasePlan | None) -> dict[str, CaseResult]:
    """Only results recorded for the case and the contract in this plan."""
    if plan is None:
        return {}
    return {
        r.case_id: r
        for r in tracking.results
        if r.version is not None and r.version == plan.versions.get(r.case_id)
    }


def record_defect(tracking: Tracking, defect: Defect) -> Tracking:
    """A defect, new (numbered F1, F2 …) or changed (same ID). Raises InputError for an
    unknown task, and for a severe defect without a task to fix it."""
    before = next((d for d in tracking.defects if defect.id and d.id == defect.id), None)
    # A task that left the plan ("Rest umplanen") does not block closing its defect.
    changed = before is None or before.task_id != defect.task_id
    if changed and defect.task_id and defect.task_id not in tracking.progress:
        raise InputError(f"Der Fehler nennt die unbekannte Aufgabe '{defect.task_id}'")
    if defect.severity == "schwer" and not defect.task_id:
        raise InputError("Ein schwerer Fehler braucht eine Aufgabe, die ihn behebt")
    if not defect.id:
        numbers = [int(d.id[1:]) for d in tracking.defects if d.id[1:].isdigit()]
        defect = defect.model_copy(update={"id": f"F{max(numbers, default=0) + 1}"})
    if defect.status == "offen" and defect.fixed_on is not None:
        defect = defect.model_copy(update={"fixed_on": None})
    others = [d for d in tracking.defects if d.id != defect.id]
    return tracking.model_copy(update={"defects": [*others, defect]})


def reopen(tracking: Tracking, defect_id: str) -> Tracking:
    """The task of a defect goes back to "in Arbeit": the defect is work again."""
    defect = next((d for d in tracking.defects if d.id == defect_id), None)
    if defect is None or not defect.task_id:
        raise InputError(f"Der Fehler {defect_id} hat keine Aufgabe, die sich öffnen ließe")
    if defect.task_id not in tracking.progress:
        raise InputError(
            f"Die Aufgabe '{defect.task_id}' von {defect_id} ist nicht mehr im Plan. Plane sie "
            "neu ein oder gib den Fehler einer anderen Aufgabe."
        )
    done = tracking.progress[defect.task_id]
    progress = {
        **tracking.progress,
        defect.task_id: done.model_copy(update={"status": "in Arbeit", "finished_on": None}),
    }
    return tracking.model_copy(update={"progress": progress})


def first_five(ids: list[str]) -> str:
    """IDs for one line beside the table that lists them all: "A, B, C, D, E und 2 weitere"."""
    return ", ".join(ids[:5]) + (f" und {len(ids) - 5} weitere" * (len(ids) > 5))


def untested(tracking: Tracking, plan: CasePlan) -> list[str]:
    """The warning of check_results about cases without a result, or none. The table of
    results lists them all; the line names where to begin."""
    latest = current_results(tracking, plan)
    missing = [c.id for c in plan.cases if c.id not in latest]
    if not missing:
        return []
    subject = "1 Testfall" if len(missing) == 1 else f"{len(missing)} Testfälle"
    return [f"{subject} ohne Ergebnis: {first_five(missing)}"]


def check_results(tracking: Tracking, plan: CasePlan) -> RetroCheck:
    """Errors: a failed case without an open defect. Warnings: cases without a result, open
    defects whose task is finished."""
    latest = current_results(tracking, plan)
    found = {d.case_id for d in tracking.defects if d.status == "offen"}
    errors = []
    for c in plan.cases:
        if c.id not in latest or latest[c.id].result != "fehlgeschlagen" or c.id in found:
            continue
        # A fixed defect does not count: the case may fail again after the fix. With fixed_on
        # set, "not tested again since the fix" and "failed again after the fix" are distinct.
        fixed_defects = [d for d in tracking.defects if d.case_id == c.id]
        fixed = [d.id for d in fixed_defects]
        fixed_dates = [d.fixed_on for d in fixed_defects if d.fixed_on is not None]
        if fixed and len(fixed_dates) == len(fixed_defects):
            last_fix = max(fixed_dates)
            if latest[c.id].on > last_fix:
                errors.append(
                    f"Testfall '{c.id}' ist am {_date(latest[c.id].on)} nach der Behebung von "
                    f"{', '.join(fixed)} (am {_date(last_fix)}) wieder fehlgeschlagen: neuen "
                    "Fehler erfassen oder Fehler wieder öffnen"
                )
            elif latest[c.id].on == last_fix:  # days only: which came first is unknown
                errors.append(
                    f"Testfall '{c.id}' ist am {_date(last_fix)} fehlgeschlagen, am selben Tag "
                    f"wurde {', '.join(fixed)} behoben: War das der Test nach der Behebung, "
                    "neuen Fehler erfassen oder Fehler wieder öffnen, sonst Testfall wiederholen"
                )
            else:
                errors.append(
                    f"Testfall '{c.id}' ist fehlgeschlagen, sein Fehler {', '.join(fixed)} ist "
                    f"seit {_date(last_fix)} behoben: Testfall wiederholen"
                )
        elif fixed:
            errors.append(
                f"Testfall '{c.id}' ist fehlgeschlagen, sein Fehler {', '.join(fixed)} ist "
                "behoben: Testfall wiederholen. Schlägt er wieder fehl, einen neuen Fehler "
                "erfassen"
            )
        else:
            errors.append(
                f"Testfall '{c.id}' ist fehlgeschlagen, aber es gibt keinen Fehlereintrag"
            )
    warnings = untested(tracking, plan)
    warnings += [
        f"Fehler {d.id} ist offen, seine Aufgabe '{d.task_id}' ist aber fertig"
        for d in tracking.defects
        if d.status == "offen"
        and d.task_id in tracking.progress
        and tracking.progress[d.task_id].status == "fertig"
    ]
    return RetroCheck(errors, warnings)


def quality_summary(tracking: Tracking, plan: CasePlan) -> dict[str, str]:
    """How far testing is: cases with a result, passed ones, open defects by severity.
    Not "test_…": pytest would take a function of that name for a test."""
    latest = current_results(tracking, plan)
    passed = sum(r.result == "bestanden" for r in latest.values())
    open_ = [d for d in tracking.defects if d.status == "offen"]
    severe = sum(d.severity == "schwer" for d in open_)
    return {
        "Mit Ergebnis": f"{len(latest)} von {len(plan.cases)}",
        "Bestanden": str(passed),
        "Offene Fehler": f"{len(open_)} (schwer: {severe})" if open_ else "0",
    }


def case_status(tracking: Tracking, plan: CasePlan) -> list[dict[str, Any]]:
    """One row per test case: its current result, a historical result, and defects."""
    latest = current_results(tracking, plan)
    previous = {r.case_id: r for r in tracking.results if r.case_id not in latest}
    return [
        {
            "ID": c.id,
            "Testfall": c.title,
            "Art": c.kind,
            "Ergebnis": latest[c.id].result if c.id in latest else "offen",
            "Am": _date(latest[c.id].on) if c.id in latest else "",
            "Früheres Ergebnis": (
                f"{previous[c.id].result} ({_date(previous[c.id].on)})" if c.id in previous else ""
            ),
            "Fehler": ", ".join(d.id for d in tracking.defects if d.case_id == c.id),
        }
        for c in plan.cases
    ]


def load(path: Path | None = None) -> Tracking | None:
    """None if no plan was adopted yet. A damaged file is an error, not an empty project."""
    path = path or PROJECT_FILE
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:  # saved by an editor in another encoding
        raise InputError(f"{path.name} ist beschädigt: kein UTF-8 ({err.reason})") from err
    except OSError as err:  # locked, no permission, a folder of that name
        raise InputError(f"{path.name} konnte nicht gelesen werden: {err}") from err
    try:
        return Tracking.model_validate(json.loads(text))
    except (ValueError, ValidationError) as err:
        raise InputError(f"{path.name} ist beschädigt: {_reason(err)}") from err


def save(tracking: Tracking, path: Path | None = None) -> None:
    path = path or PROJECT_FILE  # read at call time: tests point it to a temporary folder
    with PROJECT_WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tracking.model_dump_json(indent=2), encoding="utf-8")


def require_current(expected: Tracking | None, *, replace_unreadable: bool = False) -> None:
    """Check the on-disk project while the caller holds PROJECT_WRITE_LOCK."""
    try:
        current = load()
    except InputError:
        if replace_unreadable:
            return
        raise
    if replace_unreadable or current != expected:
        raise InputError("Das Projekt wurde inzwischen geändert. Prüfe den aktuellen Stand.")


def save_if_current(old: Tracking, new: Tracking) -> None:
    with PROJECT_WRITE_LOCK:
        require_current(old)
        save(new)


def percent(share: float) -> str:
    """0.333 -> "33 %", the German way."""
    return f"{share:.0%}".replace("%", " %")


def euro(amount: float) -> str:
    """1600 -> "1.600,00 €", the German way."""
    return f"{amount:,.2f} €".translate(str.maketrans(",.", ".,"))


def has_progress(tracking: Tracking) -> bool:
    return bool(tracking.history) or any(p != Progress() for p in tracking.progress.values())


def _finish_date(value: Any, where: str) -> date | None:
    """A cell of "Fertig am": empty, a date, or a date as text in either form."""
    text = _cell(value)  # empty for None, NaN and pandas.NaT (a datetime unequal to itself)
    if not text:
        return None
    if isinstance(value, datetime):  # also pandas.Timestamp
        return value.date()
    if isinstance(value, date):
        return value
    for form in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, form).date()
        except ValueError:
            pass
    raise InputError(f"{where}: Fertig am '{text}' ist kein Datum (TT.MM.JJJJ)")


def _finished_on(
    before: Progress, status: str, row: dict[str, Any], where: str, start: date, today: date
) -> date | None:
    """The day a task was finished, after the project lead's edit. Set to today when the task
    becomes finished; kept on saving again; dropped when the task is no longer finished. A day
    entered in the table wins, an emptied cell means unknown."""
    old = before.finished_on if before.status == "fertig" else None
    if "Fertig am" not in row:  # a row from elsewhere, without the column
        entered = old
    else:
        entered = _finish_date(row["Fertig am"], where)
    if status != "fertig":
        if entered is not None and entered != old:
            raise InputError(
                f"{where}: Fertig am gesetzt, aber Status '{status}'. Setze den Status auf "
                "fertig oder leere das Datum"
            )
        return None
    if before.status != "fertig" and entered is None:
        return today
    if entered is not None and entered > today:
        raise InputError(f"{where}: Fertig am {_date(entered)} liegt in der Zukunft")
    if entered is not None and entered < start:
        raise InputError(
            f"{where}: Fertig am {_date(entered)} liegt vor dem Projektstart {_date(start)}"
        )
    return entered


def apply_rows(
    tracking: Tracking, rows: list[dict[str, Any]], today: date | None = None
) -> Tracking:
    """The progress table as the project lead edited it. Tasks without a row keep their state."""
    today = today or date.today()
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
        finished_on = _finished_on(
            tracking.progress[task_id],
            status,
            row,
            where,
            tracking.project.start_date,
            today,
        )
        progress[task_id] = Progress(
            status=status,
            actual_hours=hours,
            remaining_hours=rest,
            note=_cell(row.get("Notiz")),
            finished_on=finished_on,
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
                finished_on=done.finished_on,
            )
        )
    finished_ids = {t.id for t in tasks if t.status == "fertig"}
    # Plan and actual of every piece of work: the tasks of the plan and the history. A part
    # in the history is finished once the task it went on as is finished, in this plan or in
    # a later one that is history now itself.
    finished_ids |= {e.id for e in tracking.history if e.finished}
    work = [(t.member, t.planned_hours, t.actual_hours, t.id in finished_ids) for t in tasks]
    work += [
        (e.member, e.planned_hours, e.actual_hours, e.finished or e.id in finished_ids)
        for e in tracking.history
    ]
    planned_hours = sum(planned for _, planned, _, _ in work)
    earned = sum(planned for _, planned, _, done in work if done)
    return Evaluation(
        today=today,
        tasks=tasks,
        history=tracking.history,
        planned_hours=planned_hours,
        actual_hours=sum(actual for _, _, actual, _ in work),
        earned=earned,
        progress=earned / planned_hours,
        finished_deviation=sum(actual - planned for _, planned, actual, done in work if done),
        by_member=[
            {
                "Person": member,
                "Plan (h)": sum(w[1] for w in work if w[0] == member),
                "Ist (h)": sum(w[2] for w in work if w[0] == member),
                "Fertig (Plan-h)": sum(w[1] for w in work if w[0] == member and w[3]),
            }
            for member in dict.fromkeys(w[0] for w in work)
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


def planned_curve(tracking: Tracking) -> list[dict[str, Any]]:
    """The planned value over the plan: the hours the plan wanted done by the end of a
    workday (planning.planned_work). Only the days where the curve bends, and the first and
    the last one."""
    values = planned_work(tracking.plan, tracking.team, tracking.project)
    return [
        {"Tag": day, "Stunden": hours}
        for number, (day, hours) in enumerate(values)
        if number in (0, len(values) - 1)
        or hours != values[number - 1][1]
        or hours != values[number + 1][1]
    ]


def earned_value(tracking: Tracking, evaluation: Evaluation) -> EarnedValue:
    reached = [
        point["Stunden"] for point in planned_curve(tracking) if point["Tag"] <= evaluation.today
    ]
    return EarnedValue(
        # Between two kept days the curve is flat or the later day is kept too. The work of
        # earlier plans was due before this plan began.
        planned=(reached[-1] if reached else 0.0) + sum(e.planned_hours for e in tracking.history),
        earned=evaluation.earned,
        actual=evaluation.actual_hours,
    )


def hours_text(value: float) -> str:
    """Hours with at most one decimal, the German way: 41.6 -> "41,6", 8.0 -> "8"."""
    # "+ 0.0" turns a rounded -0.0 into 0.0.
    return f"{round(value, 1) + 0.0:.1f}".removesuffix(".0").replace(".", ",")


def key_figures(evaluation: "Evaluation") -> dict[str, str]:
    """The numbers of the project the way the reports write them, for the agents: they repeat
    a number as they get it ("Fortschritt bei 0.0" went into a status report)."""
    return {
        "planstunden": f"{hours_text(evaluation.planned_hours)} h",
        "ist_stunden": f"{hours_text(evaluation.actual_hours)} h",
        "fortschritt": percent(evaluation.progress),
    }


def as_shown(value: Any) -> Any:
    """`value` (dicts, lists, dates, numbers) for the input of an agent, written the German
    way: dates as 20.11.2026, decimals with a comma. Whole numbers, texts and IDs stay."""
    if isinstance(value, dict):
        return {key: as_shown(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [as_shown(item) for item in value]
    if isinstance(value, date):
        return f"{value:%d.%m.%Y}"
    if isinstance(value, float):
        return hours_text(value)
    return value


def signed_hours(value: float) -> str:
    """A deviation in hours, with its sign: +2, -1,5, +0. Sums of floats leave noise such as
    2.8e-17; hours_text rounds it away."""
    text = hours_text(value)
    return text if text.startswith("-") else f"+{text}"


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


def _left(task: Task, done: Progress) -> float:
    """What is left of an unfinished task: what the project lead says, else the full estimate
    of an open task and the estimate minus the booked hours of a started one."""
    if done.remaining_hours is not None:
        return done.remaining_hours
    # Booked hours count even if the status was left at "offen".
    if done.status == "in Arbeit" or done.actual_hours:
        left = round(task.estimate_hours - done.actual_hours, 6)
        # Only when nothing is left by the numbers. A rest under an hour is a rest; and
        # never more than the task itself, if that is shorter than the hour.
        return left if left > 0 else min(MIN_REST_HOURS, task.estimate_hours)
    return task.estimate_hours


def rest_plan(tracking: Tracking, reassign: dict[str, str] | None = None) -> Plan | None:
    """The unfinished tasks as a plan of their own; None if every task is finished.

    A task counts with what the project lead says is left of it. Without that, an open task
    counts with its full estimate and a started one with the estimate minus the booked
    hours. Dependencies on finished tasks are gone. `reassign` (task ID -> member) gives
    tasks to someone else."""
    state = tracking.progress
    open_ids = {task.id for task in tracking.plan.tasks if state[task.id].status != "fertig"}
    if not open_ids:
        return None
    return Plan(
        tasks=[
            task.model_copy(
                update={
                    "estimate_hours": _left(task, state[task.id]),
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
    return project.model_copy(update={"start_date": start}), rest


def current_team(tracking: Tracking, team: list[Member] | None = None) -> list[Member]:
    """The team to forecast and replan the rest with: latest member details from team.json
    merged onto the adopted snapshot.

    Members present in team.json supply their current skills, weekly hours, note, and any
    absences added since adoption while keeping absences already adopted with the plan.
    Newly joined members are included; members who left team.json stay while unfinished tasks
    are still assigned to them so scheduling keeps working. Without a saved team file (empty),
    the adopted snapshot is returned unchanged."""
    latest = workbench.load_team() if team is None else team
    if not latest:
        return list(tracking.team)
    by_name = {m.name: m for m in latest}
    open_owners = {
        a.member
        for a in tracking.plan.assignments
        if tracking.progress[a.task_id].status != "fertig"
    }
    merged: list[Member] = []
    seen: set[str] = set()
    for member in tracking.team:
        if member.name in by_name:
            now = by_name[member.name]
            absences = list(now.absences)
            for away in member.absences:
                if away not in absences:
                    absences.append(away)
            merged.append(now.model_copy(update={"absences": absences}))
            seen.add(member.name)
        elif member.name in open_owners:
            merged.append(member)
            seen.add(member.name)
    for member in latest:
        if member.name not in seen:
            merged.append(member)
    return merged


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
    try:
        active_team = current_team(tracking)
    except InputError as err:
        return Forecast(
            planned_end=planned_end,
            end=None,
            shift=0,
            deadline_gap=0,
            blocked={},
            schedule=[],
            problem=str(err),
        )
    # The last possible date as deadline: only the dates are wanted here. Today can lie
    # behind the real deadline, and check_plan would then find no workday to plan in.
    open_end = project.model_copy(
        update={"start_date": max(today, project.start_date), "deadline": date.max}
    )
    # Scheduled like any plan: the Planung says the same about the rest when it is
    # loaded there ("Rest mit dem Agenten umplanen").
    expected = check_plan(rest, active_team, open_end, dates_only=True)
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
        # In working days of the project: its free days are no buffer.
        shift=working_shift(project, planned_end, end),
        deadline_gap=working_shift(project, project.deadline, end),
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
    horizon = add_working_days(tracking.project, today, days - 1)
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
    try:
        active_team = current_team(tracking)
    except InputError as err:
        return f"Nicht prüfbar: {err}"
    people = {m.name: m for m in active_team}
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
    shift = working_shift(tracking.project, before.end, after.end)
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


def next_step(tracking: Tracking, today: date, forecast_shown: bool = False) -> tuple[str, str]:
    """What the project lead should look at next, and on which page ("durchfuehrung",
    "kontrolle" or "testlauf"). The most urgent reason wins. The text names no page: it may
    be shown on the page it points to. `forecast_shown`: the page shows the forecast
    already (forecast_text), so a reason that only repeats it is left out."""
    outlook = forecast(tracking, today)
    late = len(evaluate(tracking, today).overdue)

    def say(reason: str, action: str, page: str, in_forecast: bool) -> tuple[str, str]:
        return (action if forecast_shown and in_forecast else f"{reason} {action}"), page

    if outlook.problem:
        return say(
            f"Die Prognose lässt sich nicht berechnen: {outlook.problem}.",
            "Prüfe Status und Rest-Stunden der Aufgaben.",
            "durchfuehrung",
            in_forecast=True,
        )
    open_defects = [d for d in tracking.defects if d.status == "offen"]
    if outlook.end is None and open_defects:
        count = "1 Fehler ist" if len(open_defects) == 1 else f"{len(open_defects)} Fehler sind"
        return say(
            f"Alle Aufgaben sind fertig, aber {count} offen.",
            "Öffne die Aufgabe wieder oder schließe den Fehler.",
            "testlauf",
            in_forecast=False,
        )
    if outlook.end is None:
        return say(
            "Alle Aufgaben sind fertig.",
            "Halte den Abschluss im Statusbericht fest.",
            "durchfuehrung",
            in_forecast=True,
        )
    if outlook.deadline_gap > 0:
        return say(
            "Nach heutigem Stand wird die Deadline verpasst.",
            "Sieh nach, welche Aufgaben das Ende verschieben.",
            "kontrolle",
            in_forecast=True,
        )
    if late:
        count = "1 Aufgabe ist" if late == 1 else f"{late} Aufgaben sind"
        return say(
            f"{count} im Verzug.",
            "Sieh nach, was daran hängt und wohin das Ende rückt.",
            "kontrolle",
            in_forecast=False,
        )
    if outlook.shift > 0:
        days = "1 Arbeitstag" if outlook.shift == 1 else f"{outlook.shift} Arbeitstage"
        return say(
            f"Nach heutigem Stand endet das Projekt {days} später als geplant; die Deadline "
            "hält noch.",
            "Sieh nach, welche Aufgaben das Ende verschieben.",
            "kontrolle",
            in_forecast=True,
        )
    if not has_progress(tracking):
        return say(
            "Noch kein Fortschritt erfasst.",
            "Bitte das Team, Status und Ist-Stunden in „Mein Bereich“ einzutragen.",
            "durchfuehrung",
            in_forecast=False,
        )
    return say(
        "Das Projekt liegt im Plan.",
        "Achte darauf, dass das Team seinen Fortschritt aktuell hält.",
        "durchfuehrung",
        in_forecast=True,
    )


def forecast_text(outlook: Forecast, deadline: date) -> str:
    """The forecast as one sentence, for the reports and the verdict lines."""
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
                    (
                        (f"fertig am {_date(t.finished_on)}" if t.finished_on else "fertig")
                        if t.status == "fertig"
                        else expected.get(t.id, "nicht berechenbar")
                    ),
                    t.status,
                    t.finished_on,
                    t.actual_hours,
                    t.remaining_hours,
                    t.note,
                ],
                strict=True,
            )
        )
        for t in evaluate(tracking, today).tasks
    ]


PART = "Teil, ging weiter"  # a started task whose rest went into the next plan


def history_rows(tracking: Tracking) -> list[dict[str, Any]]:
    """The work of earlier plans, one row per entry, for tables and documents."""
    return [
        {
            "ID": e.id,
            "Aufgabe": e.title,
            "Person": e.member,
            "Stand": "fertig" if e.finished else PART,
            "Plan (h)": e.planned_hours,
            "Ist (h)": e.actual_hours,
            "Notiz": e.note,
            "Bis": _date(e.until),
        }
        for e in tracking.history
    ]


def _history_text(tracking: Tracking) -> str:
    if not tracking.history:
        return "Keine: Der Plan wurde nicht neu übernommen."
    rows = [
        f"| {_md(r['ID'])} | {_md(r['Aufgabe'])} | {_md(r['Person'])} | {r['Stand']} | "
        f"{r['Plan (h)']:g} | {r['Ist (h)']:g} | {_md(r['Notiz'])} |"
        for r in history_rows(tracking)
    ]
    head = [
        "Arbeit aus früheren Plänen, in den Kennzahlen oben mitgezählt.",
        "",
        "| ID | Aufgabe | Person | Stand | Plan (h) | Ist (h) | Notiz |",
        "|---|---|---|---|---|---|---|",
    ]
    return "\n".join(head + rows)


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
        steps = "\n".join(
            f"- **{_md(step.task_id)}:** {_md(step.action)}" for step in summary.next_steps
        )
        note = "*Vorschlag des Durchführungs-Agenten, von der Projektleitung zu prüfen.*"
        # The summary keeps its paragraphs; only links, images and tags are made inert.
        text = "\n\n".join(filter(None, [_inert(summary.summary), steps, note]))
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
        f"- {_md(t.id)} · {_md(t.title)} ({_md(t.member)}), geplant bis "
        f"{_date(t.planned_end)}, Status: {t.status}"
        for t in evaluation.overdue
    ]
    return _fill(
        "statusbericht.md",
        projekt=_md(project.idea),
        stand=_date(evaluation.today),
        start=_date(project.start_date),
        deadline=_date(project.deadline),
        planende=_date(max(t.planned_end for t in tasks)),
        prognose=forecast_text(outlook, project.deadline),
        naechste="\n\n".join(
            filter(None, [_md(demo_this_week(tracking, evaluation.today) or ""), coming])
        ),
        fortschritt=percent(evaluation.progress),
        fertig=count["fertig"],
        in_arbeit=count["in Arbeit"],
        offen=count["offen"],
        plan_h=hours_text(evaluation.planned_hours),
        ist_h=hours_text(evaluation.actual_hours),
        abweichung=signed_hours(evaluation.finished_deviation),
        zusammenfassung=text,
        verzug="\n".join(overdue) or "Keine Aufgabe im Verzug.",
        aufgaben="\n".join(
            f"| {_md(t.id)} | {_md(t.title)} | {_md(t.member)} | {t.status} | "
            f"{hours_text(t.planned_hours)} | {hours_text(t.actual_hours)} | {_md(t.note)} |"
            for t in tasks
        ),
        frueher=_history_text(tracking),
        anforderungen=_requirements_text(tracking),
        risiken="\n".join(f"- {_md(r)}" for r in tracking.plan.risks) or "Keine Risiken erfasst.",
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
            "| Aufgaben | Maßnahme | Erwartete Wirkung (Agent) | Nachgerechnet (Python) |\n"
            f"|---|---|---|---|\n{measures}"
            if report.measures
            else "Keine Gegenmaßnahmen vorgeschlagen."
        )
        note = "*Vorschlag des Kontroll-Agenten, von der Projektleitung zu prüfen.*"
        judgement = "\n\n".join([f"**Bewertung:** {report.assessment}", findings, table, note])
    return _fill(
        "kontrollbericht.md",
        projekt=_md(project.idea),
        stand=_date(today),
        start=_date(project.start_date),
        deadline=_date(project.deadline),
        planende=_date(max(t.planned_end for t in evaluation.tasks)),
        prognose=forecast_text(outlook, project.deadline),
        fortschritt=percent(evaluation.progress),
        plan_h=hours_text(evaluation.planned_hours),
        ist_h=hours_text(evaluation.actual_hours),
        abweichung=signed_hours(evaluation.finished_deviation),
        kosten=cost,
        planwert=hours_text(value.planned),
        fertigwert=hours_text(value.earned),
        spi=index_text(value.schedule_index, NO_SCHEDULE_INDEX),
        cpi=index_text(value.cost_index, NO_COST_INDEX),
        verzug="\n".join(overdue) or "Keine Aufgabe im Verzug.",
        personen="\n".join(
            f"| {_md(row['Person'])} | {hours_text(row['Plan (h)'])} | "
            f"{hours_text(row['Ist (h)'])} | {hours_text(row['Fertig (Plan-h)'])} |"
            for row in evaluation.by_member
        ),
        frueher=_history_text(tracking),
        anforderungen=_requirements_text(tracking),
        bewertung=judgement,
        demos=_demos_text(tracking, today),
    )


def _requirements_text(tracking: Tracking) -> str:
    """The progress per requirement (requirement_progress) as a Markdown table."""
    rows = requirement_progress(tracking)
    if not rows:
        return "Keine Anforderungen mit dem Plan übernommen."
    head = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
    body = ["| " + " | ".join(_md(str(cell)) for cell in row.values()) + " |" for row in rows]
    return "\n".join(head + body)


def _demos_text(tracking: Tracking, today: date) -> str:
    """The demos of the plan with their retros, as a table for the control report."""
    if not tracking.plan.demos:
        return "Der Plan hat keine Wochen-Demos."
    retros = {r.monday: r for r in tracking.retros}
    weeks = _weeks(tracking)
    head = [
        "| Woche | Bis | Demo | Fertig | Gezeigt | Was ging schief | Ursache | Maßnahme |",
        "|---|---|---|---|---|---|---|---|",
    ]
    rows = []
    for row in demo_status(tracking, today):
        first = weeks.get(row["Woche"], (None, None))[0]
        retro = retros.get(monday(first)) if first else None
        notes = [retro.went_wrong, retro.cause, retro.measure] if retro else ["", "", ""]
        cells = [str(row["Woche"]), row["Bis"], row["Demo"], row["Fertig"], row["Gezeigt"]]
        cells += [note or "–" for note in notes]
        rows.append("| " + " | ".join(_md(cell) for cell in cells) + " |")
    return "\n".join(head + rows)


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
                    f"## {_md(task.id)} · {_md(task.title)}",
                    "",
                    "| | |",
                    "|---|---|",
                    f"| Verantwortlich | {_md(state.member)} |",
                    f"| Aufwand | {hours_text(task.estimate_hours)} h |",
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
        projekt=_md(project.idea),
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
        for path in (log_dir or agents.LOG_DIR).glob(f"{prefix}-*.json")  # read at call time
    ]
    runs = []
    for _, agent, path in sorted(paths, key=lambda item: item[0], reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("kein JSON-Objekt")
        except (OSError, ValueError) as err:
            # A log cut off while it was written. It stays in the overview with the reason;
            # its time and tokens are not known.
            runs.append(
                {
                    "Lauf": path.name,
                    "Agent": agent,
                    "Ergebnis": f"Protokoll unlesbar: {err}",
                    "Dauer (s)": None,
                    "Runden": None,
                    "Eingabe-Token": None,
                    "Ausgabe-Token": None,
                }
            )
            continue
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
