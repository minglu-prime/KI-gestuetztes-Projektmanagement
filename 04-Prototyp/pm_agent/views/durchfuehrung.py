"""Page "Durchführung": record progress per task and fill project documents from templates."""

from datetime import date

import pandas as pd
import streamlit as st

from pm_agent import followup
from pm_agent.tracking import (
    NO_WEEK_AHEAD,
    NOTHING_AHEAD,
    NOTHING_LEFT,
    PROGRESS_COLUMNS,
    PROGRESS_READ_ONLY,
    STATUSES,
    apply_rows,
    demo_this_week,
    evaluate,
    forecast,
    percent,
    progress_rows,
    save_if_current,
    status_report,
    week_ahead,
    work_packages,
)
from pm_agent.ui import (
    adopted_project,
    as_text,
    chip,
    consent,
    forecast_verdict,
    heading,
    history_table,
    kept_editor,
    run_with_progress,
    strip,
    verdict,
)
from pm_agent.workbench import InputError

state = st.session_state

st.header("Durchführung")
st.caption(
    "Fortschritt erfassen, den Stand vom Agenten zusammenfassen lassen und Projektdokumente aus "
    "Vorlagen füllen. Alle Zahlen rechnet Python aus dem übernommenen Plan und deinen Angaben."
)
tracking = adopted_project()
if tracking is None:
    st.stop()

# Where the project stands, from the saved progress: the forecast first.
result = evaluate(tracking, date.today())
outlook = forecast(tracking, date.today())
verdict(*forecast_verdict(outlook, tracking.project.deadline))
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
st.markdown(f"**{as_text(tracking.project.idea)}**")
st.progress(result.progress, text=f"{percent(result.progress)} der Planstunden fertig")
st.caption(f"Übernommen am {tracking.adopted:%d.%m.%Y %H:%M} · {len(tracking.plan.tasks)} Aufgaben")

with st.container(border=True, key="panel-ahead"):
    heading(
        "event_upcoming",
        "Die nächsten fünf Arbeitstage",
        python="plant aus deinem Fortschritt voraus",
    )
    ahead = week_ahead(tracking, date.today())
    demo = demo_this_week(tracking, date.today())
    if demo:
        st.info(as_text(demo), icon=":material/slideshow:")
    if outlook.problem:
        st.error(
            f"{NO_WEEK_AHEAD} {outlook.problem}. Prüfe Status und Rest-Stunden in der Tabelle "
            "unten."
        )
    elif outlook.end is None:
        st.success(NOTHING_LEFT)
    elif not ahead:
        # Reachable when everyone with unfinished work is away for the whole time.
        st.info(NOTHING_AHEAD)
    else:
        st.dataframe(pd.DataFrame(ahead), hide_index=True)
        st.caption(
            "Was laut Prognose bis in fünf Arbeitstagen beginnt, je Person in der Reihenfolge "
            "der Arbeit. Die Prognose plant alles Unfertige ab heute neu ein."
        )

with st.container(border=True, key="panel-progress"):
    heading("edit_note", "Fortschritt", du="trägst Status und Stunden ein")
    if state.pop("progress_saved", False):
        st.success("Fortschritt gespeichert (lokal in data/projekt.json, nicht im Repository).")
    # Unsaved edits survive a visit to another page; the forecast columns are computed anew.
    # Saving raises the version: the editor starts again from the saved state.
    edited, conflict = kept_editor(
        "progress_editor_",
        "progress_version",
        tracking,
        pd.DataFrame(progress_rows(tracking), columns=PROGRESS_COLUMNS),
        columns=[c for c in PROGRESS_COLUMNS if c not in PROGRESS_READ_ONLY],
        hide_index=True,
        width="stretch",
        disabled=PROGRESS_READ_ONLY,
        column_config={
            # Narrower than its longest title (shown in full on hover): otherwise the columns
            # to fill in lay beyond the right edge of the panel.
            "Aufgabe": st.column_config.TextColumn(width="medium"),
            "Status": st.column_config.SelectboxColumn(options=STATUSES, required=True),
            "Fertig am": st.column_config.DateColumn(
                format="DD.MM.YYYY",
                width=95,  # a date; left empty it took twice that and pushed out "Notiz"
                help="Wird beim Speichern auf heute gesetzt, wenn die Aufgabe fertig wird. "
                "Nachtragen, wenn sie früher fertig war.",
            ),
            "Ist (h)": st.column_config.NumberColumn(format="localized", min_value=0.0, step=0.5),
            "Rest (h)": st.column_config.NumberColumn(
                format="localized",
                min_value=0.0,
                step=0.5,
                help="Was noch zu tun ist, wenn es von Plan minus Ist abweicht. Leer lassen, "
                "wenn unbekannt. Die Prognose auf der Seite Kontrolle rechnet damit.",
            ),
        },
    )
    st.caption(
        "Status, Fertig am, Ist-Stunden, Rest und Notiz lassen sich ändern. Änderungen gelten "
        "erst nach dem Speichern. „Prognose Ende“ zeigt, wann die Aufgabe nach heutigem Stand "
        "fertig wird."
    )
    history_table(tracking)
    if st.button("Fortschritt speichern", type="primary", icon=":material/save:") and not conflict:
        try:
            updated = apply_rows(tracking, edited.to_dict("records"))
        except InputError as err:
            st.error(f"Bitte korrigieren:\n\n{as_text(str(err))}")
        else:
            try:
                save_if_current(tracking, updated)
            except (InputError, OSError) as err:
                st.error(f"Der Fortschritt konnte nicht gespeichert werden: {as_text(str(err))}")
            else:
                state.progress_saved = True
                state.progress_version = state.get("progress_version", 0) + 1
                st.rerun()

with st.container(border=True, key="panel-agent"):
    heading(
        "smart_toy",
        "Durchführungs-Agent",
        agent="schreibt einen Vorschlag",
        python="prüft ihn",
        du="entscheidest, was gilt",
    )
    st.caption(
        "Der Agent schlägt aus Plan und gespeichertem Fortschritt die Zusammenfassung und die "
        "nächsten Schritte für den Statusbericht vor. Python nimmt den Vorschlag nur an, wenn "
        "jede Aufgabe im Verzug einen nächsten Schritt hat. Was davon gilt, entscheidest du."
    )
    agreed = consent("consent_durchfuehrung")
    if st.button(
        "Zusammenfassung mit dem Agenten vorschlagen",
        icon=":material/play_arrow:",
        disabled=not agreed,
    ):
        proposed = run_with_progress(
            "Der Agent schreibt die Zusammenfassung …",
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
            st.markdown(as_text(summary.summary))
            for step in summary.next_steps:
                st.markdown(f"- **{as_text(step.task_id)}:** {as_text(step.action)}")
        st.caption("Der Vorschlag steht jetzt auch im Statusbericht unten.")

with st.container(border=True, key="panel-documents"):
    heading("description", "Dokumente aus Vorlagen", python="füllt sie aus")
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

if st.button("Weiter zur Kontrolle", icon=":material/arrow_forward:"):
    st.switch_page("views/kontrolle.py")
