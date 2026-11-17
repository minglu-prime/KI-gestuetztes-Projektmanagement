"""The end of a run: which requirements the project lead accepts, the closing report, the
operations handbook and the next backlog.

Python suggests and checks; the project lead decides. No Streamlit in here.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pm_agent.agent import LOG_DIR, run_submission
from pm_agent.lifecycle import Check
from pm_agent.models import Cases, Lesson, Lessons
from pm_agent.tools import Submission
from pm_agent.tracking import (
    Evaluation,
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
        criteria = {c.id for c in need.criteria}
        mine = [c for c in items if criteria & set(c.criteria)]
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


def check_lessons(lessons: Lessons, tracking: Tracking) -> list[str]:
    """Errors: a reference that is neither a defect nor the Monday of a reviewed week; a
    severe defect or a missed demo no lesson mentions."""
    weeks = {r.monday.isoformat(): r for r in tracking.retros}
    known = {d.id for d in tracking.defects} | set(weeks)
    errors = [
        f"Lehre {n} nennt den unbekannten Bezug '{ref}'"
        for n, lesson in enumerate(lessons.items, start=1)
        for ref in lesson.refs
        if ref not in known
    ]
    named = {ref for lesson in lessons.items for ref in lesson.refs}
    errors += [
        f"Der schwere Fehler {d.id} kommt in keiner Lehre vor"
        for d in tracking.defects
        if d.severity == "schwer" and d.id not in named
    ]
    errors += [
        f"Die ausgefallene Demo der Woche ab {_date(r.monday)} kommt in keiner Lehre vor"
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
                for s in tracking.signoffs
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


def closing_document(tracking: Tracking, cases: Cases | None, evaluation: Evaluation) -> str:
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
        stand=_date(evaluation.today),
        start=_date(project.start_date),
        deadline=_date(project.deadline),
        planende=_date(max(t.planned_end for t in evaluation.tasks)),
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
