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
from pm_agent.models import Member, Plan, Project, StatusSummary
from pm_agent.planning import check_plan
from pm_agent.workbench import DATA_DIR, InputError, _cell, _date, _md, _reason

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
    "Status",
    "Ist (h)",
    "Notiz",
]


class Progress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status = "offen"
    actual_hours: float = Field(default=0, ge=0, allow_inf_nan=False)
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
        progress[task_id] = Progress(
            status=status, actual_hours=hours, note=_cell(row.get("Notiz"))
        )
    return tracking.model_copy(update={"progress": progress})


def evaluate(tracking: Tracking, today: date) -> Evaluation:
    schedule = check_plan(tracking.plan, tracking.team, tracking.project).schedule
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


def progress_rows(tracking: Tracking) -> list[dict[str, Any]]:
    """One row per task for the progress table. Only Status, Ist (h) and Notiz are edited."""
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
                    t.status,
                    t.actual_hours,
                    t.note,
                ],
                strict=True,
            )
        )
        for t in evaluate(tracking, date.today()).tasks
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
