"""Everything the UI needs besides widgets: tables the project lead edits, local storage of
team data and run logs, and the export. No Streamlit in here, so all of it is unit-tested.

Files live next to the package (04-Prototyp/pm_agent/data and /logs), never in the working
directory, and both folders are git-ignored: they hold personal data.
"""

import csv
import io
import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pm_agent.agent import LOG_DIR
from pm_agent.models import (
    Absence,
    Assignment,
    CheckResult,
    Member,
    Plan,
    Project,
    Task,
)
from pm_agent.planning import workday_shift

DATA_DIR = LOG_DIR.parent / "data"
TEAM_FILE = DATA_DIR / "team.json"
RUNS_CSV = LOG_DIR / "runs.csv"

TEAM_COLUMNS = ["Name", "Skills", "Stunden/Woche", "Abwesend", "Notiz"]
PLAN_COLUMNS = ["ID", "Aufgabe", "Person", "Stunden", "Abhängig von", "Skills", "Begründung"]
_SKILL = re.compile(r"^(.+?)\s*[: ]\s*([1-5])$")
_DAY = r"(\d{1,2}\.\d{1,2}\.\d{4})"
# One day, or two days with "-", "–" or "bis" between them.
_ABSENCE = re.compile(rf"^{_DAY}(?:\s*(?:-|–|bis)\s*{_DAY})?$")


class InputError(ValueError):
    """A table the project lead filled in cannot be read. The message is German."""


def team_rows(team: list[Member]) -> list[dict[str, Any]]:
    return [
        {
            "Name": m.name,
            "Skills": ", ".join(f"{skill} {level}" for skill, level in m.skills.items()),
            "Stunden/Woche": m.hours_per_week,
            "Abwesend": free_days_text(m.absences),
            "Notiz": m.note,
        }
        for m in team
    ]


def free_days(text: str) -> list[Absence]:
    """Days or ranges as typed: "24.12.2026–01.01.2027, 06.01.2027". The free days of the
    project in step 2 and the column "Abwesend" of the team are written the same way."""
    return _absences(text, what="")


def free_days_text(days: list[Absence]) -> str:
    """The way free_days reads them."""
    return ", ".join(
        _date(a.first) if a.first == a.last else f"{_date(a.first)}–{_date(a.last)}" for a in days
    )


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
                    absences=_absences(_cell(row.get("Abwesend"))),
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


def table_plan(plan: Plan) -> Plan:
    """The plan as the table gives it back when nobody has touched it. The table is not a
    mirror: assignments come back in task order, and a skill, a dependency or a risk with a
    separator in it (comma, line break) comes back in pieces. Whether the table was edited
    is decided against this form, not against the plan itself.

    A plan the table cannot give back at all (a title that reads as empty there) is its own
    form: every readable table then differs from it, and reading the table as it stands
    reports the row."""
    try:
        return rows_to_plan(plan_rows(plan), plan, "\n".join(plan.risks).splitlines())
    except InputError:
        return plan


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
    rows = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
    # The columns of the file, then what this row has on top. Written as a whole each time:
    # appending a line under a heading with other columns would put values under the wrong
    # name, and nobody would notice. The file has one line per export, so it stays small.
    columns = list(dict.fromkeys([*(rows[0] if rows else []), *row]))
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows([*rows, row])


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


def explain_task(
    plan: Plan, team: list[Member], result: CheckResult, task_id: str
) -> dict[str, Any]:
    """Everything about one task of a checked plan, for the project lead who asks "why this
    person, and what hangs on it?". `skills` pairs each required skill with the level the
    assigned person has (None: not named). `alternatives` are the other team members who
    have at least one of the required skills, best fit first; for a task without required
    skills, everyone else, least loaded first."""
    tasks = {task.id: task for task in plan.tasks}
    task = tasks[task_id]
    assignment = next(a for a in plan.assignments if a.task_id == task_id)
    dates = next(s for s in result.schedule if s.task_id == task_id)
    load = {item.member: item.utilization for item in result.load}

    def levels(member: Member) -> dict[str, int]:
        """The member's level for each required skill they have, in the task's spelling."""
        known = {skill.casefold(): level for skill, level in member.skills.items()}
        return {
            skill: known[skill.casefold()]
            for skill in task.required_skills
            if skill.casefold() in known
        }

    assigned = next(m for m in team if m.name == assignment.member)
    has = levels(assigned)
    others = [(m, levels(m)) for m in team if m.name != assigned.name]
    if task.required_skills:
        others = [(m, fit) for m, fit in others if fit]
    others.sort(
        key=lambda pair: (
            -len(pair[1]),
            -sum(pair[1].values()),
            # No utilisation: away until the deadline. Such a person comes last.
            math.inf if load[pair[0].name] is None else load[pair[0].name],
            pair[0].name,
        )
    )
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "member": assignment.member,
        "reason": assignment.reason,
        "hours": task.estimate_hours,
        "start": dates.start,
        "end": dates.end,
        "skills": [(skill, has.get(skill)) for skill in task.required_skills],
        "depends_on": [(dep, tasks[dep].title) for dep in task.depends_on],
        "needed_by": [(t.id, t.title) for t in plan.tasks if task_id in t.depends_on],
        # No slack, not membership in critical_path: the last task of that chain can have
        # a whole day of room when its days are not full.
        "critical": result.slack[task_id] == 0,
        "slack": result.slack[task_id],
        "alternatives": [
            {"member": m.name, "skills": fit, "utilization": load[m.name]} for m, fit in others
        ],
    }


def suggested_wishes(
    plan: Plan, team: list[Member], result: CheckResult, project: Project
) -> list[str]:
    """Up to four things the project lead could ask Claude to change, read off the check of
    the plan: what is most pressing first. Nothing for a plan with errors."""
    if result.errors or result.end_date is None:
        return []
    tasks = {task.id: task for task in plan.tasks}
    owner = {a.task_id: a.member for a in plan.assignments}
    wishes = []
    if result.end_date > project.deadline:
        wishes.append(f"Der Plan soll spätestens am {_date(project.deadline)} enden.")
    elif workday_shift(result.end_date, project.deadline) == 0:
        wishes.append("Schaffe vor der Deadline mindestens zwei Arbeitstage Puffer.")
    loads = [item for item in result.load if item.utilization is not None]
    for item in loads:
        if round(item.utilization, 9) > 1:
            wishes.append(
                f"Entlaste {item.member}: Bis zur Deadline ist mehr zugewiesen als verfügbar."
            )
            break
    # A task whose person has not named a required skill, while someone else has.
    skills = {m.name: {s.casefold(): level for s, level in m.skills.items()} for m in team}
    for task in plan.tasks:
        missing = [s for s in task.required_skills if s.casefold() not in skills[owner[task.id]]]
        able = [
            (skills[m.name][skill.casefold()], m.name)
            for skill in missing[:1]
            for m in team
            if skill.casefold() in skills[m.name]
        ]
        if able:
            best = max(able)[1]
            wishes.append(
                f"Gib {task.id} ({task.title}) an {best}: {best} hat {missing[0]} angegeben."
            )
            break
    if len(loads) > 1:
        busiest = max(loads, key=lambda item: item.utilization)
        idlest = min(loads, key=lambda item: item.utilization)
        if busiest.utilization - idlest.utilization >= 0.3:
            wishes.append(f"Verteile Arbeit von {busiest.member} auf {idlest.member} um.")
    if result.critical_path:
        longest = max(result.critical_path, key=lambda tid: tasks[tid].estimate_hours)
        wishes.append(f"Was, wenn {longest} ({tasks[longest].title}) doppelt so lange dauert?")
    return wishes[:4]


def pair_tasks(before: Plan, after: Plan) -> dict[str, str]:
    """Which task of `after` is which task of `before`: ID in before -> ID in after.

    Paired by ID and title, then by title alone, then by ID alone. Claude sometimes renumbers
    a draft; paired by ID only, every task after an inserted one would count as renamed and
    reassigned. A title pairs two tasks only if it is unique in both plans: with two tasks
    called the same, nothing says which is which."""
    old = {task.id: task for task in before.tasks}
    new = {task.id: task for task in after.tasks}

    def unique(plan: Plan) -> dict[str, str]:
        titles = [task.title for task in plan.tasks]
        return {task.title: task.id for task in plan.tasks if titles.count(task.title) == 1}

    old_titles, new_titles = unique(before), unique(after)
    twin: dict[str, str] = {}
    for tid, task in old.items():
        if tid in new and new[tid].title == task.title:
            twin[tid] = tid
    for tid, task in old.items():  # renumbered
        other = new_titles.get(task.title)
        if (
            tid not in twin
            and task.title in old_titles
            and other is not None
            and other not in twin.values()
        ):
            twin[tid] = other
    for tid in old:  # renamed
        if tid not in twin and tid in new and tid not in twin.values():
            twin[tid] = tid
    return twin


def plan_changes(before: Plan, after: Plan) -> list[str]:
    """What differs between two plans, one line per change, for the project lead. Reasons of
    assignments and descriptions are left out: they do not change what is planned. Which
    task is which decides pair_tasks."""
    old = {task.id: task for task in before.tasks}
    new = {task.id: task for task in after.tasks}
    twin = pair_tasks(before, after)
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
        # The dependencies of before, in the IDs of after. A dependency on a removed task
        # is marked: its ID may have gone to another task, and would then look unchanged.
        # A dependency on an ID that `before` never had is a mistake of the draft, not a
        # removed task: it stays as it is.
        needed = [
            twin[dep] if dep in twin else f"{dep} [entfernt]" if dep in old else dep
            for dep in was.depends_on
        ]
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
    # The tasks that are in both plans, in the IDs of after: do they stand in the same order?
    if [twin[t.id] for t in before.tasks if t.id in twin] != [
        t.id for t in after.tasks if t.id in origin
    ]:
        lines.append(
            "Reihenfolge der Aufgaben geändert: Können zwei Aufgaben gleichzeitig beginnen, "
            "wird zuerst eingeplant, was weiter oben steht"
        )
    lines += [f"Neues Risiko: {risk}" for risk in after.risks if risk not in before.risks]
    lines += [f"Risiko entfällt: {risk}" for risk in before.risks if risk not in after.risks]
    return lines


def check_changes(
    before: CheckResult, after: CheckResult, pairs: dict[str, str] | None = None
) -> list[str]:
    """What a change of the plan does to its check: end date, warnings, moved dates.

    `pairs` (pair_tasks) says which task of before is which task of after. Without it tasks
    are the same if their IDs are."""
    if pairs is None:
        kept = {s.task_id for s in after.schedule}
        pairs = {s.task_id: s.task_id for s in before.schedule if s.task_id in kept}

    now = dict(zip(after.warning_kinds, after.warnings, strict=True))
    # The warnings of before, with task IDs in the IDs of after. A warning about a task that
    # is gone went with it: plan_changes names the task, and its ID may belong to another
    # task now.
    was = {}
    for kind, text in zip(before.warning_kinds, before.warnings, strict=True):
        if kind[0] == "skill":
            if kind[1] not in pairs:
                continue
            kind = ("skill", pairs[kind[1]], kind[2])
        was[kind] = text
    lines = []
    if before.end_date and after.end_date and before.end_date != after.end_date:
        shift = workday_shift(before.end_date, after.end_date)
        days, direction = abs(shift), "später" if shift > 0 else "früher"
        lines.append(
            f"Planende: {_date(before.end_date)} → {_date(after.end_date)} "
            f"({days} Arbeitstag{'' if days == 1 else 'e'} {direction})"
        )
    lines += [f"Fehler: {error}" for error in after.errors if error not in before.errors]
    # By kind, not by text: "5 Arbeitstage nach der Deadline" that became 3 is the same
    # warning with another number, not one solved and a new one.
    for kind, text in now.items():
        if kind not in was:
            lines.append(f"Neue Warnung: {text}")
        elif text != was[kind] and kind[0] != "skill":
            lines.append(f"Warnung bleibt: {text}")
    lines += [f"Behoben: {text}" for kind, text in was.items() if kind not in now]
    dates = {pairs[s.task_id]: (s.start, s.end) for s in before.schedule if s.task_id in pairs}
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


def bar_end(last_day: date) -> date:
    """Where a bar that covers `last_day` ends on a time axis, and where the line of a
    deadline on that day is drawn.

    The axis marks the start of each day. A bar covers whole days, so it runs to the start
    of the day after its last day. The deadline day is a working day too, so its line sits
    at the end of the day the same way. Drawn at its start, a task finishing on the deadline
    looked late. The last day of the calendar has no day after it and stays where it is."""
    return last_day if last_day == date.max else last_day + timedelta(days=1)


def gantt(plan: Plan, result: CheckResult, deadline: date) -> tuple[list[dict[str, Any]], date]:
    """The bars of the Gantt chart and where the deadline line is drawn (see bar_end)."""
    titles = {t.id: t.title for t in plan.tasks}
    bars = [
        {
            "Aufgabe": f"{s.task_id} · {titles[s.task_id]}",
            "Person": s.member,
            "Start": s.start,
            "Ende": bar_end(s.end),
            "Zeitraum": f"{s.start:%d.%m.} – {s.end:%d.%m.}",
            "Kritisch": result.slack[s.task_id] == 0,
            "Puffer": result.slack[s.task_id],
        }
        for s in result.schedule
    ]
    return bars, bar_end(deadline)


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


def _absences(text: str, what: str = "Abwesenheit ") -> list[Absence]:
    absences = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        match = _ABSENCE.match(part)
        try:
            days = [datetime.strptime(day, "%d.%m.%Y").date() for day in match.groups() if day]
        except (AttributeError, ValueError):  # no match, or a date like 31.02.
            raise InputError(
                f"{what}'{part}' nicht lesbar, erwartet zum Beispiel "
                "'01.12.2026–05.12.2026' oder '23.12.2026'"
            ) from None
        absences.append(Absence(first=days[0], last=days[-1]))
    return absences


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
    """Text for one table cell or one list item: no column separator, on one line."""
    return " ".join(text.replace("|", "\\|").split())
