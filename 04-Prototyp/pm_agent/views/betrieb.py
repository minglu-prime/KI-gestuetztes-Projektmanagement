"""Page "Betrieb" (optional: many student projects are never run): who runs each component
of the design, how it is deployed, watched and taken back, and which incidents happened."""

from datetime import date

import pandas as pd
import streamlit as st

from pm_agent import closing, lifecycle
from pm_agent.closing import OPERATION_COLUMNS, check_operations, operation_rows, rows_to_operations
from pm_agent.tracking import Incident, load, save
from pm_agent.ui import adopted_project, as_text, heading, kept_editor
from pm_agent.workbench import InputError

state = st.session_state


def change(make) -> bool:
    try:
        current = load()
        if current is None:
            raise InputError("Es ist kein Projekt übernommen")
        save(make(current))
    except InputError as err:
        state.operations_error = str(err)
        return False
    except OSError as err:
        state.operations_error = f"Das Projekt konnte nicht gespeichert werden: {err}."
        return False
    return True


st.header("Betrieb")
st.caption(
    "Optional: Viele Gruppenprojekte gehen nie in Betrieb. Wenn doch, hält das Betriebshandbuch "
    "je Baustein fest, wer verantwortlich ist (eine Rolle, kein Name) und wie er bereitgestellt, "
    "überwacht und zurückgenommen wird. Störungen gehen in den nächsten Durchlauf ein."
)
tracking = adopted_project()
if tracking is None:
    st.stop()
try:
    life = lifecycle.load()
except InputError as err:
    st.error(f"Der Entwurf konnte nicht gelesen werden: {as_text(str(err))}")
    st.stop()
design = life.design if life is not None else None
if "operations_error" in state:
    st.error(as_text(state.pop("operations_error")))


def on_incident() -> None:
    incident = Incident(
        on=date.today(),
        component_id=state.incident_component,
        impact=state.incident_impact,
        cause=state.incident_cause,
        measure=state.incident_measure,
    )
    if not incident.impact:
        state.operations_error = "Beschreib die Auswirkung der Störung."
        return
    if change(lambda t: closing.record_incident(t, incident, design)):
        for key in ["incident_impact", "incident_cause", "incident_measure"]:
            state[key] = ""


def on_fixed(incident_id: str) -> None:
    def fix(t):
        incident = next(i for i in t.incidents if i.id == incident_id)
        return closing.record_incident(t, incident.model_copy(update={"status": "behoben"}), design)

    change(fix)


with st.container(border=True, key="panel-handbook"):
    heading("settings", "Betriebshandbuch", du="trägst ein", python="prüft")
    if design is None:
        st.info("Noch kein Entwurf: Ohne Bausteine gibt es kein Betriebshandbuch.")
        st.page_link("views/entwurf.py", label="Zum Entwurf", icon=":material/arrow_forward:")
    else:
        edited = kept_editor(
            "operations_editor_",
            "operations_version",
            (design, tracking.operations),
            pd.DataFrame(operation_rows(design, tracking.operations), columns=OPERATION_COLUMNS),
            disabled=["Baustein", "Name"],
            width="stretch",
        )
        if st.button("Betriebshandbuch speichern", icon=":material/save:"):
            items = rows_to_operations(edited.to_dict("records"))
            if change(lambda t: t.model_copy(update={"operations": items})):
                st.rerun()
        errors, warnings = check_operations(design, tracking.operations)
        for error in errors:
            st.error(as_text(error))
        for warning in warnings:
            st.warning(as_text(warning))

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
