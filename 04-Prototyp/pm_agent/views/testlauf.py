"""Page "Test": the results of the test cases and the defects they found. The team runs the
tests; the project lead enters what came out. Python checks that every failed case has an
open defect, and a defect can put its task back to "in Arbeit".

The buttons work through callbacks: they run before the page is drawn again, so they can
empty the fields they used (a second click would otherwise record the same defect twice)."""

from collections.abc import Callable
from datetime import date

import pandas as pd
import streamlit as st

from pm_agent import lifecycle
from pm_agent.tracking import (
    CasePlan,
    CaseResult,
    Defect,
    Tracking,
    case_status,
    check_results,
    current_results,
    load,
    record_defect,
    record_result,
    reopen,
    save_if_current,
)
from pm_agent.ui import (
    adopted_project,
    as_text,
    check_verdict,
    heading,
    messages,
    next_open,
    notify,
    verdict,
)
from pm_agent.workbench import InputError

state = st.session_state


def change(make, done: Callable[[Tracking], str]) -> Tracking | None:
    """Apply `make` to the project as saved now, save it and say so (`done` words it from
    the saved project). A refusal or a failed save is shown on the next run, and gives None."""
    try:
        current = load()
        if current is None:
            raise InputError("Es ist kein Projekt übernommen")
        saved = make(current)
        save_if_current(current, saved)
    except InputError as err:
        state.test_page_error = str(err)
        return None
    except OSError as err:
        state.test_page_error = f"Das Projekt konnte nicht gespeichert werden: {err}."
        return None
    notify(done(saved))
    return saved


def on_result(plan: CasePlan) -> None:
    versions = plan.versions
    result = CaseResult(
        case_id=state.test_case, result=state.test_result, on=date.today(), note=state.test_note
    )

    checked = []  # the test plan as it stood when saving

    def record(t: Tracking) -> Tracking:
        current = lifecycle.case_plan(lifecycle.load())
        if current is None or current.versions.get(result.case_id) != versions.get(result.case_id):
            raise InputError("Der Testfall wurde inzwischen geändert. Prüfe ihn erneut.")
        checked.append(current)
        return record_result(t, result, current)

    saved = change(record, lambda t: f"Ergebnis gespeichert: {result.case_id} {result.result}.")
    if saved is not None:
        state.test_note = ""
        # On to the next case without a result, counted against the cases as they are now.
        state.test_case = first_open(checked[-1], saved, after=result.case_id)
        # A failure without an open defect waits for one in the form below.
        if result.result == "fehlgeschlagen" and result.case_id not in open_defects(saved):
            state.defect_case = result.case_id


def first_open(plan: CasePlan, tracking: Tracking, after: str = "") -> str:
    """The case to run next: the first one after `after` without a current result."""
    order, done = [c.id for c in plan.cases], set(current_results(tracking, plan))
    found = next_open(order, done, after or order[-1])
    return found if after or found not in done else order[0]  # all done: from the top


def open_defects(tracking: Tracking) -> set[str]:
    """The cases that have an open defect."""
    return {d.case_id for d in tracking.defects if d.status == "offen"}


def on_defect() -> None:
    fields = {
        "case_id": state.defect_case,
        "severity": state.defect_severity,
        "cause": state.defect_cause,
        "task_id": state.defect_task or None,
    }
    chosen = state.get("defect_id", "")

    def record(t: Tracking) -> Tracking:
        # A chosen entry keeps what the form does not show: its status and the day of the fix.
        old = next((d for d in t.defects if d.id == chosen), None)
        defect = Defect(**{**old.model_dump(), **fields}) if old else Defect(**fields)
        return record_defect(t, defect)

    # A new defect gets the next number: the last one in the list.
    said = "geändert" if chosen else "erfasst"
    if change(record, lambda t: f"Fehler {chosen or t.defects[-1].id} {said}."):
        state.defect_id = ""
        state.defect_cause = ""
        state.defect_task = ""


def on_pick_defect(defects: dict[str, Defect], cases: dict[str, str]) -> None:
    """Fill the form with the chosen defect, or empty it for a new one."""
    defect = defects.get(state.defect_id)
    state.defect_cause = defect.cause if defect else ""
    state.defect_task = (defect.task_id or "") if defect else ""
    if defect:
        state.defect_severity = defect.severity
        if defect.case_id in cases:
            state.defect_case = defect.case_id


def on_reopen(defect_id: str) -> None:
    def opened(t: Tracking) -> str:
        task = next(d.task_id for d in t.defects if d.id == defect_id)
        return f"Aufgabe {task} ist wieder in Arbeit."

    change(lambda t: reopen(t, defect_id), opened)


def on_fixed(defect_id: str) -> None:
    def fix(t: Tracking) -> Tracking:
        defect = next(d for d in t.defects if d.id == defect_id)
        return record_defect(
            t, defect.model_copy(update={"status": "behoben", "fixed_on": date.today()})
        )

    change(fix, lambda t: f"Fehler {defect_id} ist behoben.")


def on_unfix(defect_id: str) -> None:
    def unfix(t: Tracking) -> Tracking:
        defect = next(d for d in t.defects if d.id == defect_id)
        return record_defect(t, defect.model_copy(update={"status": "offen", "fixed_on": None}))

    change(unfix, lambda t: f"Fehler {defect_id} ist wieder offen.")


st.header("Test")
st.caption(
    "Was kam heraus, als das Team die Testfälle ausgeführt hat? Du trägst die Ergebnisse ein, "
    "Python prüft, dass jeder fehlgeschlagene Testfall einen offenen Fehlereintrag hat. Ein "
    "Fehler kann seine Aufgabe in der Durchführung wieder öffnen."
)
tracking = adopted_project()
if tracking is None:
    st.stop()
try:
    life = lifecycle.load()
except InputError as err:
    st.error(f"Der Testplan konnte nicht gelesen werden: {as_text(str(err))}")
    st.stop()
plan = lifecycle.case_plan(life)
if "test_page_error" in state:
    st.error(as_text(state.pop("test_page_error")))
if plan is None:
    st.info("Noch kein Testplan. Lege die Testfälle auf der Seite Testplan an.")
    st.page_link("views/testplan.py", label="Zum Testplan", icon=":material/arrow_forward:")
    st.stop()
if lifecycle.cases_state(life) != "freigegeben":
    st.warning(
        "Der Testplan ist nicht freigegeben. Ergebnisse lassen sich trotzdem eintragen; "
        "geprüft wird gegen die Testfälle, wie sie gerade stehen."
    )
titles = {c.id: c.title for c in plan.cases}
if state.get("test_case") not in titles:  # a first visit, or the case is gone
    state.test_case = first_open(plan, tracking)
errors, warnings = check_results(tracking, plan)
fine = "Jeder Testfall hat ein Ergebnis, jeder fehlgeschlagene einen Fehlereintrag."
verdict(*check_verdict(errors, warnings, fine))

with st.container(border=True, key="panel-results"):
    heading("rule", "Ergebnisse", du="trägst ein", python="prüft")
    st.dataframe(pd.DataFrame(case_status(tracking, plan)), hide_index=True)
    st.selectbox(
        "Testfall", list(titles), format_func=lambda c: f"{c} · {titles[c]}", key="test_case"
    )
    st.radio(
        "Ergebnis", ["bestanden", "fehlgeschlagen", "blockiert"], horizontal=True, key="test_result"
    )
    st.text_input("Notiz", key="test_note")
    st.button("Ergebnis speichern", icon=":material/save:", on_click=on_result, args=(plan,))

with st.container(border=True, key="panel-defects"):
    heading("bug_report", "Fehler", du="erfasst und entscheidest", python="prüft")
    messages(errors, warnings)
    tasks = {t.id: t.title for t in tracking.plan.tasks}
    defects_by_id = {d.id: d for d in tracking.defects}
    if defects_by_id:
        st.selectbox(
            "Eintrag",
            ["", *defects_by_id],
            format_func=lambda d: f"{d} ändern ({defects_by_id[d].cause})" if d else "Neuer Fehler",
            key="defect_id",
            on_change=on_pick_defect,
            args=(defects_by_id, titles),
        )
    if state.get("defect_case") not in titles:
        # A failed case without an open defect is what the form is most likely for.
        latest = current_results(tracking, plan)
        open_cases = open_defects(tracking)
        state.defect_case = next(
            (
                c.id
                for c in plan.cases
                if c.id in latest
                and latest[c.id].result == "fehlgeschlagen"
                and c.id not in open_cases
            ),
            plan.cases[0].id,
        )
    st.selectbox(
        "Gefunden von", list(titles), format_func=lambda c: f"{c} · {titles[c]}", key="defect_case"
    )
    st.radio("Schwere", ["schwer", "mittel", "leicht"], horizontal=True, key="defect_severity")
    st.text_input("Vermutete Ursache", key="defect_cause")
    st.selectbox(
        "Aufgabe, die ihn behebt",
        ["", *tasks],
        format_func=lambda t: f"{t} · {tasks[t]}" if t else "keine",
        key="defect_task",
    )
    st.button("Fehler erfassen", icon=":material/add:", on_click=on_defect)
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
                        "Status": (
                            f"behoben ({d.fixed_on:%d.%m.%Y})"
                            if d.status == "behoben" and d.fixed_on
                            else d.status
                        ),
                    }
                    for d in tracking.defects
                ]
            ),
            hide_index=True,
        )
        for defect in [d for d in tracking.defects if d.status == "offen"]:
            left, right = st.columns(2)
            if defect.task_id:
                left.button(
                    f"{defect.id}: Aufgabe {defect.task_id} wieder öffnen",
                    key=f"reopen_{defect.id}",
                    icon=":material/replay:",
                    on_click=on_reopen,
                    args=(defect.id,),
                )
            right.button(
                f"{defect.id}: behoben",
                key=f"fixed_{defect.id}",
                icon=":material/check:",
                on_click=on_fixed,
                args=(defect.id,),
            )
        for defect in [d for d in tracking.defects if d.status == "behoben"]:
            st.button(
                f"{defect.id}: wieder öffnen",
                key=f"unfix_{defect.id}",
                icon=":material/undo:",
                on_click=on_unfix,
                args=(defect.id,),
            )
