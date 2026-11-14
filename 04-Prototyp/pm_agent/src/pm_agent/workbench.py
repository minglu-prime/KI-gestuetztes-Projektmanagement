"""Everything the UI needs besides widgets: tables the project lead edits, local storage of
team data and run logs, and the export. No Streamlit in here, so all of it is unit-tested.

Files live next to the package (04-Prototyp/pm_agent/data and /logs), never in the working
directory, and both folders are git-ignored: they hold personal data.
"""

import csv
import io
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pm_agent.agent import LOG_DIR
from pm_agent.models import Assignment, CheckResult, Member, Plan, Project, Task
from pm_agent.planning import workday_shift

DATA_DIR = LOG_DIR.parent / "data"
TEAM_FILE = DATA_DIR / "team.json"
RUNS_CSV = LOG_DIR / "runs.csv"

TEAM_COLUMNS = ["Name", "Skills", "Stunden/Woche", "Notiz"]
PLAN_COLUMNS = ["ID", "Aufgabe", "Person", "Stunden", "Abhängig von", "Skills", "Begründung"]
_SKILL = re.compile(r"^(.+?)\s*[: ]\s*([1-5])$")


class InputError(ValueError):
    """A table the project lead filled in cannot be read. The message is German."""


def team_rows(team: list[Member]) -> list[dict[str, Any]]:
    return [
        {
            "Name": m.name,
            "Skills": ", ".join(f"{skill} {level}" for skill, level in m.skills.items()),
            "Stunden/Woche": m.hours_per_week,
            "Notiz": m.note,
        }
        for m in team
    ]


def rows_to_team(rows: list[dict[str, Any]]) -> list[Member]:
    """Rows without a name are ignored, so an empty last row of the editor does no harm."""
    team, errors = [], []
    for number, row in enumerate(rows, start=1):
        name = _cell(row.get("Name"))
        if not name:
            continue
        try:
            team.append(
                Member(
                    name=name,
                    skills=_skills(_cell(row.get("Skills"))),
                    hours_per_week=row.get("Stunden/Woche"),
                    note=_cell(row.get("Notiz")),
                )
            )
        except (InputError, ValidationError) as err:
            errors.append(f"Zeile {number} ({name}): {_reason(err)}")
    if errors:
        raise InputError("\n".join(errors))
    return team


def plan_rows(plan: Plan) -> list[dict[str, Any]]:
    owner = {a.task_id: a for a in plan.assignments}
    return [
        {
            "ID": t.id,
            "Aufgabe": t.title,
            "Person": owner[t.id].member if t.id in owner else "",
            "Stunden": t.estimate_hours,
            "Abhängig von": ", ".join(t.depends_on),
            "Skills": ", ".join(t.required_skills),
            "Begründung": owner[t.id].reason if t.id in owner else "",
        }
        for t in plan.tasks
    ]


def rows_to_plan(rows: list[dict[str, Any]], original: Plan, risks: list[str]) -> Plan:
    """The edited table as a plan. Descriptions are not in the table and come from the
    original plan. A row without a person stays unassigned, which check_plan reports."""
    descriptions = {t.id: t.description for t in original.tasks}
    tasks, assignments, errors = [], [], []
    for number, row in enumerate(rows, start=1):
        task_id = _cell(row.get("ID"))
        if not task_id and not _cell(row.get("Aufgabe")):
            continue
        try:
            tasks.append(
                Task(
                    id=task_id,
                    title=_cell(row.get("Aufgabe")),
                    description=descriptions.get(task_id, ""),
                    required_skills=_list(row.get("Skills")),
                    estimate_hours=row.get("Stunden"),
                    depends_on=_list(row.get("Abhängig von")),
                )
            )
            if _cell(row.get("Person")):
                assignments.append(
                    Assignment(
                        task_id=task_id,
                        member=_cell(row.get("Person")),
                        reason=_cell(row.get("Begründung")) or "Von der Projektleitung zugewiesen",
                    )
                )
        except ValidationError as err:
            errors.append(f"Zeile {number} ({task_id or 'ohne ID'}): {_reason(err)}")
    if errors:
        raise InputError("\n".join(errors))
    try:
        return Plan(tasks=tasks, assignments=assignments, risks=[r for r in risks if r.strip()])
    except ValidationError as err:
        raise InputError(_reason(err)) from err


def load_team(path: Path = TEAM_FILE) -> list[Member]:
    """An empty team if nothing was saved yet. A damaged file is an error, not an empty team."""
    if not path.exists():
        return []
    try:
        return [Member.model_validate(m) for m in json.loads(path.read_text(encoding="utf-8"))]
    except (ValueError, ValidationError) as err:
        raise InputError(f"{path.name} ist beschädigt: {_reason(err)}") from err


def save_team(team: list[Member], path: Path = TEAM_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [m.model_dump(mode="json") for m in team]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def saved_runs(log_dir: Path = LOG_DIR) -> list[Path]:
    """Logged runs that ended with a plan and can be reopened, newest first."""
    runs = []
    for path in sorted(log_dir.glob("run-*.json"), reverse=True):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("plan") and record.get("project") and record.get("team"):
            runs.append(path)
    return runs


def load_run(path: Path) -> tuple[Project, list[Member], Plan, dict[str, Any]]:
    record = json.loads(path.read_text(encoding="utf-8"))
    team = [Member.model_validate(m) for m in record["team"]]
    return (
        Project.model_validate(record["project"]),
        team,
        Plan.model_validate(record["plan"]),
        record,
    )


def append_run(row: dict[str, Any], path: Path = RUNS_CSV) -> None:
    """One line per exported plan in runs.csv: the data for the before/after comparison."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(row))
        if new:
            writer.writeheader()
        writer.writerow(row)


def round_summary(number: int, record: dict[str, Any]) -> tuple[str, list[str]]:
    """One line per agent round for the progress view, plus the messages the tools returned."""
    parts, messages = [], []
    for result in record.get("tool_results", []):
        tool, content = result["tool"], result["content"]
        if result["is_error"]:
            rejected = (tool or "").startswith("submit_")
            parts.append(f"{tool}: abgelehnt" if rejected else f"{tool}: Fehler")
            messages.append(content)
        elif tool == "check_plan":
            report = json.loads(content)
            parts.append(
                f"check_plan: {len(report['errors'])} Fehler, {len(report['warnings'])} Warnungen"
            )
            messages += report["errors"] + report["warnings"]
        else:
            parts.append(f"{tool}: {content}")
    headline = "; ".join(parts) or record.get("text") or f"beendet ({record.get('stop_reason')})"
    return f"Runde {number} · {headline}", messages


def plan_changes(before: Plan, after: Plan) -> list[str]:
    """What differs between two plans, one line per change, for the project lead. Reasons of
    assignments and descriptions are left out: they do not change what is planned.

    Tasks are paired by ID and title, then by title alone, then by ID alone. Claude sometimes
    renumbers a draft; paired by ID only, every task after an inserted one would count as
    renamed and reassigned."""
    old = {task.id: task for task in before.tasks}
    new = {task.id: task for task in after.tasks}
    by_title = {task.title: task.id for task in after.tasks}
    twin: dict[str, str] = {}  # ID in `before` -> ID of the same task in `after`
    for tid, task in old.items():
        if tid in new and new[tid].title == task.title:
            twin[tid] = tid
    for tid, task in old.items():  # renumbered
        other = by_title.get(task.title)
        if tid not in twin and other is not None and other not in twin.values():
            twin[tid] = other
    for tid in old:  # renamed
        if tid not in twin and tid in new and tid not in twin.values():
            twin[tid] = tid
    origin = {new_id: old_id for old_id, new_id in twin.items()}

    old_owner = {a.task_id: a.member for a in before.assignments}
    new_owner = {a.task_id: a.member for a in after.assignments}
    lines = [
        f"Neu: {tid} · {task.title} ({new_owner.get(tid, 'niemand')}, {task.estimate_hours:g} h)"
        for tid, task in new.items()
        if tid not in origin
    ]
    lines += [f"Entfernt: {tid} · {task.title}" for tid, task in old.items() if tid not in twin]
    for tid, task in new.items():
        if tid not in origin:
            continue
        old_id = origin[tid]
        was, parts = old[old_id], []
        # The dependencies of before, in the IDs of after.
        needed = [twin.get(dep, dep) for dep in was.depends_on]
        if task.title != was.title:
            parts.append(f"heißt jetzt „{task.title}“")
        if old_owner.get(old_id) != new_owner.get(tid):
            parts.append(f"{old_owner.get(old_id, 'niemand')} → {new_owner.get(tid, 'niemand')}")
        if task.estimate_hours != was.estimate_hours:
            parts.append(f"{was.estimate_hours:g} h → {task.estimate_hours:g} h")
        if set(task.depends_on) != set(needed):
            parts.append(
                f"hängt ab von {', '.join(task.depends_on) or 'nichts'} "
                f"(vorher {', '.join(needed) or 'nichts'})"
            )
        if set(task.required_skills) != set(was.required_skills):
            parts.append(
                f"braucht {', '.join(task.required_skills) or 'keine Skills'} "
                f"(vorher {', '.join(was.required_skills) or 'keine Skills'})"
            )
        if parts:
            label = tid if tid == old_id else f"{tid} (vorher {old_id})"
            lines.append(f"{label} · {was.title}: " + "; ".join(parts))
    renumbered = sum(old_id != new_id for old_id, new_id in twin.items())
    if renumbered:
        subject = "Eine Aufgabe hat" if renumbered == 1 else f"{renumbered} Aufgaben haben"
        lines.append(f"{subject} eine neue ID")
    lines += [f"Neues Risiko: {risk}" for risk in after.risks if risk not in before.risks]
    lines += [f"Risiko entfällt: {risk}" for risk in before.risks if risk not in after.risks]
    return lines


def check_changes(before: CheckResult, after: CheckResult) -> list[str]:
    """What a change of the plan does to its check: end date, warnings, moved dates."""
    lines = []
    if before.end_date and after.end_date and before.end_date != after.end_date:
        shift = workday_shift(before.end_date, after.end_date)
        days, direction = abs(shift), "später" if shift > 0 else "früher"
        lines.append(
            f"Planende: {_date(before.end_date)} → {_date(after.end_date)} "
            f"({days} Arbeitstag{'' if days == 1 else 'e'} {direction})"
        )
    lines += [f"Fehler: {error}" for error in after.errors if error not in before.errors]
    lines += [f"Neue Warnung: {w}" for w in after.warnings if w not in before.warnings]
    lines += [f"Behoben: {w}" for w in before.warnings if w not in after.warnings]
    dates = {s.task_id: (s.start, s.end) for s in before.schedule}
    moved = sum(s.task_id in dates and dates[s.task_id] != (s.start, s.end) for s in after.schedule)
    if moved:
        subject = "einer Aufgabe verschieben" if moved == 1 else f"{moved} Aufgaben verschieben"
        lines.append(f"Termine von {subject} sich")
    return lines


def describe_round(number: int, record: dict[str, Any], previous: Plan | None) -> dict[str, Any]:
    """One agent round for the progress view: the headline and tool messages of
    round_summary, what Claude wrote, the size of the draft it checked or submitted, and what
    it changed since `previous` (the draft of the round before, or the plan it started from).
    `draft` is None if the round had no readable plan; the caller then keeps `previous`."""
    headline, messages = round_summary(number, record)
    draft = None
    for call in reversed(record.get("tool_calls", [])):
        try:
            draft = Plan.model_validate(call["input"])
        except ValidationError:
            continue  # not hidden: the tool rejected this input, its message is in `messages`
        break
    return {
        "headline": headline,
        "said": record.get("text", ""),
        "draft": draft,
        "size": (
            f"{len(draft.tasks)} Aufgaben, {sum(t.estimate_hours for t in draft.tasks):g} h"
            if draft
            else ""
        ),
        "changes": plan_changes(previous, draft) if previous and draft else [],
        "messages": messages,
    }


def gantt(plan: Plan, result: CheckResult, deadline: date) -> tuple[list[dict[str, Any]], date]:
    """The bars of the Gantt chart and where the deadline line is drawn.

    The time axis marks the start of each day. A bar covers whole days, so it runs to the
    start of the day after the task's last day. The deadline day is a working day too, so
    the line sits at its end the same way. Drawn at its start, a task finishing on the
    deadline looked late."""
    day = timedelta(days=1)
    titles = {t.id: t.title for t in plan.tasks}
    bars = [
        {
            "Aufgabe": f"{s.task_id} · {titles[s.task_id]}",
            "Person": s.member,
            "Start": s.start,
            "Ende": s.end + day,
            "Zeitraum": f"{s.start:%d.%m.} – {s.end:%d.%m.}",
        }
        for s in result.schedule
    ]
    return bars, deadline + day


def to_markdown(project: Project, plan: Plan, result: CheckResult) -> str:
    owner = {a.task_id: a for a in plan.assignments}
    dates = {s.task_id: s for s in result.schedule}
    lines = [
        "# Projektplan",
        "",
        f"**Projekt:** {project.idea}  ",
        f"**Zeitraum:** {_date(project.start_date)} bis {_date(project.deadline)}  ",
        f"**Planende:** {_date(result.end_date) if result.end_date else 'nicht berechenbar'}",
        "",
        "## Aufgaben",
        "",
        "| ID | Aufgabe | Person | Stunden | Start | Ende | Begründung |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in plan.tasks:
        s, a = dates.get(t.id), owner.get(t.id)
        lines.append(
            f"| {t.id} | {_md(t.title)} | {a.member if a else ''} | {t.estimate_hours:g} | "
            f"{_date(s.start) if s else ''} | {_date(s.end) if s else ''} | "
            f"{_md(a.reason) if a else ''} |"
        )
    if result.critical_path:
        lines += ["", f"**Kritischer Pfad:** {' → '.join(result.critical_path)}"]
    for title, items in (
        ("Fehler", result.errors),
        ("Warnungen", result.warnings),
        ("Risiken", plan.risks),
    ):
        if items:
            lines += ["", f"## {title}", ""] + [f"- {item}" for item in items]
    return "\n".join(lines) + "\n"


def to_csv(plan: Plan, result: CheckResult) -> str:
    dates = {s.task_id: s for s in result.schedule}
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")  # semicolon: German Excel splits it into columns
    writer.writerow(PLAN_COLUMNS[:6] + ["Start", "Ende", "Begründung"])
    for row in plan_rows(plan):
        s = dates.get(row["ID"])
        writer.writerow(
            [row[c] for c in PLAN_COLUMNS[:6]]
            + [_date(s.start) if s else "", _date(s.end) if s else "", row["Begründung"]]
        )
    return out.getvalue()


def _skills(text: str) -> dict[str, int]:
    skills = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        match = _SKILL.match(part)
        if not match:
            raise InputError(f"Skill '{part}' nicht lesbar, erwartet zum Beispiel 'Python 4'")
        skills[match[1]] = int(match[2])
    return skills


def _list(value: Any) -> list[str]:
    return [p.strip() for p in _cell(value).split(",") if p.strip()]


def _cell(value: Any) -> str:
    # The table editor gives None (or NaN) for empty cells.
    return "" if value is None or value != value else str(value).strip()


def _reason(err: Exception) -> str:
    if isinstance(err, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'Eingabe'}: {e['msg']}" for e in err.errors()
        )
    return str(err)


def _date(day: Any) -> str:
    return day.strftime("%d.%m.%Y")


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
