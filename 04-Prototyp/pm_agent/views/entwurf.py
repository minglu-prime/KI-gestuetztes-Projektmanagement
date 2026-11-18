"""Page "Entwurf": the parts of the system, their contracts and the flows between them.
Claude drafts it from the requirements, Python checks it and draws the sequence diagrams,
the project lead changes and approves it."""

from datetime import datetime

import pandas as pd
import streamlit as st

from pm_agent import lifecycle
from pm_agent.diagram import sequence_svg
from pm_agent.lifecycle import (
    COMPONENT_COLUMNS,
    FLOW_COLUMNS,
    INTERFACE_COLUMNS,
    STEP_COLUMNS,
    approve_design,
    check_design,
    design_document,
    design_rows,
    design_state,
    requirements_state,
    rows_to_design,
)
from pm_agent.ui import (
    as_text,
    consent,
    heading,
    kept_editor,
    phase_chip,
    run_with_progress,
    saved_lifecycle,
    store,
    strip,
)
from pm_agent.workbench import InputError

state = st.session_state

st.header("Entwurf")
st.caption(
    "Wie ist das System gebaut? Claude entwirft aus den Anforderungen die Bausteine, ihre "
    "Schnittstellen und die Abläufe zwischen ihnen. Python prüft, dass jeder Ablauf zu den "
    "Schnittstellen passt, und zeichnet daraus die Sequenzdiagramme. Du änderst und gibst frei."
)
life = saved_lifecycle()
if life is None:
    st.stop()
status = st.container()  # filled at the end, when the design of this run is known

# 1 · Grundlage --------------------------------------------------------------------------
needs_phase = requirements_state(life)
if life.project is None:
    st.info(
        "Noch keine Projektidee mit Terminen. Trag sie auf der Seite Projektauftrag ein: "
        "Der Entwurf baut darauf auf."
    )
    st.page_link("views/auftrag.py", label="Zum Projektauftrag", icon=":material/arrow_forward:")
elif life.requirements is None:
    st.info(
        "Noch keine Anforderungen. Ohne sie lässt sich nicht prüfen, ob jede Muss-Anforderung "
        "einen Ablauf hat."
    )
    st.page_link(
        "views/anforderungen.py", label="Zu den Anforderungen", icon=":material/arrow_forward:"
    )
elif needs_phase != "freigegeben":
    st.warning(
        "Die Anforderungen sind nicht freigegeben. Der Entwurf lässt sich trotzdem anlegen; "
        "geprüft wird gegen die Anforderungen, wie sie gerade stehen."
    )

# 2 · Entwurf von Claude ------------------------------------------------------------------
with st.container(border=True, key="panel-draft"):
    heading(
        "smart_toy",
        "Entwurf von Claude",
        claude="entwirft aus den Anforderungen",
        python="prüft die Abläufe",
    )
    st.caption(
        "An Claude gehen Projektidee, Termine, Projektauftrag und Anforderungen, keine Angaben "
        "zum Team. Python gibt den Entwurf zurück, bis jede Muss-Anforderung einen Ablauf hat "
        "und jeder Schritt zu seiner Schnittstelle passt."
    )
    allowed = consent("design_consent", "Projektidee, Termine, Projektauftrag und Anforderungen")
    replace = True
    if life.design is not None:
        replace = st.checkbox(
            "Den vorhandenen Entwurf durch einen neuen ersetzen.", key="design_replace"
        )
    if st.button(
        "Entwurf mit Claude entwerfen",
        icon=":material/play_arrow:",
        type="primary" if life.design is None else "secondary",
        disabled=life.project is None or not replace or not allowed,
    ):
        drafted = run_with_progress(
            "Claude entwirft das System …",
            lambda on_round: lifecycle.run_design(
                life.project, life.charter, life.requirements, on_round=on_round
            ),
        )
        if drafted is not None:
            saved = store(life, life.model_copy(update={"design": drafted}))
            if saved is not None:
                life = saved
                state.design_version = state.get("design_version", 0) + 1

# 3 · Bausteine, Schnittstellen, Abläufe --------------------------------------------------
TABLES = [
    ("components", "Bausteine", COMPONENT_COLUMNS),
    ("interfaces", "Schnittstellen", INTERFACE_COLUMNS),
    ("flows", "Abläufe", FLOW_COLUMNS),
    ("steps", "Schritte", STEP_COLUMNS),
]
HELP = {
    "components": "Art: Rolle (wer das System benutzt), Komponente (baut das Team) oder "
    "Fremdsystem (gibt es schon).",
    "interfaces": "Nutzer durch Komma getrennt. Eingabe und Ausgabe als `name: Typ, notiz?: "
    "Text` (? = optional). Fehler als `409 Raum belegt; 404 Raum unbekannt`.",
    "flows": "Anforderungen durch Komma getrennt (R1, R2 …).",
    "steps": "Ein Schritt pro Zeile, in der Reihenfolge des Ablaufs. Ein Aufruf geht vom Nutzer "
    "an den Anbieter der Schnittstelle, eine Antwort zurück.",
}
CONFIG = {
    "components": {
        "Art": st.column_config.SelectboxColumn(options=["Rolle", "Komponente", "Fremdsystem"])
    },
    "steps": {"Art": st.column_config.SelectboxColumn(options=["Aufruf", "Antwort"])},
}
with st.container(border=True, key="panel-design"):
    heading("account_tree", "Bausteine und Abläufe", du="änderst und ergänzt", python="prüft")
    if life.design is None:
        st.info("Noch kein Entwurf. Lass ihn von Claude entwerfen oder trag ihn selbst ein.")
    rows = (
        design_rows(life.design) if life.design is not None else {key: [] for key, _, _ in TABLES}
    )
    edited_rows = {}
    conflict = False
    for (key, _title, columns), tab in zip(TABLES, st.tabs([t for _, t, _ in TABLES]), strict=True):
        with tab:
            st.caption(HELP[key])
            frame, table_conflict = kept_editor(
                f"design_{key}_",
                "design_version",
                life.design,
                pd.DataFrame(rows[key], columns=columns),
                num_rows="dynamic",
                width="stretch",
                column_config=CONFIG.get(key),
            )
            edited_rows[key] = frame.to_dict("records")
            conflict |= table_conflict
    # A design emptied of its saved rows is an edit too.
    typed = life.design is not None or any(
        str(value).strip()
        for table in edited_rows.values()
        for row in table
        for value in row.values()
        if value is not None and value == value  # empty cells come as None or NaN
    )
    edited, problem = None, None
    if typed:
        try:
            edited = rows_to_design(edited_rows)
        except InputError as err:
            problem = str(err)
    unsaved = typed and edited != life.design
    if problem:
        st.error(f"Bitte korrigieren:\n\n{as_text(problem)}")
    if unsaved:
        st.caption("Änderungen sind noch nicht gespeichert.")
    can_save = edited is not None and unsaved and not conflict
    if (
        st.button(
            "Änderungen speichern und prüfen",
            icon=":material/fact_check:",
            disabled=not can_save,
        )
        and can_save
    ):
        if store(life, life.model_copy(update={"design": edited})) is not None:
            st.rerun()
    errors = []
    if life.design is not None:
        errors, warnings = check_design(life.design, life.requirements)
        for error in errors:
            st.error(as_text(error))
        for warning in warnings:
            st.warning(as_text(warning))

# 4 · Diagramme --------------------------------------------------------------------------
if life.design is not None:
    with st.container(border=True, key="panel-diagram"):
        heading("schema", "Sequenzdiagramme", python="zeichnet aus den Schritten")
        st.caption(
            "So wie gespeichert. Die Beschriftung kommt aus den Schnittstellen: Ein Aufruf "
            "zeigt die Eingabefelder, eine Antwort die Ausgabefelder."
        )
        flows = {f.id: f for f in life.design.flows}
        chosen = st.selectbox(
            "Ablauf",
            list(flows),
            format_func=lambda fid: f"{fid} · {flows[fid].title}",
            key="design_flow",
        )
        if chosen is not None:
            # st.html sanitizes SVG away. The SVG is built by Python with every text escaped.
            st.markdown(
                f'<div class="diagram">{sequence_svg(flows[chosen], life.design)}</div>',
                unsafe_allow_html=True,
            )

# 5 · Freigabe ---------------------------------------------------------------------------
with st.container(border=True, key="panel-approve"):
    heading("verified", "Freigabe", du="gibst frei")
    phase = design_state(life)
    if phase == "freigegeben":
        st.success(
            f"Freigegeben am {life.design_ok.at:%d.%m.%Y %H:%M}. Die Planung bekommt Bausteine "
            "und Schnittstellen als Grundlage für die Aufgaben."
        )
    elif phase == "geändert":
        st.warning(
            f"Seit der Freigabe am {life.design_ok.at:%d.%m.%Y %H:%M} geändert, hier oder in "
            "einer Phase davor. Prüfe ihn und gib ihn erneut frei."
        )
    if unsaved:
        st.caption("Erst speichern, dann freigeben.")
    if st.button(
        "Entwurf freigeben",
        icon=":material/verified:",
        type="primary",
        disabled=life.design is None or bool(errors) or unsaved or phase == "freigegeben",
    ):
        if store(life, approve_design(life, datetime.now())) is not None:
            st.rerun()

# 6 · Dokument ---------------------------------------------------------------------------
if life.design is not None and life.project is not None:
    with st.container(border=True, key="panel-document"):
        heading("description", "Dokument", python="füllt die Vorlage aus")
        document = design_document(life)
        st.download_button(
            "Entwurf als Markdown herunterladen",
            document,
            file_name="entwurf.md",
            icon=":material/download:",
        )
        st.caption("Die Diagramme stehen als Mermaid im Dokument; GitHub zeigt sie als Bild.")
        with st.expander("Vorschau"):
            st.markdown(document)

status.html(
    strip(
        phase_chip("Anforderungen", needs_phase),
        phase_chip("Entwurf", design_state(life)),
    )
)
