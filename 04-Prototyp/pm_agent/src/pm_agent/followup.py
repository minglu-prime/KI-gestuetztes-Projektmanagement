"""The agents for Durchführung and Kontrolle. Both read the adopted plan with its recorded
progress and the numbers `tracking.evaluate` computed from it. Claude writes the judgement;
Python checks it against the data before the submit tool accepts it.

Skeleton: one submit tool and one check per agent. Further tools (for example a what-if
reschedule for the Kontrolle agent) go next to the Submission in the run functions.
"""

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from pm_agent.agent import LOG_DIR, PROMPTS, run_agent
from pm_agent.models import ControlReport, StatusSummary
from pm_agent.tools import Submission
from pm_agent.tracking import Evaluation, Tracking, evaluate


def run_status_summary(
    tracking: Tracking,
    today: date,
    log_dir: Path | None = LOG_DIR,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> StatusSummary:
    """Durchführung agent: the text part of the status report. Raises AgentError."""
    evaluation = evaluate(tracking, today)
    submission = Submission(
        name="submit_status",
        noun="Statusbericht",
        description=(
            "Reicht Zusammenfassung und nächste Schritte für den Statusbericht ein. Lehnt ab, "
            "wenn eine Aufgabe im Verzug keinen nächsten Schritt hat, und nennt die Gründe."
        ),
        schema=StatusSummary,
        check=lambda summary: check_summary(summary, evaluation),
    )
    return _run("durchfuehrung", submission, tracking, evaluation, log_dir, on_round)


def run_control_report(
    tracking: Tracking,
    today: date,
    log_dir: Path | None = LOG_DIR,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> ControlReport:
    """Kontrolle agent: assessment, findings and countermeasures. Raises AgentError."""
    evaluation = evaluate(tracking, today)
    submission = Submission(
        name="submit_control",
        noun="Kontrollbericht",
        description=(
            "Reicht Bewertung, Feststellungen und Gegenmaßnahmen ein. Lehnt ab, wenn eine "
            "Aufgabe im Verzug keine Gegenmaßnahme hat, und nennt die Gründe."
        ),
        schema=ControlReport,
        check=lambda report: check_report(report, evaluation),
    )
    return _run("kontrolle", submission, tracking, evaluation, log_dir, on_round)


def check_summary(summary: StatusSummary, evaluation: Evaluation) -> list[str]:
    tasks = {t.id: t for t in evaluation.tasks}
    errors = []
    for step in summary.next_steps:
        if step.task_id not in tasks:
            errors.append(f"Nächster Schritt nennt die unbekannte Aufgabe '{step.task_id}'")
        elif tasks[step.task_id].status == "fertig":
            errors.append(
                f"Aufgabe '{step.task_id}' ist fertig und braucht keinen nächsten Schritt"
            )
    covered = {step.task_id for step in summary.next_steps}
    errors += [
        f"Aufgabe '{t.id}' ist im Verzug, aber kein nächster Schritt nennt sie"
        for t in evaluation.overdue
        if t.id not in covered
    ]
    return errors


def check_report(report: ControlReport, evaluation: Evaluation) -> list[str]:
    known = {t.id for t in evaluation.tasks}
    errors = []
    for kind, items in (("Feststellung", report.findings), ("Gegenmaßnahme", report.measures)):
        for item in items:
            errors += [
                f"{kind} nennt die unbekannte Aufgabe '{task_id}'"
                for task_id in item.task_ids
                if task_id not in known
            ]
    covered = {task_id for measure in report.measures for task_id in measure.task_ids}
    errors += [
        f"Aufgabe '{t.id}' ist im Verzug, aber keine Gegenmaßnahme nennt sie"
        for t in evaluation.overdue
        if t.id not in covered
    ]
    if evaluation.overdue and report.assessment == "im Plan":
        errors.append("Es gibt Aufgaben im Verzug, die Bewertung kann nicht 'im Plan' sein")
    return errors


def facts(tracking: Tracking, evaluation: Evaluation) -> str:
    """What both agents get: the plan, the progress and the computed numbers, as JSON."""
    plan = {t.id: t for t in tracking.plan.tasks}
    data = {
        "projekt": tracking.project.model_dump(mode="json"),
        "stand": evaluation.today.isoformat(),
        "kennzahlen": {
            "planstunden": evaluation.planned_hours,
            "ist_stunden": evaluation.actual_hours,
            "fortschritt": round(evaluation.progress, 3),
            "abweichung_fertiger_aufgaben": evaluation.finished_deviation,
            "im_verzug": [t.id for t in evaluation.overdue],
        },
        "aufgaben": [
            {
                **asdict(t),
                "planned_start": t.planned_start.isoformat(),
                "planned_end": t.planned_end.isoformat(),
                "depends_on": plan[t.id].depends_on,
            }
            for t in evaluation.tasks
        ],
        "je_person": evaluation.by_member,
        "team": [m.model_dump(mode="json") for m in tracking.team],
        "risiken": tracking.plan.risks,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def _run(
    name: str,
    submission: Submission[Any],
    tracking: Tracking,
    evaluation: Evaluation,
    log_dir: Path | None,
    on_round: Callable[[dict[str, Any]], None] | None,
) -> Any:
    data = facts(tracking, evaluation)
    return run_agent(
        log_prefix=name,
        noun=submission.noun,
        system=(PROMPTS / f"{name}.md").read_text(encoding="utf-8"),
        request=f"{data}\n\nReiche dein Ergebnis mit {submission.tool.name} ein.",
        tools=[submission.tool],
        result=lambda: submission.result,
        record=lambda result: {
            "input": json.loads(data),
            "result": result.model_dump(mode="json") if result is not None else None,
        },
        log_dir=log_dir,
        on_round=on_round,
    )
