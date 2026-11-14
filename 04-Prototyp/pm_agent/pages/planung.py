"""Page "Planung": team, project, planning, result, edit, export. Started through app.py.

All six steps are tabs on this page, so every widget is rendered on every run. Streamlit drops
the state of widgets that are not rendered. For the other pages of the site the simple widgets
use persist_state="session"; the two table editors cannot, so their content is kept in the
session state and restored when the user comes back (see restore_editors).
"""

import time
from datetime import date, datetime
from html import escape

import altair as alt
import pandas as pd
import streamlit as st
from anthropic import APIError
from pydantic import ValidationError

from pm_agent.agent import PlanningError, run_planning
from pm_agent.models import Project
from pm_agent.planning import check_plan
from pm_agent.tracking import adopt, has_progress
from pm_agent.tracking import load as load_tracking
from pm_agent.ui import chip, strip
from pm_agent.workbench import (
    PLAN_COLUMNS,
    RUNS_CSV,
    TEAM_COLUMNS,
    TEAM_FILE,
    InputError,
    append_run,
    gantt,
    load_run,
    load_team,
    plan_rows,
    round_summary,
    rows_to_plan,
    rows_to_team,
    save_team,
    saved_runs,
    team_rows,
    to_csv,
    to_markdown,
)

state = st.session_state
STEPS = ["1 · Team", "2 · Projekt", "3 · Planung", "4 · Ergebnis", "5 · Anpassen", "6 · Export"]


def init() -> None:
    if "team_df" in state:
        return
    try:
        team, state.team_file_error = load_team(), None
    except InputError as err:
        team, state.team_file_error = [], str(err)
    state.team_df = pd.DataFrame(team_rows(team), columns=TEAM_COLUMNS)
    # Widget defaults live in the session state, so open_run can overwrite them.
    state.update(idea="", start=date.today(), deadline=None, consent=False)
    state.update(
        plan=None,
        original=None,
        rounds=[],
        source=None,
        agent_seconds=None,
        shown_at=None,
        edited=False,
        plan_df=None,
        editor_version=0,
        team_version=0,
    )


def restore_editors() -> None:
    """After a visit to another page the table editors start again from their last content."""
    if state.get("team_current") is not None:
        # Added rows carry their own index labels; a fresh index keeps the index column hidden.
        state.team_df = state.team_current.reset_index(drop=True)
        state.team_version += 1
    if state.get("plan_current") is not None and state.plan is not None:
        state.plan_df = state.plan_current.reset_index(drop=True)
        state.editor_version += 1


def show_plan(plan, rounds, source, agent_seconds) -> None:
    """A new plan from the agent or from a log becomes the current plan."""
    state.update(
        plan=plan,
        original=plan,
        rounds=rounds,
        source=source,
        agent_seconds=agent_seconds,
        shown_at=time.monotonic(),
        edited=False,
        plan_df=pd.DataFrame(plan_rows(plan), columns=PLAN_COLUMNS),
        plan_current=None,
        risks_text="\n".join(plan.risks),
        editor_version=state.editor_version + 1,
    )


def open_run(path) -> None:
    """Callback: runs before the widgets, so it may fill their keys."""
    project, team, plan, record = load_run(path)
    state.team_df = pd.DataFrame(team_rows(team), columns=TEAM_COLUMNS)
    state.team_current = None
    state.team_version += 1
    state.update(idea=project.idea, start=project.start_date, deadline=project.deadline)
    show_plan(plan, record["rounds"], f"Protokoll {path.name}", record.get("seconds"))
    state.step = STEPS[3]  # straight to the result


def go(step: str) -> None:
    """Callback: open a step. The tabs keep their selection under the key "step"."""
    state.step = step


def next_step(label: str, step: str, ready: bool, key: str) -> None:
    """The button that leads on. It is the primary one once this step is complete."""
    st.button(
        label,
        key=key,
        icon=":material/arrow_forward:",
        type="primary" if ready else "secondary",
        on_click=go,
        args=(step,),
    )


init()
if state.get("page_changed"):  # set by app.py
    restore_editors()
st.header("Planung")
st.caption(
    "Claude schlägt einen Plan vor, Python prüft ihn deterministisch, die Projektleitung "
    "entscheidet."
)
status_strip = st.empty()  # filled at the end, when team, project and plan are known
# on_change="rerun" makes the selection a value in the session state, so buttons can open a
# step. Every step is still rendered on every run (see the module docstring).
tabs = st.tabs(STEPS, key="step", on_change="rerun")

# 1 · Team ---------------------------------------------------------------------------------
with tabs[0]:
    st.subheader("Team")
    st.caption(
        "Wer arbeitet mit? Skills mit Stufe 1–5 und die Stunden pro Woche bestimmen, wem "
        "welche Aufgabe zugewiesen wird."
    )
    if state.team_file_error:
        st.error(f"Gespeichertes Team konnte nicht geladen werden: {state.team_file_error}")
    edited_team = st.data_editor(
        state.team_df,
        key=f"team_editor_{state.team_version}",
        num_rows="dynamic",
        width="stretch",
        column_config={
            "Name": st.column_config.TextColumn(required=True),
            "Skills": st.column_config.TextColumn(
                help="Skill mit Stufe 1–5, z. B. Python 4, SQL 3"
            ),
            "Stunden/Woche": st.column_config.NumberColumn(min_value=1, max_value=168),
            "Notiz": st.column_config.TextColumn(help="z. B. Urlaub, Prüfungsphase"),
        },
    )
    state.team_current = edited_team
    try:
        team = rows_to_team(edited_team.to_dict("records"))
    except InputError as err:
        team = None
        st.error(f"Bitte korrigieren:\n\n{err}")
    if team == []:
        st.info(
            "Noch kein Teammitglied. Trage pro Zeile eine Person mit Skills und Wochenstunden ein."
        )
    if team and st.button("Team lokal speichern", icon=":material/save:"):
        save_team(team)
        st.success(
            f"Gespeichert in {TEAM_FILE.parent.name}/{TEAM_FILE.name} (lokal, nicht im Repository)."
        )
    consent = st.checkbox(
        "Alle eingetragenen Personen haben zugestimmt, dass ihre Angaben (Name, Skills, Stunden, "
        "Notiz) zur Planung an die Anthropic API gesendet werden.",
        key="consent",
        persist_state="session",
    )
    next_step("Weiter zum Projekt", STEPS[1], bool(team) and consent, "to_project")

# 2 · Projekt ------------------------------------------------------------------------------
with tabs[1]:
    st.subheader("Projekt")
    st.caption("Was soll bis wann entstehen? Aus der Idee leitet Claude die Aufgaben ab.")
    idea = st.text_area(
        "Projektidee",
        key="idea",
        persist_state="session",
        placeholder="Was soll gebaut werden, für wen, mit welchen Anforderungen?",
    )
    left, right = st.columns(2)
    start = left.date_input("Start", key="start", format="DD.MM.YYYY", persist_state="session")
    deadline = right.date_input(
        "Deadline", key="deadline", format="DD.MM.YYYY", persist_state="session"
    )
    project = None
    if not idea.strip() or deadline is None:
        st.info("Beschreibe die Projektidee und wähle eine Deadline.")
    else:
        try:
            project = Project(idea=idea, start_date=start, deadline=deadline)
        except ValidationError as err:
            st.error("; ".join(e["msg"].removeprefix("Value error, ") for e in err.errors()))
    next_step("Weiter zur Planung", STEPS[2], project is not None, "to_planning")

# 3 · Planung ------------------------------------------------------------------------------
with tabs[2]:
    st.subheader("Planung mit Claude")
    new_plan, logged_run = st.columns([3, 2], gap="medium")
    with new_plan.container(border=True, key="panel-claude", height="stretch"):
        st.markdown("#### :material/smart_toy: Neuen Plan erstellen")
        st.caption(
            "Claude entwirft, Python prüft, Claude bessert nach, bis der Plan ohne Fehler ist."
        )
        missing = [
            text
            for ok, text in [
                (bool(team), "ein gültiges Team (Schritt 1)"),
                (consent, "die Zustimmung des Teams (Schritt 1)"),
                (project is not None, "Projektidee und Deadline (Schritt 2)"),
            ]
            if not ok
        ]
        if missing:
            st.info("Für die Planung fehlt noch: " + ", ".join(missing) + ".")
        if st.button(
            "Plan mit Claude erstellen",
            type="primary",
            icon=":material/play_arrow:",
            disabled=bool(missing),
        ):
            rounds = []
            with st.status("Claude plant …", expanded=True) as status:

                def on_round(record):
                    rounds.append(record)
                    headline, messages = round_summary(len(rounds), record)
                    st.write(headline)
                    for message in messages:
                        st.caption(message)

                started = time.monotonic()
                failure = None
                try:
                    plan = run_planning(project, team, on_round=on_round)
                except PlanningError as err:
                    failure = str(err)
                except APIError as err:
                    failure = f"Die Claude API meldet einen Fehler: {err}"
                else:
                    show_plan(plan, rounds, "Agent", round(time.monotonic() - started, 1))
                # The message goes below the box: a collapsed status would hide it.
                label = f"Kein Plan nach {len(rounds)} Runden" if failure else "Plan angenommen"
                status.update(label=label, state="error" if failure else "complete", expanded=True)
            if failure:
                st.error(failure)
            else:
                st.success(
                    f"Plan angenommen nach {len(rounds)} Runden. Er steht in Schritt 4 und 5."
                )

    with logged_run.container(border=True, key="panel-run", height="stretch"):
        st.markdown("#### :material/history: Protokollierten Lauf öffnen")
        st.caption("Zeigt einen früheren Plan ohne neuen Aufruf von Claude.")
        try:
            runs = saved_runs()
        except ValueError as err:  # a damaged log file
            runs = []
            st.error(f"Protokolle in logs/ konnten nicht gelesen werden: {err}")
        if not runs:
            st.caption("Noch keine protokollierten Läufe mit Plan.")
        else:
            chosen = st.selectbox("Lauf", runs, format_func=lambda p: p.name)
            st.button(
                "Lauf öffnen", icon=":material/folder_open:", on_click=open_run, args=(chosen,)
            )

    if state.rounds:
        with st.expander(f"Verlauf ({state.source}, {len(state.rounds)} Runden)", expanded=False):
            for number, record in enumerate(state.rounds, start=1):
                headline, messages = round_summary(number, record)
                st.write(headline)
                for message in messages:
                    st.caption(message)
    if state.plan is not None:
        next_step("Ergebnis ansehen", STEPS[3], False, "to_result")

# The current check, shared by steps 4–6. No LLM: it runs on every rerun.
result = check_plan(state.plan, team, project) if state.plan and team and project else None

# 4 · Ergebnis -----------------------------------------------------------------------------
with tabs[3]:
    st.subheader("Ergebnis")
    if state.plan is None:
        st.info("Noch kein Plan. Erstelle ihn in Schritt 3 oder öffne einen protokollierten Lauf.")
    elif result is None:
        st.warning("Team oder Projekt sind unvollständig, der Plan kann nicht geprüft werden.")
    else:
        st.caption(
            f"Quelle: {state.source}"
            + (" · von der Projektleitung angepasst" if state.edited else "")
        )
        a, b, c = st.columns(3)
        a.metric("Planende", result.end_date.strftime("%d.%m.%Y") if result.end_date else "–")
        b.metric("Fehler", len(result.errors))
        c.metric("Warnungen", len(result.warnings))
        for error in result.errors:
            st.error(error)
        for warning in result.warnings:
            st.warning(warning)
        if not result.errors and not result.warnings:
            st.success("Die Prüfung meldet keine Fehler und keine Warnungen.")

        with st.container(border=True, key="panel-schedule"):
            st.markdown("#### :material/view_timeline: Terminplan")
            if result.schedule:
                bars, deadline_line = gantt(state.plan, result, project.deadline)
                chart = (
                    alt.Chart(pd.DataFrame(bars))
                    .mark_bar(cornerRadius=3)
                    .encode(
                        x=alt.X("Start:T", title=None, axis=alt.Axis(format="%d.%m.")),
                        x2="Ende:T",
                        y=alt.Y("Aufgabe:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
                        color="Person:N",
                        tooltip=["Aufgabe", "Person", "Zeitraum"],
                    )
                )
                deadline_data = alt.Chart(pd.DataFrame({"Deadline": [deadline_line]}))
                deadline_rule = deadline_data.mark_rule(strokeDash=[4, 4]).encode(x="Deadline:T")
                deadline_label = deadline_data.mark_text(
                    text="Deadline", align="right", baseline="top", dx=-6, fontSize=11
                ).encode(x="Deadline:T", y=alt.value(0))
                # White like the panel around it; the theme would paint the page colour.
                layered = (chart + deadline_rule + deadline_label).properties(background="#ffffff")
                st.altair_chart(layered, width="stretch")
                arrow = '<span class="chip-arrow">→</span>'
                path = arrow.join(
                    f'<span class="chip on">{escape(task_id)}</span>'
                    for task_id in result.critical_path
                )
                st.html(f'<p class="path"><strong>Kritischer Pfad</strong>{path}</p>')
            else:
                st.info("Ohne fehlerfreien Plan gibt es keinen Terminplan.")

        with st.container(border=True, key="panel-load"):
            st.markdown("#### :material/groups: Auslastung bis zur Deadline")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Person": item.member,
                            "Zugewiesen (h)": round(item.assigned_hours, 1),
                            "Verfügbar (h)": round(item.capacity_hours, 1),
                            "Auslastung": item.utilization,
                        }
                        for item in result.load
                    ]
                ),
                hide_index=True,
                column_config={
                    # The bar is full at 100 %. Above that the number says by how much.
                    "Auslastung": st.column_config.ProgressColumn(
                        format="percent", min_value=0, max_value=1
                    )
                },
            )
        with st.container(border=True, key="panel-risks"):
            st.markdown("#### :material/warning: Risiken")
            if state.plan.risks:
                st.markdown("\n".join(f"- {r}" for r in state.plan.risks))
            else:
                st.caption("Der Plan nennt keine Risiken.")

        with st.container(border=True, key="panel-reasons"):
            st.markdown("#### :material/assignment_ind: Zuweisungen und Begründungen")
            st.dataframe(
                pd.DataFrame(plan_rows(state.plan))[["ID", "Aufgabe", "Person", "Begründung"]],
                hide_index=True,
            )

        with st.container(horizontal=True):
            st.button("Plan anpassen", icon=":material/edit:", on_click=go, args=(STEPS[4],))
            next_step("Weiter zum Export", STEPS[5], not result.errors, "to_export")

# 5 · Anpassen -----------------------------------------------------------------------------
with tabs[4]:
    st.subheader("Anpassen und erneut prüfen")
    if state.plan is None:
        st.info("Noch kein Plan zum Anpassen.")
    else:
        st.caption(
            "Ändere Personen, Stunden oder Abhängigkeiten. „Erneut prüfen“ rechnet nur "
            "deterministisch nach, Claude wird nicht aufgerufen."
        )
        edited_plan = st.data_editor(
            state.plan_df,
            key=f"plan_editor_{state.editor_version}",
            num_rows="dynamic",
            width="stretch",
            column_config={
                "Stunden": st.column_config.NumberColumn(min_value=0.5),
                "Abhängig von": st.column_config.TextColumn(help="IDs, getrennt durch Komma"),
                "Skills": st.column_config.TextColumn(help="getrennt durch Komma"),
            },
        )
        state.plan_current = edited_plan
        risks = st.text_area("Risiken (eins pro Zeile)", key="risks_text", persist_state="session")
        if st.button("Erneut prüfen", type="primary", icon=":material/fact_check:"):
            try:
                new = rows_to_plan(
                    edited_plan.to_dict("records"), state.original, risks.splitlines()
                )
            except InputError as err:
                st.error(f"Bitte korrigieren:\n\n{err}")
            else:
                state.update(plan=new, edited=new != state.original)
                st.rerun()
        next_step("Ergebnis ansehen", STEPS[3], False, "back_to_result")

# 6 · Export -------------------------------------------------------------------------------
with tabs[5]:
    st.subheader("Export")
    if state.plan is None or result is None:
        st.info("Noch kein geprüfter Plan zum Exportieren.")
    else:
        if result.errors:
            st.warning("Der Plan hat noch Fehler (siehe Schritt 4). Export ist trotzdem möglich.")

        def record_export(fmt: str) -> None:
            append_run(
                {
                    "exportiert": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "quelle": state.source,
                    "agent_sekunden": state.agent_seconds,
                    "runden": len(state.rounds),
                    "pruefung_sekunden": round(time.monotonic() - state.shown_at, 1),
                    "angepasst": state.edited,
                    "tasks": len(state.plan.tasks),
                    "fehler": len(result.errors),
                    "warnungen": len(result.warnings),
                    "format": fmt,
                }
            )

        stamp = date.today().strftime("%Y%m%d")
        download, take_over = st.columns(2, gap="medium")
        with download.container(border=True, key="panel-download", height="stretch"):
            st.markdown("#### :material/download: Herunterladen")
            with st.container(horizontal=True):
                st.download_button(
                    "Als Markdown herunterladen",
                    to_markdown(project, state.plan, result),
                    file_name=f"projektplan-{stamp}.md",
                    mime="text/markdown",
                    on_click=record_export,
                    args=("markdown",),
                )
                st.download_button(
                    "Als CSV herunterladen",
                    to_csv(state.plan, result),
                    file_name=f"projektplan-{stamp}.csv",
                    mime="text/csv",
                    on_click=record_export,
                    args=("csv",),
                )
            st.caption(
                f"Jeder Export wird mit Dauer und Änderungen in "
                f"{RUNS_CSV.parent.name}/{RUNS_CSV.name} vermerkt "
                "(lokal, für den Vorher-nachher-Vergleich)."
            )

        with take_over.container(border=True, key="panel-adopt", height="stretch"):
            st.markdown("#### :material/flag: Als Projekt übernehmen")
            st.caption("Der Plan wird zur Grundlage für die Seiten Durchführung und Kontrolle.")
            try:
                adopted = load_tracking()
            except InputError as err:
                adopted = None
                st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {err}")
            overwrite = True
            if adopted is not None and has_progress(adopted):
                overwrite = st.checkbox(
                    f"Das am {adopted.adopted:%d.%m.%Y} übernommene Projekt hat schon erfassten "
                    "Fortschritt. Überschreiben und den Fortschritt verwerfen.",
                    key="adopt_overwrite",
                )
            elif adopted is not None:
                st.caption(f"Ersetzt das am {adopted.adopted:%d.%m.%Y} übernommene Projekt.")
            if result.errors:
                st.caption("Erst möglich, wenn der Plan keine Fehler mehr hat (siehe Schritt 4).")
            if st.button(
                "Plan als Projekt übernehmen",
                type="primary",
                icon=":material/flag:",
                disabled=bool(result.errors) or not overwrite,
            ):
                adopt(project, team, state.plan)
                st.success("Übernommen. Weiter auf den Seiten Durchführung und Kontrolle.")

        with st.expander("Vorschau Markdown"):
            st.markdown(to_markdown(project, state.plan, result))

# Where the planning stands, above the steps.
if state.plan is None:
    plan_chip = chip("Plan offen")
elif result is None:
    plan_chip = chip("Plan nicht prüfbar", "warn")
elif result.errors:
    plan_chip = chip(f"Plan: {len(result.errors)} Fehler", "warn")
else:
    count = len(result.warnings)
    notes = f", {count} Warnung{'' if count == 1 else 'en'}" if count else ""
    plan_chip = chip(f"Plan geprüft{notes}", "on")
people = f"Team: {len(team)} Person{'' if len(team) == 1 else 'en'}" if team else "Team fehlt"
status_strip.html(
    strip(
        chip(people, "on" if team else ""),
        chip("Zustimmung", "on" if consent else ""),
        chip("Projekt", "on" if project is not None else ""),
        plan_chip,
    )
)
