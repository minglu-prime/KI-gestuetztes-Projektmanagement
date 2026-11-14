"""Page "Durchführung": record progress per task and fill project documents from templates."""

from datetime import date

import pandas as pd
import streamlit as st

from pm_agent import followup
from pm_agent.tracking import (
    PROGRESS_COLUMNS,
    STATUSES,
    apply_rows,
    evaluate,
    progress_rows,
    save,
    status_report,
    work_packages,
)
from pm_agent.ui import adopted_project, consent, run_with_progress
from pm_agent.workbench import InputError

state = st.session_state

st.header("Durchführung")
st.caption(
    "Fortschritt erfassen, den Stand von Claude zusammenfassen lassen und Projektdokumente aus "
    "Vorlagen füllen. Alle Zahlen rechnet Python aus dem übernommenen Plan und deinen Angaben."
)
tracking = adopted_project()
if tracking is None:
    st.stop()
st.caption(
    f"Projekt: {tracking.project.idea} · übernommen am {tracking.adopted:%d.%m.%Y %H:%M} · "
    f"{len(tracking.plan.tasks)} Aufgaben"
)

st.subheader("Fortschritt")
if state.pop("progress_saved", False):
    st.success("Fortschritt gespeichert (lokal in data/projekt.json, nicht im Repository).")
edited = st.data_editor(
    pd.DataFrame(progress_rows(tracking), columns=PROGRESS_COLUMNS),
    # A new key after saving: the editor starts again from the saved state.
    key=f"progress_editor_{state.get('progress_version', 0)}",
    hide_index=True,
    width="stretch",
    disabled=PROGRESS_COLUMNS[:5],
    column_config={
        "Status": st.column_config.SelectboxColumn(options=STATUSES, required=True),
        "Ist (h)": st.column_config.NumberColumn(min_value=0.0, step=0.5),
    },
)
st.caption("Änderungen gelten erst nach dem Speichern.")
if st.button("Fortschritt speichern", type="primary"):
    try:
        updated = apply_rows(tracking, edited.to_dict("records"))
    except InputError as err:
        st.error(f"Bitte korrigieren:\n\n{err}")
    else:
        save(updated)
        state.progress_saved = True
        state.progress_version = state.get("progress_version", 0) + 1
        st.rerun()

st.subheader("Durchführungs-Agent")
st.caption(
    "Claude schlägt aus Plan und gespeichertem Fortschritt die Zusammenfassung und die nächsten "
    "Schritte für den Statusbericht vor. Python nimmt den Vorschlag nur an, wenn jede Aufgabe im "
    "Verzug einen nächsten Schritt hat. Was davon gilt, entscheidest du."
)
agreed = consent("consent_durchfuehrung")
if st.button("Zusammenfassung mit Claude vorschlagen", disabled=not agreed):
    proposed = run_with_progress(
        "Claude schreibt die Zusammenfassung …",
        lambda on_round: followup.run_status_summary(tracking, date.today(), on_round=on_round),
    )
    if proposed is not None:
        state.status_summary = (tracking, proposed)
summary = None
if "status_summary" in state:
    basis, summary = state.status_summary
    if basis != tracking:
        summary = None
        st.info("Der Fortschritt hat sich seit dem Vorschlag geändert. Lass ihn neu erstellen.")
if summary is not None:
    with st.container(border=True):
        st.markdown(summary.summary)
        for step in summary.next_steps:
            st.markdown(f"- **{step.task_id}:** {step.action}")
    st.caption("Der Vorschlag steht jetzt auch im Statusbericht unten.")

st.subheader("Dokumente aus Vorlagen")
st.caption("Gefüllt aus dem übernommenen Plan und dem gespeicherten Fortschritt.")
documents = {
    "Statusbericht": (
        "statusbericht",
        status_report(tracking, evaluate(tracking, date.today()), summary),
    ),
    "Arbeitspaketbeschreibungen": ("arbeitspakete", work_packages(tracking)),
}
chosen = st.radio("Vorlage", list(documents), horizontal=True)
file_stem, text = documents[chosen]
st.download_button(
    f"{chosen} als Markdown herunterladen",
    text,
    file_name=f"{file_stem}-{date.today():%Y%m%d}.md",
    mime="text/markdown",
)
with st.container(border=True):
    st.markdown(text)
