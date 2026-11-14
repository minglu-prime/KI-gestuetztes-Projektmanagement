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
    percent,
    progress_rows,
    save,
    status_report,
    work_packages,
)
from pm_agent.ui import adopted_project, chip, consent, run_with_progress, strip
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

# Where the project stands, from the saved progress.
result = evaluate(tracking, date.today())
finished = sum(t.status == "fertig" for t in result.tasks)
running = sum(t.status == "in Arbeit" for t in result.tasks)
late = len(result.overdue)
st.html(
    strip(
        chip(
            f"{finished} von {len(result.tasks)} Aufgaben fertig",
            "on" if finished == len(result.tasks) else "",
        ),
        chip(f"{running} in Arbeit", "on" if running else ""),
        chip(f"{late} im Verzug", "warn") if late else chip("Kein Verzug", "on"),
    )
)
st.markdown(f"**{tracking.project.idea}**")
st.progress(result.progress, text=f"{percent(result.progress)} der Planstunden fertig")
st.caption(f"Übernommen am {tracking.adopted:%d.%m.%Y %H:%M} · {len(tracking.plan.tasks)} Aufgaben")

with st.container(border=True, key="panel-progress"):
    st.markdown("#### :material/edit_note: Fortschritt")
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
    st.caption(
        "Status, Ist-Stunden und Notiz lassen sich ändern. Änderungen gelten erst nach dem "
        "Speichern."
    )
    if st.button("Fortschritt speichern", type="primary", icon=":material/save:"):
        try:
            updated = apply_rows(tracking, edited.to_dict("records"))
        except InputError as err:
            st.error(f"Bitte korrigieren:\n\n{err}")
        else:
            save(updated)
            state.progress_saved = True
            state.progress_version = state.get("progress_version", 0) + 1
            st.rerun()

with st.container(border=True, key="panel-agent"):
    st.markdown("#### :material/smart_toy: Durchführungs-Agent")
    st.caption(
        "Claude schlägt aus Plan und gespeichertem Fortschritt die Zusammenfassung und die "
        "nächsten Schritte für den Statusbericht vor. Python nimmt den Vorschlag nur an, wenn "
        "jede Aufgabe im Verzug einen nächsten Schritt hat. Was davon gilt, entscheidest du."
    )
    agreed = consent("consent_durchfuehrung")
    if st.button(
        "Zusammenfassung mit Claude vorschlagen",
        icon=":material/play_arrow:",
        disabled=not agreed,
    ):
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
        with st.container(border=True, key="preview-summary"):
            st.markdown(summary.summary)
            for step in summary.next_steps:
                st.markdown(f"- **{step.task_id}:** {step.action}")
        st.caption("Der Vorschlag steht jetzt auch im Statusbericht unten.")

with st.container(border=True, key="panel-documents"):
    st.markdown("#### :material/description: Dokumente aus Vorlagen")
    st.caption("Gefüllt aus dem übernommenen Plan und dem gespeicherten Fortschritt.")
    documents = {
        "Statusbericht": ("statusbericht", status_report(tracking, result, summary)),
        "Arbeitspaketbeschreibungen": ("arbeitspakete", work_packages(tracking)),
    }
    chosen = st.radio("Vorlage", list(documents), horizontal=True)
    file_stem, text = documents[chosen]
    st.download_button(
        f"{chosen} als Markdown herunterladen",
        text,
        file_name=f"{file_stem}-{date.today():%Y%m%d}.md",
        mime="text/markdown",
        icon=":material/download:",
    )
    with st.container(border=True, key="preview-document"):
        st.markdown(text)

if st.button("Weiter zur Kontrolle", icon=":material/arrow_forward:"):
    st.switch_page("pages/kontrolle.py")
