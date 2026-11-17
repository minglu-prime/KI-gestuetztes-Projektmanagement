"""Page "Abschluss": the project lead accepts or defers each requirement, Claude drafts the
lessons learned, Python checks that nothing severe is left open and fills the closing
report.

Buttons work through callbacks (see views/testlauf.py): they run before the page is drawn
again and can empty the fields they used."""

from datetime import date

import pandas as pd
import streamlit as st

from pm_agent import closing, lifecycle
from pm_agent.closing import (
    LESSON_COLUMNS,
    check_closing,
    check_lessons,
    closing_document,
    lesson_rows,
    rows_to_lessons,
    signoff_rows,
)
from pm_agent.models import Lessons
from pm_agent.tracking import Signoff, evaluate, load, save
from pm_agent.ui import adopted_project, as_text, consent, heading, run_with_progress
from pm_agent.workbench import InputError

state = st.session_state


def change(make) -> bool:
    try:
        current = load()
        if current is None:
            raise InputError("Es ist kein Projekt übernommen")
        save(make(current))
    except InputError as err:
        state.closing_error = str(err)
        return False
    except OSError as err:
        state.closing_error = f"Das Projekt konnte nicht gespeichert werden: {err}."
        return False
    return True


def on_signoff() -> None:
    signoff = Signoff(
        requirement_id=state.signoff_req,
        decision=state.signoff_decision,
        reason=state.signoff_reason,
    )
    if change(lambda t: closing.record_signoff(t, signoff)):
        state.signoff_reason = ""


st.header("Abschluss")
st.caption(
    "Ist jede Anforderung erfüllt, und was lernen wir daraus? Python schlägt aus Testergebnissen "
    "und Fehlern vor, was sich abnehmen lässt; du entscheidest je Anforderung. Claude entwirft "
    "die Lessons Learned aus Rückblicken und Fehlern."
)
tracking = adopted_project()
if tracking is None:
    st.stop()
try:
    life = lifecycle.load()
except InputError as err:
    st.error(f"Der Testplan konnte nicht gelesen werden: {as_text(str(err))}")
    life = None
cases = life.cases if life is not None else None
today = date.today()
if "closing_error" in state:
    st.error(as_text(state.pop("closing_error")))

with st.container(border=True, key="panel-signoff"):
    heading("verified", "Abnahme je Anforderung", python="schlägt vor", du="entscheidest")
    errors, warnings = check_closing(tracking, cases)
    if tracking.requirements:
        st.dataframe(pd.DataFrame(signoff_rows(tracking, cases)), hide_index=True)
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
        st.button("Entscheidung speichern", icon=":material/save:", on_click=on_signoff)
    for error in errors:
        st.error(as_text(error))
    for warning in warnings:
        st.warning(as_text(warning))
    if not errors:
        st.success("Nichts Schweres ist offen: Das Projekt lässt sich abschließen.")

with st.container(border=True, key="panel-lessons"):
    heading(
        "lightbulb",
        "Lessons Learned",
        claude="entwirft",
        python="prüft die Bezüge",
        du="änderst",
    )
    st.caption(
        "An Claude gehen Kennzahlen, Wochenrückblicke, Fehler und Abnahmen, keine Angaben zum "
        "Team. Freie Texte können trotzdem Namen enthalten, daher die Zustimmung."
    )
    if st.button(
        "Lessons Learned mit Claude entwerfen",
        icon=":material/play_arrow:",
        disabled=not consent("consent_abschluss"),
    ):
        drafted = run_with_progress(
            "Claude entwirft die Lessons Learned …",
            lambda on_round: closing.run_lessons(tracking, today, on_round=on_round),
        )
        if drafted is not None and change(
            lambda t: t.model_copy(update={"lessons": drafted.items})
        ):
            state.lessons_version = state.get("lessons_version", 0) + 1
            st.rerun()
    edited = st.data_editor(
        pd.DataFrame(lesson_rows(tracking.lessons), columns=LESSON_COLUMNS),
        key=f"lessons_editor_{state.get('lessons_version', 0)}",
        num_rows="dynamic",
        width="stretch",
    )
    if st.button("Lessons Learned speichern", icon=":material/save:"):
        try:
            items = rows_to_lessons(edited.to_dict("records"))
        except InputError as err:
            st.error(f"Bitte korrigieren:\n\n{as_text(str(err))}")
        else:
            if change(lambda t: t.model_copy(update={"lessons": items})):
                st.rerun()
    if tracking.lessons:
        for problem in check_lessons(Lessons(items=tracking.lessons), tracking):
            st.warning(as_text(problem))

with st.container(border=True, key="panel-document"):
    heading("description", "Abschlussbericht", python="füllt die Vorlage aus")
    document = closing_document(tracking, cases, evaluate(tracking, today))
    st.download_button(
        "Abschlussbericht als Markdown herunterladen",
        document,
        file_name="abschlussbericht.md",
        icon=":material/download:",
    )
    with st.expander("Vorschau"):
        st.markdown(document)
