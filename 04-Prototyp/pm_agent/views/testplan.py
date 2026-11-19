"""Page "Testplan": test cases for every acceptance criterion and every interface. Claude
drafts them, Python checks the coverage, the project lead changes and approves them. The
results are entered later, on the page Test."""

from datetime import datetime

import pandas as pd
import streamlit as st

from pm_agent import lifecycle
from pm_agent.lifecycle import (
    CASE_COLUMNS,
    approve_cases,
    case_rows,
    cases_document,
    cases_state,
    check_cases,
    design_state,
    requirements_state,
    rows_to_cases,
)
from pm_agent.ui import (
    as_text,
    consent,
    heading,
    kept_editor,
    messages,
    phase_chip,
    run_with_progress,
    saved_lifecycle,
    store,
    strip,
)
from pm_agent.workbench import InputError

state = st.session_state

st.header("Testplan")
st.caption(
    "Woran erkennt man, dass das System tut, was die Anforderungen verlangen, und dass seine "
    "Teile zusammenpassen? Claude entwirft Testfälle aus den Akzeptanzkriterien und den "
    "Schnittstellen, Python prüft die Abdeckung, du änderst und gibst frei. Ausführen wird "
    "das Team; die Ergebnisse trägst du auf der Seite Test ein."
)
life = saved_lifecycle()
if life is None:
    st.stop()
status = st.container()  # filled at the end, when the cases of this run are known

# 1 · Grundlage --------------------------------------------------------------------------
if life.project is None:
    st.info("Noch keine Projektidee mit Terminen. Trag sie auf der Seite Projektauftrag ein.")
    st.page_link("views/auftrag.py", label="Zum Projektauftrag", icon=":material/arrow_forward:")
elif life.requirements is None:
    st.info(
        "Noch keine Anforderungen. Ohne Akzeptanzkriterien gibt es nichts zu testen; lege sie "
        "auf der Seite Anforderungen an."
    )
    st.page_link(
        "views/anforderungen.py", label="Zu den Anforderungen", icon=":material/arrow_forward:"
    )
elif "freigegeben" not in (requirements_state(life), design_state(life)):
    st.warning(
        "Anforderungen und Entwurf sind nicht freigegeben. Der Testplan lässt sich trotzdem "
        "anlegen; geprüft wird gegen den Stand, wie er gerade ist."
    )

# 2 · Entwurf von Claude ------------------------------------------------------------------
with st.container(border=True, key="panel-draft"):
    heading(
        "smart_toy",
        "Entwurf von Claude",
        claude="entwirft aus Kriterien und Schnittstellen",
        python="prüft die Abdeckung",
    )
    st.caption(
        "An Claude gehen Projektidee, Termine, Anforderungen und Schnittstellen, keine Angaben "
        "zum Team. Python gibt den Entwurf zurück, bis jedes Akzeptanzkriterium einer "
        "Muss-Anforderung einen Testfall hat."
    )
    allowed = consent(
        "cases_consent", "Projektidee, Termine, Anforderungen und Schnittstellen des Systementwurfs"
    )
    replace = True
    if life.cases is not None:
        replace = st.checkbox(
            "Die vorhandenen Testfälle durch einen neuen Entwurf ersetzen.", key="cases_replace"
        )
    if st.button(
        "Testfälle mit Claude entwerfen",
        icon=":material/play_arrow:",
        type="primary" if life.cases is None else "secondary",
        disabled=life.project is None or not replace or not allowed,
    ):
        drafted = run_with_progress(
            "Claude entwirft die Testfälle …",
            lambda on_round: lifecycle.run_cases(
                life.project, life.requirements, life.design, on_round=on_round
            ),
        )
        if drafted is not None:
            saved = store(life, life.model_copy(update={"cases": drafted}))
            if saved is not None:
                life = saved
                state.cases_version = state.get("cases_version", 0) + 1

# 3 · Testfälle --------------------------------------------------------------------------
with st.container(border=True, key="panel-cases"):
    heading("rule", "Testfälle", du="änderst und ergänzt", python="prüft")
    if life.cases is None and life.project is not None:  # without it, the top says what is missing
        st.info("Noch keine Testfälle. Lass sie von Claude entwerfen oder trag sie selbst ein.")
    st.caption(
        "Eine Zeile pro Testfall. Kriterien (R1.1 …) durch Komma, Schritte durch Semikolon "
        "getrennt. Ein Integrationstest nennt eine Schnittstelle (S1 …) und, wenn er einen Fehler "
        "auslösen soll, dessen Code."
    )
    rows = case_rows(life.cases) if life.cases is not None else []
    edited_rows, conflict = kept_editor(
        "cases_editor_",
        "cases_version",
        life.cases,
        pd.DataFrame(rows, columns=CASE_COLUMNS),
        num_rows="dynamic",
        width="stretch",
        column_config={
            "ID": st.column_config.TextColumn(required=True, help="z. B. T1"),
            "Art": st.column_config.SelectboxColumn(options=["Akzeptanz", "Integration"]),
        },
    )
    # A table emptied of saved cases is an edit too.
    typed = life.cases is not None or any(
        str(value).strip()
        for row in edited_rows.to_dict("records")
        for value in row.values()
        if value is not None and value == value  # empty cells come as None or NaN
    )
    edited, problem = None, None
    if typed:
        try:
            edited = rows_to_cases(edited_rows.to_dict("records"))
        except InputError as err:
            problem = str(err)
    unsaved = typed and edited != life.cases
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
        if store(life, life.model_copy(update={"cases": edited})) is not None:
            st.rerun()
    errors = []
    if life.cases is not None:
        errors, warnings = check_cases(life.cases, life.requirements, life.design)
        messages(errors, warnings)

# 4 · Freigabe ---------------------------------------------------------------------------
with st.container(border=True, key="panel-approve"):
    heading("verified", "Freigabe", du="gibst frei")
    phase = cases_state(life)
    if phase == "freigegeben":
        st.success(
            f"Freigegeben am {life.cases_ok.at:%d.%m.%Y %H:%M}. Die Ergebnisse trägst du auf "
            "der Seite Test ein."
        )
    elif phase == "geändert":
        st.warning(
            f"Seit der Freigabe am {life.cases_ok.at:%d.%m.%Y %H:%M} geändert, hier oder in "
            "einer Phase davor. Prüfe die Testfälle und gib sie erneut frei."
        )
    if unsaved:
        st.caption("Erst speichern, dann freigeben.")
    if st.button(
        "Testplan freigeben",
        icon=":material/verified:",
        type="primary",
        disabled=life.cases is None or bool(errors) or unsaved or phase == "freigegeben",
    ):
        if store(life, approve_cases(life, datetime.now())) is not None:
            st.rerun()

# 5 · Dokument ---------------------------------------------------------------------------
if life.cases is not None and life.project is not None:
    with st.container(border=True, key="panel-document"):
        heading("description", "Dokument", python="füllt die Vorlage aus")
        document = cases_document(life)
        st.download_button(
            "Testplan als Markdown herunterladen",
            document,
            file_name="testplan.md",
            icon=":material/download:",
        )
        with st.expander("Vorschau"):
            st.markdown(document)

status.html(
    strip(
        phase_chip("Anforderungen", requirements_state(life)),
        phase_chip("Entwurf", design_state(life)),
        phase_chip("Testplan", cases_state(life)),
    )
)
