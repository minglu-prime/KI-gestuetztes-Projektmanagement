"""The end of a run: which requirements the project lead accepts, the closing report, the
operations handbook and the next backlog.

Python suggests and checks; the project lead decides. No Streamlit in here.
"""

from pm_agent.lifecycle import Check
from pm_agent.models import Cases
from pm_agent.tracking import Signoff, Tracking
from pm_agent.workbench import InputError


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
