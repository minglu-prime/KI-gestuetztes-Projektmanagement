"""The end of a run: which requirements the project lead accepts, the closing report, the
operations handbook and the next backlog.

Python suggests and checks; the project lead decides. No Streamlit in here.
"""

import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pm_agent.agent import LOG_DIR, run_submission
from pm_agent.lifecycle import Check
from pm_agent.models import BacklogItem, Cases, Charter, Design, Lesson, Lessons
from pm_agent.planning import working_shift
from pm_agent.tools import Submission
from pm_agent.tracking import (
    Evaluation,
    Incident,
    Operation,
    Signoff,
    Tracking,
    _demos_text,
    _fill,
    hours_text,
    percent,
)
from pm_agent.workbench import InputError, _cell, _date, _md, _reason

DASH = "–"  # an empty cell


def suggestions(tracking: Tracking, cases: Cases | None) -> dict[str, str]:
    """Requirement ID -> "abnehmbar", or why not yet: a case without a result or not passed,
    an open defect of one of its cases, or no case at all."""
    latest = {r.case_id: r.result for r in tracking.results}
    items = cases.cases if cases else []
    verdicts = {}
    for need in tracking.requirements:
        prefix = f"{need.id}."
        mine = [c for c in items if any(cid.startswith(prefix) for cid in c.criteria)]
        if not mine:
            verdicts[need.id] = "kein Testfall"
            continue
        reasons = [
            f"Testfall {c.id} ohne Ergebnis"
            if c.id not in latest
            else f"Testfall {c.id} nicht bestanden"
            for c in mine
            if latest.get(c.id) != "bestanden"
        ]
        reasons += [
            f"Fehler {d.id} offen"
            for d in tracking.defects
            if d.status == "offen" and d.case_id in {c.id for c in mine}
        ]
        verdicts[need.id] = "; ".join(reasons) or "abnehmbar"
    return verdicts


def record_signoff(tracking: Tracking, signoff: Signoff) -> Tracking:
    """The decision on one requirement, replacing an earlier one. Raises InputError for an
    unknown requirement or a deferral without a reason. Not saved: the caller saves."""
    if signoff.requirement_id not in {n.id for n in tracking.requirements}:
        raise InputError(f"Die Abnahme nennt die unbekannte Anforderung '{signoff.requirement_id}'")
    if signoff.decision == "zurückgestellt" and not signoff.reason:
        raise InputError("Eine zurückgestellte Anforderung braucht einen Grund")
    others = [s for s in tracking.signoffs if s.requirement_id != signoff.requirement_id]
    return tracking.model_copy(update={"signoffs": [*others, signoff]})


def check_closing(tracking: Tracking, cases: Cases | None) -> Check:
    """Errors: an open severe defect, a Muss requirement neither accepted nor deferred with a
    reason. Warnings: a requirement accepted against the suggestion, a Soll or Kann one not
    decided."""
    errors = [
        f"Fehler {d.id} (schwer) ist noch offen"
        for d in tracking.defects
        if d.status == "offen" and d.severity == "schwer"
    ]
    if not tracking.requirements:
        return Check(
            errors, ["Der Plan wurde ohne Anforderungen übernommen: Es gibt nichts abzunehmen"]
        )
    decided = {s.requirement_id: s for s in tracking.signoffs}
    advice = suggestions(tracking, cases)
    warnings = []
    for need in tracking.requirements:
        signoff = decided.get(need.id)
        if signoff is None:
            if need.priority == "Muss":
                errors.append(
                    f"Muss-Anforderung '{need.id}' ({need.title}) ist weder abgenommen noch "
                    "begründet zurückgestellt"
                )
            else:
                warnings.append(
                    f"{need.priority}-Anforderung '{need.id}' ({need.title}) ist noch nicht "
                    "entschieden"
                )
        elif signoff.decision == "abgenommen" and advice[need.id] != "abnehmbar":
            warnings.append(f"Anforderung '{need.id}' ist abgenommen, obwohl: {advice[need.id]}")
    return Check(errors, warnings)


def _week_ref(ref: str) -> str:
    """ "16.11.2026" as "2026-11-16"; anything else as it is."""
    try:
        return datetime.strptime(ref, "%d.%m.%Y").date().isoformat()
    except ValueError:
        return ref


def _current_signoffs(tracking: Tracking) -> list[Signoff]:
    """Sign-offs of the requirements adopted now: a plan adopted again with other
    requirements keeps the old ones in the file."""
    known = {n.id for n in tracking.requirements}
    return [s for s in tracking.signoffs if s.requirement_id in known]


def check_lessons(lessons: Lessons, tracking: Tracking) -> list[str]:
    """Errors: a reference that is neither a defect nor the Monday of a reviewed week; a
    severe defect or a missed demo no lesson mentions."""
    weeks = {r.monday.isoformat(): r for r in tracking.retros}
    known = {d.id for d in tracking.defects} | set(weeks)
    errors = [
        f"Lehre {n} nennt den unbekannten Bezug '{ref}'"
        for n, lesson in enumerate(lessons.items, start=1)
        for ref in lesson.refs
        if _week_ref(ref) not in known
    ]
    named = {_week_ref(ref) for lesson in lessons.items for ref in lesson.refs}
    errors += [
        f"Der schwere Fehler {d.id} kommt in keiner Lehre vor"
        for d in tracking.defects
        if d.severity == "schwer" and d.id not in named
    ]
    errors += [
        f"Die ausgefallene Demo der Woche ab {_date(r.monday)} (Bezug {monday}) kommt in "
        "keiner Lehre vor"
        for monday, r in weeks.items()
        if r.shown != "ja" and monday not in named
    ]
    return errors


def run_lessons(
    tracking: Tracking,
    today: date,
    log_dir: Path | None = LOG_DIR,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> Lessons:
    """Claude drafts the lessons learned from retros, defects and sign-offs. No names of
    the team go to the API. Raises AgentError."""
    from pm_agent.tracking import evaluate  # the same day the page evaluates

    evaluation = evaluate(tracking, today)
    titles = {n.id: n.title for n in tracking.requirements}
    data = json.dumps(
        {
            "kennzahlen": {
                "fortschritt": round(evaluation.progress, 3),
                "planstunden": evaluation.planned_hours,
                "iststunden": evaluation.actual_hours,
            },
            "rueckblicke": [r.model_dump(mode="json") for r in tracking.retros],
            "fehler": [d.model_dump(mode="json") for d in tracking.defects],
            "abnahme": [
                {**s.model_dump(mode="json"), "titel": titles.get(s.requirement_id, "")}
                for s in _current_signoffs(tracking)
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    submission = Submission(
        name="submit_lessons",
        noun="Lessons Learned",
        description=(
            "Reicht die Lessons Learned ein. Lehnt ab, wenn ein schwerer Fehler oder eine "
            "ausgefallene Demo in keiner Lehre vorkommt oder ein Bezug unbekannt ist, und "
            "nennt die Gründe."
        ),
        schema=Lessons,
        check=lambda lessons: check_lessons(lessons, tracking),
    )
    return run_submission("lessons", submission, data, log_dir, on_round)


def _days(shift: int) -> str:
    """-2 -> "2 Arbeitstage vor Plan"."""
    if shift == 0:
        return "wie geplant"
    count = f"{abs(shift)} Arbeitstag{'' if abs(shift) == 1 else 'e'}"
    return f"{count} {'nach' if shift > 0 else 'vor'} Plan"


def actual_end(tracking: Tracking, evaluation: Evaluation) -> str:
    """The day the last task was finished, against the planned end. Tasks finished before the
    day was recorded have none: then the end is a lower bound, and the text says so."""
    tasks = evaluation.tasks
    finished = [t for t in tasks if t.status == "fertig"]
    if len(finished) < len(tasks):
        return f"noch offen ({len(finished)} von {len(tasks)} Aufgaben fertig)"
    earlier = [e for e in tracking.history if e.finished]
    days = [t.finished_on for t in finished] + [e.finished_on for e in earlier]
    known = [d for d in days if d is not None]
    if not known:
        return "unbekannt (keine Fertigdaten erfasst)"
    last = max(known)
    planned = max(t.planned_end for t in tasks)
    text = f"{_date(last)} ({_days(working_shift(tracking.project, planned, last))})"
    if unknown := len(days) - len(known):
        text += (
            f". {unknown} fertige Aufgabe{'' if unknown == 1 else 'n'} ohne Fertigdatum: "
            "Das tatsächliche Ende kann später liegen"
        )
    return text


def late_tasks(tracking: Tracking, evaluation: Evaluation) -> str:
    """Tasks of the plan finished after their planned end, as a Markdown table."""
    rows = []
    for t in evaluation.tasks:
        if t.finished_on is None:
            continue
        shift = working_shift(tracking.project, t.planned_end, t.finished_on)
        if shift > 0:
            cells = [t.id, t.title, _date(t.planned_end), _date(t.finished_on), str(shift)]
            rows.append("| " + " | ".join(_md(cell) for cell in cells) + " |")
    if not rows:
        return "Keine Aufgabe wurde später fertig als geplant."
    head = [
        "| ID | Aufgabe | Geplantes Ende | Fertig am | Verzug (Arbeitstage) |",
        "|---|---|---|---|---|",
    ]
    return "\n".join(head + rows)


def closing_document(
    tracking: Tracking,
    cases: Cases | None,
    evaluation: Evaluation,
    charter: Charter | None = None,
) -> str:
    """The closing report: sign-offs with Python's suggestion, figures, demos, defects,
    lessons, and what the check still finds open."""
    advice = suggestions(tracking, cases)
    decided = {s.requirement_id: s for s in tracking.signoffs}
    rows = []
    for need in tracking.requirements:
        signoff = decided.get(need.id)
        cells = [
            need.id,
            need.title,
            need.priority,
            advice[need.id],
            signoff.decision if signoff else "offen",
            (signoff.reason if signoff else "") or DASH,
        ]
        rows.append("| " + " | ".join(_md(cell) for cell in cells) + " |")
    defects = "\n".join(
        f"- {_md(d.id)} ({d.severity}, {d.status}): {_md(d.cause) or DASH}"
        for d in tracking.defects
    )
    lessons = "\n".join(
        f"- {_md(lesson.observation)}: {_md(lesson.advice)}"
        + (f" (Bezug: {_md(', '.join(lesson.refs))})" if lesson.refs else "")
        for lesson in tracking.lessons
    )
    errors, warnings = check_closing(tracking, cases)
    project = tracking.project
    return _fill(
        "abschluss.md",
        projekt=_md(project.idea),
        ziel=(
            f"{_md(charter.goal)}\n\n"
            + "\n".join(f"- {_md(c.id)}: {_md(c.text)}" for c in charter.success_criteria)
            if charter
            else "Kein Projektauftrag."
        ),
        stand=_date(evaluation.today),
        start=_date(project.start_date),
        deadline=_date(project.deadline),
        planende=_date(max(t.planned_end for t in evaluation.tasks)),
        istende=actual_end(tracking, evaluation),
        spaet=late_tasks(tracking, evaluation),
        abnahme="\n".join(rows) or f"| {DASH} | Keine Anforderungen | | | | |",
        fortschritt=percent(evaluation.progress),
        plan_h=hours_text(evaluation.planned_hours),
        ist_h=hours_text(evaluation.actual_hours),
        demos=_demos_text(tracking, evaluation.today),
        fehler=defects or "Keine Fehler erfasst.",
        lehren=lessons or "Noch keine.",
        offen="\n".join(f"- {_md(text)}" for text in errors + warnings) or "Keine.",
    )


LESSON_COLUMNS = ["Beobachtung", "Empfehlung", "Bezug"]


def lesson_rows(lessons: list[Lesson]) -> list[dict[str, Any]]:
    return [
        {"Beobachtung": x.observation, "Empfehlung": x.advice, "Bezug": ", ".join(x.refs)}
        for x in lessons
    ]


def rows_to_lessons(rows: list[dict[str, Any]]) -> list[Lesson]:
    """The edited table as lessons. Raises InputError naming each unreadable row."""
    items, errors = [], []
    for number, row in enumerate(rows, start=1):
        if not any(_cell(v) for v in row.values()):
            continue  # an empty row the editor adds
        try:
            items.append(
                Lesson(
                    observation=_cell(row.get("Beobachtung")),
                    advice=_cell(row.get("Empfehlung")),
                    refs=[r.strip() for r in _cell(row.get("Bezug")).split(",") if r.strip()],
                )
            )
        except ValidationError as err:
            errors.append(f"Zeile {number}: {_reason(err)}")
    if errors:
        raise InputError("\n".join(errors))
    return items


def signoff_rows(tracking: Tracking, cases: Cases | None) -> list[dict[str, Any]]:
    """One row per requirement: Python's suggestion and the lead's decision."""
    advice = suggestions(tracking, cases)
    decided = {s.requirement_id: s for s in tracking.signoffs}
    return [
        {
            "ID": need.id,
            "Anforderung": need.title,
            "Priorität": need.priority,
            "Vorschlag": advice[need.id],
            "Entscheidung": decided[need.id].decision if need.id in decided else "offen",
            "Grund": decided[need.id].reason if need.id in decided else "",
        }
        for need in tracking.requirements
    ]


OPERATION_COLUMNS = [
    "Baustein",
    "Name",
    "Verantwortlich",
    "Bereitstellung",
    "Überwachung",
    "Rücknahme",
]


def operation_rows(design: Design | None, operations: list[Operation]) -> list[dict[str, Any]]:
    """One row per component the team builds; roles and systems outside the project are
    not run by the team."""
    if design is None:
        return []
    known = {o.component_id: o for o in operations}
    rows = []
    for c in design.components:
        if c.kind != "Komponente":
            continue
        o = known.get(c.id, Operation(component_id=c.id))
        rows.append(
            {
                "Baustein": c.id,
                "Name": c.name,
                "Verantwortlich": o.owner,
                "Bereitstellung": o.deployment,
                "Überwachung": o.monitoring,
                "Rücknahme": o.rollback,
            }
        )
    return rows


def rows_to_operations(rows: list[dict[str, Any]]) -> list[Operation]:
    return [
        Operation(
            component_id=_cell(row.get("Baustein")),
            owner=_cell(row.get("Verantwortlich")),
            deployment=_cell(row.get("Bereitstellung")),
            monitoring=_cell(row.get("Überwachung")),
            rollback=_cell(row.get("Rücknahme")),
        )
        for row in rows
        if _cell(row.get("Baustein"))
    ]


def check_operations(design: Design | None, operations: list[Operation]) -> Check:
    """Errors: a component without an owner or without monitoring."""
    if design is None:
        return Check([], ["Ohne Entwurf gibt es keine Bausteine für das Betriebshandbuch"])
    known = {o.component_id: o for o in operations}
    errors = []
    for c in design.components:
        if c.kind != "Komponente":
            continue
        o = known.get(c.id, Operation(component_id=c.id))
        if not o.owner:
            errors.append(f"Baustein '{c.id}' ({c.name}) hat keine Verantwortlichen")
        if not o.monitoring:
            errors.append(f"Baustein '{c.id}' ({c.name}) hat keine Überwachung")
    return Check(errors, [])


def record_incident(tracking: Tracking, incident: Incident, design: Design | None) -> Tracking:
    """An incident, new (numbered S1, S2 …) or changed (same ID). Raises InputError for a
    component the design does not know."""
    known = {c.id for c in design.components} if design else set()
    if incident.component_id not in known:
        raise InputError(f"Die Störung nennt den unbekannten Baustein '{incident.component_id}'")
    if not incident.id:
        numbers = [int(i.id[2:]) for i in tracking.incidents if i.id[2:].isdigit()]
        incident = incident.model_copy(update={"id": f"ST{max(numbers, default=0) + 1}"})
    others = [i for i in tracking.incidents if i.id != incident.id]
    return tracking.model_copy(update={"incidents": [*others, incident]})


def next_backlog(tracking: Tracking) -> list[BacklogItem]:
    """What the next run starts from: deferred requirements, open defects, open measures of
    the retros and open incidents, each with its origin."""
    from pm_agent.tracking import open_measures

    titles = {n.id: n.title for n in tracking.requirements}
    items = [
        BacklogItem(
            text=(
                f"Anforderung {s.requirement_id} ({titles.get(s.requirement_id, '?')}): {s.reason}"
            ),
            origin=f"{s.requirement_id} zurückgestellt",
        )
        for s in _current_signoffs(tracking)
        if s.decision == "zurückgestellt"
    ]
    items += [
        BacklogItem(
            text=f"Fehler beheben: {d.cause or d.case_id}", origin=f"{d.id} offen ({d.severity})"
        )
        for d in tracking.defects
        if d.status == "offen"
    ]
    items += [
        BacklogItem(text=r.measure, origin=f"Maßnahme der Woche ab {_date(r.monday)}")
        for r in open_measures(tracking)
    ]
    items += [
        BacklogItem(
            text=f"Störung beheben: {i.impact}" + (f" (Ursache: {i.cause})" if i.cause else ""),
            origin=f"{i.id} offen",
        )
        for i in tracking.incidents
        if i.status == "offen"
    ]
    return items


def start_next_run(tracking: Tracking, now: datetime, archive: Path) -> Path:
    """Move the files of this run into a new folder of `archive` (nothing is deleted) and
    begin a new Vorhaben that holds the next backlog. Returns the folder."""
    import pm_agent.lifecycle as lifecycle_module
    import pm_agent.tracking as tracking_module

    backlog = next_backlog(tracking)
    base = archive / now.strftime("%Y-%m-%d_%H%M")
    folder, n = base, 1
    while folder.exists():
        n += 1
        folder = base.with_name(f"{base.name}-{n}")
    # Everything or nothing: the new Vorhaben is written first, beside the old one; a
    # failure on the way puts back what was moved and removes what was written.
    fresh = lifecycle_module.FILE.with_name("vorhaben.neu.json")  # read at call time
    lifecycle_module.save(lifecycle_module.Lifecycle(backlog=backlog), fresh)
    moved: list[Path] = []
    try:
        folder.mkdir(parents=True)
        for path in [lifecycle_module.FILE, tracking_module.PROJECT_FILE]:
            if path.exists():
                path.rename(folder / path.name)
                moved.append(path)
        fresh.rename(lifecycle_module.FILE)
    except OSError:
        for path in reversed(moved):
            (folder / path.name).rename(path)
        fresh.unlink(missing_ok=True)
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
        raise
    return folder
