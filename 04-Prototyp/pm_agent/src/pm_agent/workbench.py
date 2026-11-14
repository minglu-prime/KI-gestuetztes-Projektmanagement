"""Everything the UI needs besides widgets: tables the project lead edits, local storage of
team data and run logs, and the export. No Streamlit in here, so all of it is unit-tested.

Files live next to the package (04-Prototyp/pm_agent/data and /logs), never in the working
directory, and both folders are git-ignored: they hold personal data.
"""

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pm_agent.agent import LOG_DIR
from pm_agent.models import Assignment, CheckResult, Member, Plan, Project, Task

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
