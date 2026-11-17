"""Page "Test": the results of the test cases and the defects they found. The team runs the
tests; the project lead enters what came out. Python checks that every failed case has a
defect, and a defect can put its task back to "in Arbeit"."""

from datetime import date

import pandas as pd
import streamlit as st

from pm_agent import lifecycle
from pm_agent.tracking import (
    CaseResult,
    Defect,
    case_status,
    check_results,
    record_defect,
    record_result,
    reopen,
    save,
)
from pm_agent.ui import adopted_project, as_text, heading
from pm_agent.workbench import InputError


def store(updated) -> None:
    try:
        save(updated)
    except OSError as err:
        st.error(f"Das Projekt konnte nicht gespeichert werden: {err}.")
    else:
        st.rerun()


st.header("Test")
st.caption(
    "Was kam heraus, als das Team die Testfälle ausgeführt hat? Du trägst die Ergebnisse ein, "
    "Python prüft, dass jeder fehlgeschlagene Testfall einen Fehlereintrag hat. Ein Fehler "
    "kann seine Aufgabe in der Durchführung wieder öffnen."
)
tracking = adopted_project()
if tracking is None:
    st.stop()
try:
    life = lifecycle.load()
except InputError as err:
    st.error(f"Der Testplan konnte nicht gelesen werden: {err}")
    st.stop()
cases = life.cases if life is not None else None
if cases is None:
    st.info("Noch kein Testplan. Lege die Testfälle auf der Seite Testplan an.")
    st.page_link("views/testplan.py", label="Zum Testplan", icon=":material/arrow_forward:")
    st.stop()
if lifecycle.cases_state(life) != "freigegeben":
    st.warning(
        "Der Testplan ist nicht freigegeben. Ergebnisse lassen sich trotzdem eintragen; "
        "geprüft wird gegen die Testfälle, wie sie gerade stehen."
    )
titles = {c.id: c.title for c in cases.cases}

with st.container(border=True, key="panel-results"):
    heading("rule", "Ergebnisse", du="trägst ein", python="prüft")
    st.dataframe(pd.DataFrame(case_status(tracking, cases)), hide_index=True)
    case = st.selectbox(
        "Testfall", list(titles), format_func=lambda c: f"{c} · {titles[c]}", key="test_case"
    )
    result = st.radio(
        "Ergebnis", ["bestanden", "fehlgeschlagen", "blockiert"], horizontal=True, key="test_result"
    )
    note = st.text_input("Notiz", key="test_note")
    if st.button("Ergebnis speichern", icon=":material/save:"):
        store(
            record_result(
                tracking, CaseResult(case_id=case, result=result, on=date.today(), note=note)
            )
        )

with st.container(border=True, key="panel-defects"):
    heading("bug_report", "Fehler", du="erfasst und entscheidest", python="prüft")
    errors, warnings = check_results(tracking, cases)
    for error in errors:
        st.error(as_text(error))
    for warning in warnings:
        st.warning(as_text(warning))
    tasks = {t.id: t.title for t in tracking.plan.tasks}
    defect_case = st.selectbox(
        "Gefunden von", list(titles), format_func=lambda c: f"{c} · {titles[c]}", key="defect_case"
    )
    severity = st.radio(
        "Schwere", ["schwer", "mittel", "leicht"], horizontal=True, key="defect_severity"
    )
    cause = st.text_input("Vermutete Ursache", key="defect_cause")
    task = st.selectbox(
        "Aufgabe, die ihn behebt",
        ["", *tasks],
        format_func=lambda t: f"{t} · {tasks[t]}" if t else "keine",
        key="defect_task",
    )
    if st.button("Fehler erfassen", icon=":material/add:"):
        try:
            updated = record_defect(
                tracking,
                Defect(case_id=defect_case, severity=severity, cause=cause, task_id=task or None),
            )
        except InputError as err:
            st.error(as_text(str(err)))
        else:
            store(updated)
    if tracking.defects:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "ID": d.id,
                        "Testfall": d.case_id,
                        "Schwere": d.severity,
                        "Ursache": d.cause,
                        "Aufgabe": d.task_id or "",
                        "Status": d.status,
                    }
                    for d in tracking.defects
                ]
            ),
            hide_index=True,
        )
        for defect in [d for d in tracking.defects if d.status == "offen"]:
            left, right = st.columns(2)
            if defect.task_id and left.button(
                f"{defect.id}: Aufgabe {defect.task_id} wieder öffnen",
                key=f"reopen_{defect.id}",
                icon=":material/replay:",
            ):
                store(reopen(tracking, defect.id))
            if right.button(
                f"{defect.id}: behoben", key=f"fixed_{defect.id}", icon=":material/check:"
            ):
                store(record_defect(tracking, defect.model_copy(update={"status": "behoben"})))
