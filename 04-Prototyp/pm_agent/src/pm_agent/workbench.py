"""Everything the UI needs besides widgets: tables the project lead edits, local storage of
team data and run logs, and the export. No Streamlit in here, so all of it is unit-tested.

Files live next to the package (04-Prototyp/pm_agent/data and /logs), never in the working
directory, and both folders are git-ignored: they hold personal data.
"""

import csv
import io
import json
import math
import os
import re
import threading
from datetime import date, datetime, timedelta
from itertools import islice
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pm_agent.agent import LOG_DIR
from pm_agent.models import (
    Absence,
    Assignment,
    CheckResult,
    Member,
    MemberAbsence,
    Plan,
    Project,
    Requirement,
    Task,
)
from pm_agent.planning import check_plan, project_weeks, workday_shift, working_shift
from pm_agent.tools import german, with_absences

DATA_DIR = LOG_DIR.parent / "data"
TEAM_FILE = DATA_DIR / "team.json"
RUNS_CSV = LOG_DIR / "runs.csv"

TEAM_COLUMNS = ["Name", "Skills", "Stunden/Woche", "Abwesend", "Notiz"]
PLAN_COLUMNS = [
    "ID",
    "Aufgabe",
    "Person",
    "Stunden",
    "Abhängig von",
    "Skills",
    "Anforderungen",
    "Begründung",
]
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
            "Anforderungen": ", ".join(t.requirement_ids),
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
                    requirement_ids=_list(row.get("Anforderungen")),
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
        return Plan(
            tasks=tasks,
            assignments=assignments,
            risks=[r for r in risks if r.strip()],
            # Not in the table, like the descriptions. A task removed there leaves its
            # demos; a demo left with no task goes.
            demos=[
                demo.model_copy(update={"task_ids": kept})
                for demo in original.demos
                if (kept := [t for t in demo.task_ids if t in {task.id for task in tasks}])
            ],
        )
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


def load_team(path: Path | None = None) -> list[Member]:
    """An empty team if nothing was saved yet. A damaged file is an error, not an empty team."""
    path = path or TEAM_FILE  # read at call time: scripts and tests point it elsewhere
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:  # locked, no permission, a folder of that name
        raise InputError(f"{path.name} konnte nicht gelesen werden: {err}") from err
    try:
        return [Member.model_validate(m) for m in json.loads(text)]
    except (ValueError, ValidationError) as err:
        raise InputError(f"{path.name} ist beschädigt: {_reason(err)}") from err


def save_team(team: list[Member], path: Path | None = None) -> None:
    path = path or TEAM_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [m.model_dump(mode="json") for m in team]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def saved_runs(log_dir: Path | None = None) -> list[Path]:
    """Logged runs that ended with a plan and can be reopened, newest first."""
    log_dir = log_dir or LOG_DIR
    runs = []
    for path in sorted(log_dir.glob("run-*.json"), reverse=True):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("plan") and record.get("project") and record.get("team"):
            runs.append(path)
    return runs


def load_run(path: Path) -> tuple[Project, list[Member], Plan, dict[str, Any]]:
    record = json.loads(path.read_text(encoding="utf-8"))
    team = [Member.model_validate(m) for m in record["team"]]
    absences = [MemberAbsence.model_validate(a) for a in record.get("absences", [])]
    return (
        Project.model_validate(record["project"]),
        with_absences(team, absences),
        Plan.model_validate(record["plan"]),
        record,
    )


# One export at a time: every browser session runs in a thread of its own, and two lines
# appended at the same moment can write over each other. Within this server only; two
# servers on one logs folder are not kept apart.
_RECORD_LOCK = threading.Lock()


def append_run(row: dict[str, Any], path: Path | None = None) -> None:
    """One line per exported plan in runs.csv: the data for the before/after comparison.

    The file is only ever appended to, and only if it is a clean record: readable as UTF-8,
    every line as long as the heading, and the heading has the columns of the row. Then the
    line goes below, in the order of the heading. Any other file (other separator or
    encoding, a line with too many cells, an open quote, an older set of columns) is put
    aside as it is, under a name with the time, and a new file begins. Nothing in an
    existing file is rewritten, so nothing in it can be lost or end up under another
    heading.

    Raises ValueError (UnicodeEncodeError) if the row cannot be written, before any file is
    touched, and OSError if a file cannot be. After an OSError every line is still there,
    in runs.csv or, if the old file was already put aside, in that file."""
    path = path or RUNS_CSV  # read at call time: tests point it to a temporary folder
    path.parent.mkdir(parents=True, exist_ok=True)
    with _RECORD_LOCK:
        old = path.read_bytes() if path.exists() else b""
        heading = _record_heading(old)
        fits = heading is not None and set(row) <= set(heading)
        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=heading if fits else list(row), restval="")
        if not fits:
            writer.writeheader()
        elif old[-1:] not in (b"\n", b"\r"):  # the new line must not continue the last one
            text.write("\r\n")
        writer.writerow(row)
        line = text.getvalue().encode("utf-8")  # fails here, before any file is touched
        if not fits and not _is_blank(old):
            _put_aside(path)
        with path.open("ab" if fits else "wb") as file:
            file.write(line)  # in one piece


def read_runs(path: Path | None = None) -> list[dict[str, str]]:
    """The lines of runs.csv, one dict per export; [] if there is no file or nothing in it.
    Read with the check append_run writes with, so that a table never shows a file with
    cells left out or shifted. Raises InputError if the file is not a clean record."""
    path = path or RUNS_CSV
    content = path.read_bytes() if path.exists() else b""
    if _is_blank(content):
        return []
    if _record_heading(content) is None:
        raise InputError(
            "kein sauberes Protokoll (andere Kodierung, ein offenes Anführungszeichen oder "
            "eine Zeile mit mehr oder weniger Zellen als die Kopfzeile)"
        )
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline="")))


def _is_blank(content: bytes) -> bool:
    """Nothing in it but a byte order mark and white space: nothing to keep."""
    try:
        return not content.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        return False


def _record_heading(content: bytes) -> list[str] | None:
    """The heading of a clean record, None for anything append_run must not append to."""
    try:
        lines = list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error):  # another encoding; an open quote, a huge cell
        return None
    if not lines or not lines[0]:
        return None
    if "" in lines[0] or len(set(lines[0])) != len(lines[0]):
        return None  # read by name, a column without one or with a double would hide values
    if any(line and len(line) != len(lines[0]) for line in lines):  # blank lines are fine
        return None
    return lines[0]


def _put_aside(path: Path) -> None:
    """Give the file a name with the time, so that its place is free. The file itself is
    moved, not a copy of what was read: a line that another server appended in between goes
    with it. And never onto a name that exists, also not one that another server took in
    the same second."""
    stamp, number = datetime.now().strftime("%Y%m%d-%H%M%S"), 1
    while True:
        count = "" if number == 1 else f"-{number}"
        aside = path.with_name(f"{path.stem}-bis-{stamp}{count}{path.suffix}")
        try:
            _move(path, aside)
            return
        except FileExistsError:
            number += 1


def _rename(source: Path, target: Path) -> None:
    """Windows only: there a rename refuses a name that exists."""
    os.rename(source, target)


def _link_and_unlink(source: Path, target: Path) -> None:
    """Elsewhere a rename writes over an existing file. A hard link refuses the name."""
    os.link(source, target)
    try:
        source.unlink()
    except OSError:
        target.unlink()  # one file under two names would be put aside twice
        raise


# The move of _put_aside: never onto a name that exists.
_move = _rename if os.name == "nt" else _link_and_unlink


def put_aside(path: Path | None = None) -> list[str]:
    """The names of the files append_run has put aside, oldest first."""
    path = path or RUNS_CSV
    if not path.parent.is_dir():  # no logs folder yet: nothing was ever written
        return []
    name = re.compile(
        rf"{re.escape(path.stem)}-bis-(\d{{8}}-\d{{6}})(?:-(\d+))?{re.escape(path.suffix)}"
    )
    found = []
    for file in path.parent.iterdir():
        match = name.fullmatch(file.name)
        if match and file.is_file():
            found.append((match[1], int(match[2] or 1), file.name))
    return [file for _, _, file in sorted(found)]


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
    elif working_shift(project, result.end_date, project.deadline) == 0:
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
    # A task without dependents listed before a critical one of the same person can delay the end.
    # One check per critical task: moving it to the front does not depend on which task it passes.
    for index, critical in enumerate(plan.tasks):
        if result.slack.get(critical.id) != 0:
            continue
        earlier = next(
            (
                t
                for t in plan.tasks[:index]
                if owner[t.id] == owner[critical.id] and t.id not in critical.depends_on
            ),
            None,
        )
        if earlier is None:
            continue
        reordered = [critical, *(t for t in plan.tasks if t.id != critical.id)]
        checked = check_plan(
            plan.model_copy(update={"tasks": reordered}), team, project, dates_only=True
        )
        if checked.end_date is not None and checked.end_date < result.end_date:
            before = set(result.order[: result.order.index(critical.id)])
            after = set(checked.order[checked.order.index(critical.id) + 1 :])
            earlier = next(
                (
                    t
                    for t in plan.tasks[:index]
                    if owner[t.id] == owner[critical.id] and t.id in before & after
                ),
                earlier,
            )
            wishes.append(
                f"Zieh {critical.id} ({critical.title}) vor {earlier.id} ({earlier.title}): "
                "Das verkürzt den Plan."
            )
            break
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
        if set(task.requirement_ids) != set(was.requirement_ids):
            parts.append(
                f"dient {', '.join(task.requirement_ids) or 'keiner Anforderung'} "
                f"(vorher {', '.join(was.requirement_ids) or 'keiner Anforderung'})"
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
    return lines + _demo_changes(before, after)


def _demo_changes(before: Plan, after: Plan) -> list[str]:
    old = {d.week: d for d in before.demos}
    new = {d.week: d for d in after.demos}
    lines = [
        f"Neue Demo in Woche {w}: {d.title} ({', '.join(d.task_ids)})"
        for w, d in new.items()
        if w not in old
    ]
    lines += [f"Demo der Woche {w} entfällt: {d.title}" for w, d in old.items() if w not in new]
    for week, demo in new.items():
        was = old.get(week)
        if was is None:
            continue
        parts = []
        if demo.title != was.title:
            parts.append(f"heißt jetzt „{demo.title}“")
        if demo.task_ids != was.task_ids:
            parts.append(
                f"braucht jetzt {', '.join(demo.task_ids)} (vorher {', '.join(was.task_ids)})"
            )
        if parts:
            lines.append(f"Demo der Woche {week} ({was.title}): " + "; ".join(parts))
    return lines


def check_changes(
    before: CheckResult,
    after: CheckResult,
    pairs: dict[str, str] | None = None,
    project: Project | None = None,
) -> list[str]:
    """What a change of the plan does to its check: end date, warnings, moved dates.

    `pairs` (pair_tasks) says which task of before is which task of after. Without it tasks
    are the same if their IDs are. With `project` the end moves in working days of the
    project; without it, in Mon-Fri days, free days included."""
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
        if project is None:
            shift = workday_shift(before.end_date, after.end_date)
        else:
            shift = working_shift(project, before.end_date, after.end_date)
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


def trace_rows(requirements: list[Requirement], plan: Plan) -> list[dict[str, Any]]:
    """Per requirement, the tasks of the plan that serve it."""
    return [
        {
            "ID": need.id,
            "Anforderung": need.title,
            "Priorität": need.priority,
            "Aufgaben": ", ".join(t.id for t in plan.tasks if need.id in t.requirement_ids)
            or "keine",
        }
        for need in requirements
    ]


def to_markdown(
    project: Project,
    plan: Plan,
    result: CheckResult,
    requirements: list[Requirement] | None = None,
) -> str:
    owner = {a.task_id: a for a in plan.assignments}
    dates = {s.task_id: s for s in result.schedule}
    lines = [
        "# Projektplan",
        "",
        f"**Projekt:** {_md(project.idea)}  ",
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
            f"| {_md(t.id)} | {_md(t.title)} | {_md(a.member) if a else ''} | "
            f"{t.estimate_hours:g} | "
            f"{_date(s.start) if s else ''} | {_date(s.end) if s else ''} | "
            f"{_md(a.reason) if a else ''} |"
        )
    if result.critical_path:
        lines += ["", f"**Kritischer Pfad:** {' → '.join(result.critical_path)}"]
    if requirements is not None:
        lines += ["", "## Anforderungen", ""] + [
            f"- {_md(row['ID'])} · {_md(row['Anforderung'])} ({row['Priorität']}): "
            f"{_md(row['Aufgaben'])}"
            for row in trace_rows(requirements, plan)
        ]
    if plan.demos:
        weeks = max(d.week for d in plan.demos)
        friday = {
            n: last
            for n, _, last in islice(project_weeks(project.start_date, project.deadline), weeks)
        }
        lines += ["", "## Demos je Woche", ""] + [
            f"- Woche {d.week}"
            + (f" (bis {_date(friday[d.week])})" if d.week in friday else "")
            + f": {_md(d.title)} ({_md(', '.join(d.task_ids))})"
            for d in sorted(plan.demos, key=lambda d: d.week)
        ]
    for title, items in (
        ("Fehler", result.errors),
        ("Warnungen", result.warnings),
        ("Risiken", plan.risks),
    ):
        if items:
            lines += ["", f"## {title}", ""] + [f"- {_md(item)}" for item in items]
    return "\n".join(lines) + "\n"


def demo_rows(plan: Plan, result: CheckResult, project: Project) -> list[dict[str, Any]]:
    """One row per demo, in week order: until when, what, which tasks, and whether the
    schedule has them done by the end of that week."""
    if not plan.demos:
        return []
    weeks = max(d.week for d in plan.demos)
    last = {
        n: day for n, _, day in islice(project_weeks(project.start_date, project.deadline), weeks)
    }
    ends = {s.task_id: s.end for s in result.schedule}
    rows = []
    for demo in sorted(plan.demos, key=lambda d: d.week):
        friday = last.get(demo.week)
        late = [
            f"{tid} endet am {_date(ends[tid])}"
            for tid in demo.task_ids
            if friday is not None and tid in ends and ends[tid] > friday
        ]
        rows.append(
            {
                "Woche": demo.week,
                "Bis": _date(friday) if friday else "nach der Deadline",
                "Demo": demo.title,
                "Aufgaben": ", ".join(demo.task_ids),
                "Rechtzeitig fertig": (
                    "nicht geprüft"
                    if result.errors or any(tid not in ends for tid in demo.task_ids)
                    else f"nein: {', '.join(late)}"
                    if late
                    else "ja"
                ),
            }
        )
    return rows


def to_csv(plan: Plan, result: CheckResult) -> str:
    """The plan for German Excel: semicolons, a decimal comma, and a byte order mark, without
    which Excel reads UTF-8 as cp1252 ("BegrÃ¼ndung")."""
    dates = {s.task_id: s for s in result.schedule}
    out = io.StringIO()
    out.write("﻿")
    writer = csv.writer(out, delimiter=";")  # semicolon: German Excel splits it into columns
    writer.writerow(PLAN_COLUMNS[:-1] + ["Start", "Ende", "Begründung"])
    for row in plan_rows(plan):
        s = dates.get(row["ID"])
        writer.writerow(
            [_csv_cell(row[c]) for c in PLAN_COLUMNS[:-1]]
            + [
                _date(s.start) if s else "",
                _date(s.end) if s else "",
                _csv_cell(row["Begründung"]),
            ]
        )
    return out.getvalue()


def _csv_cell(value: Any) -> Any:
    """A number with a decimal comma; text that Excel would run as a formula (it begins with
    = + - @ or a tab or line break) with an apostrophe in front, so Excel shows it as text."""
    if isinstance(value, float):
        return f"{value:g}".replace(".", ",")
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + value
    return value


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
        if days[-1] < days[0]:
            raise InputError(f"{what}'{part}': Das Ende liegt vor dem Beginn")
        absences.append(Absence(first=days[0], last=days[-1]))
    return absences


def _list(value: Any) -> list[str]:
    return [p.strip() for p in _cell(value).split(",") if p.strip()]


def _cell(value: Any) -> str:
    # The table editor gives None (or NaN) for empty cells.
    return "" if value is None or value != value else str(value).strip()


def _reason(err: Exception) -> str:
    if isinstance(err, json.JSONDecodeError):
        return f"kein gültiges JSON (Zeile {err.lineno}, Spalte {err.colno})"
    if isinstance(err, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'Eingabe'}: {german(e)}" for e in err.errors()
        )
    return str(err)


def _date(day: Any) -> str:
    return day.strftime("%d.%m.%Y")


def _inert(text: str) -> str:
    """Text from Claude or the project lead inside a Markdown document: no link, image or
    HTML tag. The preview would fetch an image from a foreign server and a link could hide
    where it leads; GitHub renders the downloaded file the same way."""
    for char in "[]<>":
        text = text.replace(char, "\\" + char)
    return text


def _md(text: str) -> str:
    """Text for one table cell or one list item: no column separator, on one line, inert."""
    return " ".join(_inert(text).replace("|", "\\|").split())
