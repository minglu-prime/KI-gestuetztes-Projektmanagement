"""Page "Anforderungen": the PRD. The agent drafts the requirements from the charter, Python
checks that every success criterion is served, the project lead changes and approves them.
The plan is traced to them once they are approved."""

from datetime import datetime

import pandas as pd
import streamlit as st

from pm_agent import lifecycle
from pm_agent.lifecycle import (
    REQUIREMENT_COLUMNS,
    approve_requirements,
    charter_state,
    check_requirements,
    requirement_rows,
    requirements_document,
    requirements_state,
    rows_to_requirements,
)
from pm_agent.ui import (
    as_text,
    consent,
    heading,
    kept_editor,
    messages,
    notify,
    phase_chip,
    phase_verdict,
    run_with_progress,
    saved_lifecycle,
    store,
    strip,
    verdict,
)
from pm_agent.workbench import InputError

state = st.session_state

st.header("Anforderungen")
st.caption(
    "Was muss das System können, und woran erkennt man, dass es das kann? Der Agent entwirft die "
    "Anforderungen aus dem Projektauftrag, Python prüft, dass jedes Erfolgskriterium abgedeckt "
    "ist, du änderst sie und gibst sie frei. Danach plant der Agent für jede Anforderung Aufgaben."
)
life = saved_lifecycle()
if life is None:
    st.stop()
status = st.container()  # filled at the end, when the requirements of this run are known

# 1 · Grundlage --------------------------------------------------------------------------
if life.backlog:
    with st.container(border=True, key="panel-backlog"):
        st.markdown("**Offen aus dem letzten Durchlauf**")
        st.caption("Der Agent bekommt diese Punkte beim Entwurf der Anforderungen.")
        st.dataframe(
            pd.DataFrame([{"Eintrag": b.text, "Herkunft": b.origin} for b in life.backlog]),
            hide_index=True,
        )
charter_phase = charter_state(life)
if life.project is None:
    st.info(
        "Noch keine Projektidee mit Terminen. Trag sie auf der Seite Projektauftrag ein: "
        "Die Anforderungen bauen darauf auf."
    )
    st.page_link("views/auftrag.py", label="Zum Projektauftrag", icon=":material/arrow_forward:")
elif charter_phase != "freigegeben":
    st.warning(
        "Der Projektauftrag ist nicht freigegeben. Die Anforderungen lassen sich trotzdem "
        "entwerfen; geprüft wird gegen den Auftrag, wie er gerade steht."
    )

# 2 · Entwurf vom Agenten ------------------------------------------------------------------
with st.container(border=True, key="panel-draft"):
    heading(
        "smart_toy",
        "Entwurf vom Agenten",
        agent="entwirft aus dem Projektauftrag",
        python="prüft die Abdeckung",
    )
    st.caption(
        "An den Agenten gehen Projektidee, Termine, Projektauftrag und gegebenenfalls die offenen "
        "Punkte des letzten Durchlaufs. Python prüft die Abdeckung der Erfolgskriterien."
    )
    allowed = consent(
        "requirements_consent",
        "Projektidee, Termine, Projektauftrag und die offenen Punkte aus dem letzten Durchlauf",
    )
    replace = True
    if life.requirements is not None:
        replace = st.checkbox(
            "Die vorhandenen Anforderungen durch einen neuen Entwurf ersetzen.",
            key="requirements_replace",
        )
    if st.button(
        "Anforderungen mit dem Agenten entwerfen",
        icon=":material/play_arrow:",
        type="primary" if life.requirements is None else "secondary",
        disabled=life.project is None or not replace or not allowed,
    ):
        drafted = run_with_progress(
            "Der Agent entwirft die Anforderungen …",
            lambda on_round: lifecycle.run_requirements(
                life.project,
                life.charter,
                on_round=on_round,
                **({"backlog": life.backlog} if life.backlog else {}),
            ),
        )
        if drafted is not None:
            saved = store(life, life.model_copy(update={"requirements": drafted}))
            if saved is not None:
                life = saved
                state.requirements_version = state.get("requirements_version", 0) + 1

# 3 · Anforderungen ----------------------------------------------------------------------
with st.container(border=True, key="panel-requirements"):
    heading("checklist", "Anforderungen", du="änderst und ergänzt", python="prüft")
    if (
        life.requirements is None and life.project is not None
    ):  # without it, the top says what is missing
        st.info(
            "Noch keine Anforderungen. Lass sie vom Agenten entwerfen oder trag sie in der "
            "Tabelle selbst ein."
        )
    st.caption(
        "Eine Zeile pro Anforderung. Akzeptanzkriterien getrennt durch Semikolon, "
        "Erfolgskriterien des Projektauftrags (K1 …) durch Komma."
    )
    rows = requirement_rows(life.requirements) if life.requirements is not None else []
    edited_rows, conflict = kept_editor(
        "requirements_editor_",
        "requirements_version",
        life.requirements,
        pd.DataFrame(rows, columns=REQUIREMENT_COLUMNS),
        num_rows="dynamic",
        width="stretch",
        column_config={
            "ID": st.column_config.TextColumn(required=True, help="z. B. R1"),
            "User Story": st.column_config.TextColumn(
                help="Als <Rolle> will ich <etwas>, damit <Nutzen>."
            ),
            "Priorität": st.column_config.SelectboxColumn(options=["Muss", "Soll", "Kann"]),
        },
    )
    # A table emptied of saved requirements is an edit too.
    typed = life.requirements is not None or any(
        str(value).strip()
        for row in edited_rows.to_dict("records")
        for value in row.values()
        if value is not None and value == value  # empty cells come as None or NaN
    )
    edited, problem = None, None
    if typed:
        try:
            # Numbers of saved criteria and of those test cases point at stay taken.
            taken = {
                *(
                    c.id
                    for r in (life.requirements.items if life.requirements else [])
                    for c in r.criteria
                ),
                *(
                    cid
                    for case in (life.cases.cases if life.cases else [])
                    for cid in case.criteria
                ),
            }
            edited = rows_to_requirements(edited_rows.to_dict("records"), taken)
        except InputError as err:
            problem = str(err)
    unsaved = typed and edited != life.requirements
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
        if store(life, life.model_copy(update={"requirements": edited})) is not None:
            state.requirements_version = state.get("requirements_version", 0) + 1
            notify("Anforderungen gespeichert.")
            st.rerun()
    errors = []
    if life.requirements is not None:
        errors, warnings = check_requirements(life.requirements, life.charter)
        messages(errors, warnings)

# 4 · Freigabe ---------------------------------------------------------------------------
with st.container(border=True, key="panel-approve"):
    heading("verified", "Freigabe", du="gibst frei")
    phase = requirements_state(life)
    if phase == "freigegeben":
        st.success(
            f"Freigegeben am {life.requirements_ok.at:%d.%m.%Y %H:%M}. Die Planung ordnet "
            "jetzt jede Aufgabe diesen Anforderungen zu."
        )
    elif phase == "geändert":
        st.warning(
            f"Seit der Freigabe am {life.requirements_ok.at:%d.%m.%Y %H:%M} geändert, hier "
            "oder im Projektauftrag. Prüfe sie und gib sie erneut frei."
        )
    if unsaved:
        st.caption("Erst speichern, dann freigeben.")
    # Approved and unchanged: nothing to approve, and the button goes.
    if (phase != "freigegeben" or unsaved) and st.button(
        "Anforderungen freigeben",
        icon=":material/verified:",
        type="primary",
        disabled=life.requirements is None or bool(errors) or unsaved,
    ):
        if store(life, approve_requirements(life, datetime.now())) is not None:
            notify("Anforderungen freigegeben.")
            st.rerun()

# 5 · Dokument ---------------------------------------------------------------------------
if life.requirements is not None and life.project is not None:
    with st.container(border=True, key="panel-document"):
        heading("description", "Dokument", python="füllt die Vorlage aus")
        document = requirements_document(life)
        st.download_button(
            "Anforderungen als Markdown herunterladen",
            document,
            file_name="anforderungen.md",
            icon=":material/download:",
        )

status.html(
    strip(
        phase_chip("Projektauftrag", charter_phase),
        phase_chip("Anforderungen", requirements_state(life)),
    )
)
# The result on top, beside the chips: the findings of the check, or what the approval needs.
shown = phase_verdict(
    requirements_state(life),
    check_requirements(life.requirements, life.charter) if life.requirements is not None else None,
)
if shown is not None:
    with status:
        verdict(*shown)
