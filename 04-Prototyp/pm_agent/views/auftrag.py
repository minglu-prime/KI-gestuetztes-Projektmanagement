"""Page "Projektauftrag": why the project exists, what belongs to it and how its success is
measured. The agent drafts it from idea and dates, Python checks it, the project lead changes it
and approves it. Kept in data/vorhaben.json with the requirements built on it."""

from datetime import datetime

import streamlit as st
from pydantic import ValidationError

from pm_agent import lifecycle
from pm_agent.lifecycle import (
    approve_charter,
    charter_document,
    charter_state,
    check_charter,
    criteria_lines,
    lines,
    lines_to_criteria,
)
from pm_agent.models import Charter, Project
from pm_agent.tools import invalid_input
from pm_agent.ui import (
    as_text,
    consent,
    heading,
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

# The fields of the charter: key in the session state, label, and how the text reads back.
FIELDS = {
    "charter_goal": "Ziel",
    "charter_benefit": "Nutzen",
    "charter_in_scope": "Im Umfang (ein Punkt pro Zeile)",
    "charter_out_of_scope": "Nicht im Umfang (ein Punkt pro Zeile)",
    "charter_stakeholders": "Beteiligte als Rollen, ohne Namen (eine pro Zeile)",
    "charter_criteria": "Erfolgskriterien (eins pro Zeile, „K1: Text“)",
    "charter_constraints": "Rahmenbedingungen (eine pro Zeile)",
}


def show(charter: Charter) -> None:
    """Put a charter into the fields. Only before they are drawn in this run."""
    state.update(
        charter_goal=charter.goal,
        charter_benefit=charter.benefit,
        charter_in_scope="\n".join(charter.in_scope),
        charter_out_of_scope="\n".join(charter.out_of_scope),
        charter_stakeholders="\n".join(charter.stakeholders),
        charter_criteria=criteria_lines(charter.success_criteria),
        charter_constraints="\n".join(charter.constraints),
    )


st.header("Projektauftrag")
st.caption(
    "Warum gibt es das Projekt, was gehört dazu und woran sieht man am Ende den Erfolg? "
    "Der Agent entwirft den Auftrag, Python prüft ihn, du änderst ihn und gibst ihn frei. Aus "
    "ihm entstehen danach die Anforderungen und der Plan."
)
life = saved_lifecycle()
if life is None:
    st.stop()
status = st.container()  # filled at the end, when the charter of this run is known

# 1 · Eckdaten ----------------------------------------------------------------------------
with st.container(border=True, key="panel-eckdaten"):
    heading("event", "Eckdaten", du="trägst Idee und Termine ein")
    saved = life.project
    if "auftrag_idea" not in state or state.get("auftrag_basis") != saved:
        state.auftrag_basis = saved
        state.auftrag_idea = saved.idea if saved else ""
        state.auftrag_start = saved.start_date if saved else None
        state.auftrag_deadline = saved.deadline if saved else None
    idea = st.text_area(
        "Projektidee",
        key="auftrag_idea",
        placeholder="Was soll gebaut werden, für wen, mit welchen Anforderungen?",
    )
    left, right = st.columns(2)
    start = left.date_input("Start", key="auftrag_start", format="DD.MM.YYYY")
    deadline = right.date_input("Deadline", key="auftrag_deadline", format="DD.MM.YYYY")
    project = None
    if not idea.strip() or start is None or deadline is None:
        st.info("Beschreibe die Projektidee und wähle Start und Deadline.")
    else:
        try:
            project = Project(
                idea=idea,
                start_date=start,
                deadline=deadline,
                free_days=life.project.free_days if life.project else [],
            )
        except ValidationError as err:
            st.error("; ".join(e["msg"].removeprefix("Value error, ") for e in err.errors()))
    if project is not None and project != life.project:
        # Saved right away: an approval made for other dates is then shown as changed.
        if (updated := store(life, life.model_copy(update={"project": project}))) is not None:
            life = updated
            state.auftrag_basis = updated.project
    st.caption("Freie Tage für alle trägst du in der Planung ein (Schritt Projekt).")

# 2 · Entwurf vom Agenten ------------------------------------------------------------------
with st.container(border=True, key="panel-draft"):
    heading(
        "smart_toy",
        "Entwurf vom Agenten",
        agent="entwirft aus Idee und Terminen",
        python="prüft ihn",
    )
    st.caption(
        "An den Agenten gehen nur Projektidee, Start und Deadline, keine Angaben zum Team. Ist der "
        "Entwurf fehlerhaft, gibt Python ihn mit den Gründen zurück, bis er stimmt."
    )
    allowed = consent("charter_consent", "Projektidee und Projekttermine")
    replace = True
    if life.charter is not None:
        replace = st.checkbox(
            "Den vorhandenen Projektauftrag durch einen neuen Entwurf ersetzen.",
            key="charter_replace",
        )
    if st.button(
        "Projektauftrag mit dem Agenten entwerfen",
        icon=":material/play_arrow:",
        type="primary" if life.charter is None else "secondary",
        disabled=project is None or project != life.project or not replace or not allowed,
    ):
        drafted = run_with_progress(
            "Der Agent entwirft den Projektauftrag …",
            lambda on_round: lifecycle.run_charter(project, on_round=on_round),
        )
        if drafted is not None:
            saved = store(life, life.model_copy(update={"charter": drafted}))
            if saved is not None:
                life = saved
                show(drafted)

# 3 · Projektauftrag ---------------------------------------------------------------------
with st.container(border=True, key="panel-charter"):
    heading("edit_note", "Projektauftrag", du="änderst und ergänzt", python="prüft")
    if life.charter is None:
        st.info(
            "Noch kein Projektauftrag. Lass ihn vom Agenten entwerfen oder schreib ihn hier selbst."
        )
    if "charter_goal" not in state:
        if life.charter is not None:
            show(life.charter)
        else:
            state.update(dict.fromkeys(FIELDS, ""))
    for key, label in FIELDS.items():
        st.text_area(label, key=key, height="content")
    typed = any(state[key].strip() for key in FIELDS)
    edited, problem = None, None
    try:
        edited = Charter(
            goal=state.charter_goal,
            benefit=state.charter_benefit,
            in_scope=lines(state.charter_in_scope),
            out_of_scope=lines(state.charter_out_of_scope),
            stakeholders=lines(state.charter_stakeholders),
            success_criteria=lines_to_criteria(state.charter_criteria),
            constraints=lines(state.charter_constraints),
        )
    except InputError as err:
        problem = f"Erfolgskriterien: {err}"
    except ValidationError as err:
        problem = "\n".join(invalid_input(err))
    unsaved = typed and edited != life.charter
    if problem and typed:
        st.error(f"Bitte korrigieren:\n\n{as_text(problem)}")
    if unsaved:
        st.caption("Änderungen sind noch nicht gespeichert.")
    if st.button(
        "Änderungen speichern und prüfen",
        icon=":material/fact_check:",
        disabled=edited is None or not unsaved,
    ):
        if store(life, life.model_copy(update={"charter": edited})) is not None:
            notify("Projektauftrag gespeichert.")
            st.rerun()
    errors = check_charter(life.charter).errors if life.charter is not None else []
    messages(errors)

# 4 · Freigabe ---------------------------------------------------------------------------
with st.container(border=True, key="panel-approve"):
    heading("verified", "Freigabe", du="gibst frei")
    phase = charter_state(life)
    if phase == "freigegeben":
        st.success(f"Freigegeben am {life.charter_ok.at:%d.%m.%Y %H:%M}.")
    elif phase == "geändert":
        st.warning(
            f"Seit der Freigabe am {life.charter_ok.at:%d.%m.%Y %H:%M} geändert. Prüfe den "
            "Auftrag und gib ihn erneut frei: Anforderungen und Plan bauen auf ihm auf."
        )
    blocked = life.charter is None or bool(errors) or unsaved
    if unsaved:
        st.caption("Erst speichern, dann freigeben.")
    # Approved: nothing to approve until a saved change. The caption above says so.
    if phase != "freigegeben" and st.button(
        "Projektauftrag freigeben",
        icon=":material/verified:",
        type="primary",
        disabled=blocked,
    ):
        if store(life, approve_charter(life, datetime.now())) is not None:
            notify("Projektauftrag freigegeben.")
            st.rerun()

# 5 · Dokument ---------------------------------------------------------------------------
if life.charter is not None and life.project is not None:
    with st.container(border=True, key="panel-document"):
        heading("description", "Dokument", python="füllt die Vorlage aus")
        document = charter_document(life)
        st.download_button(
            "Projektauftrag als Markdown herunterladen",
            document,
            file_name="projektauftrag.md",
            icon=":material/download:",
        )

status.html(strip(phase_chip("Projektauftrag", charter_state(life))))
# The result on top, beside the chips: the findings of the check, or what the approval needs.
shown = phase_verdict(
    charter_state(life), check_charter(life.charter) if life.charter is not None else None
)
if shown is not None:
    with status:
        verdict(*shown)
