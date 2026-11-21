"""Page "Abschluss", in three tabs. Abnahme und Lehren: the project lead accepts or defers
each requirement, Claude drafts the lessons learned, Python checks that nothing severe is
left open and fills the closing report. Betrieb (optional: many student projects are never
run): who runs each component of the design, how it is deployed, watched and taken back, and
which incidents happened. Nächster Durchlauf: Python collects deferred requirements, open
defects, open measures and open incidents, each with its origin; starting the next run moves
this run's files into data/archiv and begins a new Vorhaben with that backlog.

Buttons work through callbacks (see views/testlauf.py): they run before the page is drawn
again and can empty the fields they used."""

from datetime import date, datetime

import pandas as pd
import streamlit as st

from pm_agent import closing, lifecycle
from pm_agent.closing import (
    LESSON_COLUMNS,
    OPERATION_COLUMNS,
    check_closing,
    check_lessons,
    check_operations,
    closing_document,
    lesson_rows,
    operation_rows,
    rows_to_lessons,
    rows_to_operations,
    signoff_rows,
)
from pm_agent.models import Lesson, Lessons, Requirement
from pm_agent.tracking import (
    PROJECT_WRITE_LOCK,
    Incident,
    Signoff,
    Tracking,
    evaluate,
    load,
    require_current,
    save_if_current,
)
from pm_agent.ui import (
    adopted_project,
    as_text,
    consent,
    heading,
    kept_editor,
    messages,
    run_with_progress,
)
from pm_agent.workbench import DATA_DIR, InputError

state = st.session_state


def change(make) -> bool:
    try:
        current = load()
        if current is None:
            raise InputError("Es ist kein Projekt übernommen")
        save_if_current(current, make(current))
    except InputError as err:
        state.closing_error = str(err)
        return False
    except OSError as err:
        state.closing_error = f"Das Projekt konnte nicht gespeichert werden: {err}."
        return False
    return True


def save_lessons(basis: Tracking, items: list[Lesson]) -> bool:
    try:
        save_if_current(basis, basis.model_copy(update={"lessons": items}))
    except (InputError, OSError) as err:
        st.error(f"Die Lessons Learned konnten nicht gespeichert werden: {as_text(str(err))}")
        return False
    return True


def on_signoff(requirements: dict[str, Requirement]) -> None:
    signoff = Signoff(
        requirement_id=state.signoff_req,
        decision=state.signoff_decision,
        reason=state.signoff_reason,
    )

    def record(t: Tracking) -> Tracking:
        current = next((need for need in t.requirements if need.id == signoff.requirement_id), None)
        if current != requirements.get(signoff.requirement_id):
            raise InputError("Die Anforderung wurde inzwischen geändert. Prüfe sie erneut.")
        return closing.record_signoff(t, signoff)

    if change(record):
        state.signoff_reason = ""


st.header("Abschluss")
st.caption(
    "Ist jede Anforderung erfüllt, und was lernen wir daraus? Python schlägt aus Testergebnissen "
    "und Fehlern vor, was sich abnehmen lässt; du entscheidest je Anforderung. Der Agent entwirft "
    "die Lessons Learned aus Rückblicken und Fehlern. Betrieb und der nächste Durchlauf stehen "
    "in den Reitern daneben."
)
tracking = adopted_project()
if tracking is None:
    st.stop()
try:
    life = lifecycle.load()
except InputError as err:
    st.error(f"Testplan und Entwurf konnten nicht gelesen werden: {as_text(str(err))}")
    life = None
plan = lifecycle.case_plan(life)
design = life.design if life is not None else None
today = date.today()
if "closing_error" in state:
    st.error(as_text(state.pop("closing_error")))


def on_incident() -> None:
    incident = Incident(
        on=date.today(),
        component_id=state.incident_component,
        impact=state.incident_impact,
        cause=state.incident_cause,
        measure=state.incident_measure,
    )
    if not incident.impact:
        state.closing_error = "Beschreib die Auswirkung der Störung."
        return
    if change(lambda t: closing.record_incident(t, incident, design)):
        for key in ["incident_impact", "incident_cause", "incident_measure"]:
            state[key] = ""


def on_fixed(incident_id: str) -> None:
    def fix(t):
        incident = next(i for i in t.incidents if i.id == incident_id)
        return closing.record_incident(t, incident.model_copy(update={"status": "behoben"}), design)

    change(fix)


# All three are drawn on every run; the browser shows the chosen one.
closing_tab, operations_tab, next_tab = st.tabs(
    ["Abnahme und Lehren", "Betrieb", "Nächster Durchlauf"]
)

with closing_tab:
    with st.container(border=True, key="panel-signoff"):
        heading("verified", "Abnahme je Anforderung", python="schlägt vor", du="entscheidest")
        errors, warnings = check_closing(tracking, plan)
        if tracking.requirements:
            st.dataframe(pd.DataFrame(signoff_rows(tracking, plan)), hide_index=True)
            titles = {n.id: n.title for n in tracking.requirements}
            st.selectbox(
                "Anforderung",
                list(titles),
                format_func=lambda r: f"{r} · {titles[r]}",
                key="signoff_req",
            )
            st.radio(
                "Entscheidung",
                ["abgenommen", "zurückgestellt"],
                horizontal=True,
                key="signoff_decision",
            )
            st.text_input("Grund (bei zurückgestellt nötig)", key="signoff_reason")
            st.button(
                "Entscheidung speichern",
                icon=":material/save:",
                on_click=on_signoff,
                args=({need.id: need for need in tracking.requirements},),
            )
        messages(errors, warnings)
        if tracking.requirements and not errors:  # with nothing to accept, nothing is closed
            st.success("Nichts Schweres ist offen: Das Projekt lässt sich abschließen.")

    with st.container(border=True, key="panel-lessons"):
        heading(
            "lightbulb",
            "Lessons Learned",
            agent="entwirft",
            python="prüft die Bezüge",
            du="änderst",
        )
        st.caption(
            "An den Agenten gehen Kennzahlen, Wochenrückblicke, Fehler und Abnahmen, keine Angaben "
            "zum "
            "Team. Freie Texte können trotzdem Namen enthalten, daher die Zustimmung."
        )
        if st.button(
            "Lessons Learned mit dem Agenten entwerfen",
            icon=":material/play_arrow:",
            disabled=not consent(
                "consent_abschluss",
                "Wochenrückblicke, Fehler und Abnahmen mit ihren freien Texten",
            ),
        ):
            drafted = run_with_progress(
                "Der Agent entwirft die Lessons Learned …",
                lambda on_round: closing.run_lessons(tracking, today, on_round=on_round),
            )
            if drafted is not None and save_lessons(tracking, drafted.items):
                state.lessons_version = state.get("lessons_version", 0) + 1
                st.rerun()
        edited, conflict = kept_editor(
            "lessons_editor_",
            "lessons_version",
            tracking.lessons,
            pd.DataFrame(lesson_rows(tracking.lessons), columns=LESSON_COLUMNS),
            num_rows="dynamic",
            width="stretch",
        )
        if st.button("Lessons Learned speichern", icon=":material/save:") and not conflict:
            try:
                items = rows_to_lessons(edited.to_dict("records"))
            except InputError as err:
                st.error(f"Bitte korrigieren:\n\n{as_text(str(err))}")
            else:
                if save_lessons(tracking, items):
                    st.rerun()
        if tracking.lessons:
            messages([], check_lessons(Lessons(items=tracking.lessons), tracking))

    with st.container(border=True, key="panel-document"):
        heading("description", "Abschlussbericht", python="füllt die Vorlage aus")
        charter = life.charter if life is not None else None
        document = closing_document(tracking, plan, evaluate(tracking, today), charter)
        st.download_button(
            "Abschlussbericht als Markdown herunterladen",
            document,
            file_name="abschlussbericht.md",
            icon=":material/download:",
        )

with operations_tab:
    st.caption(
        "Optional: Viele Gruppenprojekte gehen nie in Betrieb. Wenn doch, hält das "
        "Betriebshandbuch je Baustein fest, wer verantwortlich ist (eine Rolle, kein Name) und "
        "wie er bereitgestellt, überwacht und zurückgenommen wird. Störungen gehen in den "
        "nächsten Durchlauf ein."
    )
    with st.container(border=True, key="panel-handbook"):
        heading("settings", "Betriebshandbuch", du="trägst ein", python="prüft")
        if design is None:
            st.info("Noch kein Entwurf: Ohne Bausteine gibt es kein Betriebshandbuch.")
            st.page_link("views/entwurf.py", label="Zum Entwurf", icon=":material/arrow_forward:")
        else:
            handbook, handbook_conflict = kept_editor(
                "operations_editor_",
                "operations_version",
                (design, tracking.operations),
                pd.DataFrame(
                    operation_rows(design, tracking.operations), columns=OPERATION_COLUMNS
                ),
                disabled=["Baustein", "Name"],
                width="stretch",
            )
            if (
                st.button("Betriebshandbuch speichern", icon=":material/save:")
                and not handbook_conflict
            ):
                items = rows_to_operations(handbook.to_dict("records"))
                if change(lambda t: t.model_copy(update={"operations": items})):
                    st.rerun()
            messages(*check_operations(design, tracking.operations))

    with st.container(border=True, key="panel-incidents"):
        heading("warning", "Störungen", du="erfasst")
        if design is not None:
            names = {c.id: c.name for c in design.components}
            st.selectbox(
                "Baustein",
                list(names),
                format_func=lambda c: f"{c} · {names[c]}",
                key="incident_component",
            )
            st.text_input("Auswirkung", key="incident_impact")
            st.text_input("Ursache", key="incident_cause")
            st.text_input("Maßnahme", key="incident_measure")
            st.button("Störung erfassen", icon=":material/add:", on_click=on_incident)
        for incident in [i for i in tracking.incidents if i.status == "offen"]:
            st.button(
                f"{incident.id}: behoben",
                key=f"incident_fixed_{incident.id}",
                icon=":material/check:",
                on_click=on_fixed,
                args=(incident.id,),
            )
        if tracking.incidents:
            st.dataframe(
                pd.DataFrame([i.model_dump(mode="json") for i in tracking.incidents]),
                hide_index=True,
            )
        else:
            st.caption("Keine Störungen erfasst.")

with next_tab:
    st.caption(
        "Was kommt in den nächsten Durchlauf? Python stellt den Backlog zusammen, jeder Eintrag "
        "mit seiner Herkunft. Mit dem neuen Durchlauf beginnt ein neues Vorhaben: Der Agent "
        "bekommt den Backlog beim Entwurf der Anforderungen."
    )
    with st.container(border=True, key="panel-backlog"):
        heading("playlist_add", "Nächster Backlog", python="stellt zusammen")
        backlog = closing.next_backlog(tracking)
        if backlog:
            st.dataframe(
                pd.DataFrame([{"Eintrag": b.text, "Herkunft": b.origin} for b in backlog]),
                hide_index=True,
            )
        else:
            st.info(
                "Der Backlog ist leer: keine zurückgestellte Anforderung, kein offener Fehler, "
                "keine offene Maßnahme, keine offene Störung."
            )

    with st.container(border=True, key="panel-next-run"):
        heading("restart_alt", "Neuer Durchlauf", du="entscheidest")
        st.caption(
            "Legt vorhaben.json und projekt.json dieses Durchlaufs unter data/archiv/<Datum> ab "
            "und beginnt ein neues Vorhaben mit dem Backlog. Projektauftrag, Anforderungen und "
            "Plan entstehen dann neu."
        )
        # Test evidence can add closing warnings. Only closing errors prevent archiving.
        blocking = closing.check_closing(tracking, None).errors
        if blocking:
            # Each one is listed in the first tab, where it is decided.
            count = len(blocking)
            st.error(
                f"Der Abschluss ist nicht fertig: {count} offene{'r' if count == 1 else ''} "
                f"Punkt{'' if count == 1 else 'e'} im Reiter „Abnahme und Lehren“."
            )
        if state.get("next_run_basis") != tracking:
            state.next_run_basis = tracking
            state.next_run_sure = False
        sure = st.checkbox(
            "Diesen Durchlauf abschließen und ins Archiv legen.", key="next_run_sure"
        )
        start = st.button(
            "Neuen Durchlauf beginnen",
            icon=":material/restart_alt:",
            disabled=not sure or bool(blocking),
        )
        if start and sure and not blocking:
            try:
                with lifecycle.WRITE_LOCK, PROJECT_WRITE_LOCK:
                    require_current(tracking)
                    folder = closing.start_next_run(tracking, datetime.now(), DATA_DIR / "archiv")
            except InputError as err:
                st.error(as_text(str(err)))
            except OSError as err:
                st.error(
                    f"Der neue Durchlauf konnte nicht beginnen: {as_text(str(err))}. Ist eine "
                    "Datei in einem anderen Programm geöffnet?"
                )
            else:
                st.success(
                    f"Archiviert unter {as_text(str(folder))}. Weiter mit dem Projektauftrag."
                )
                st.page_link(
                    "views/auftrag.py", label="Zum Projektauftrag", icon=":material/arrow_forward:"
                )
