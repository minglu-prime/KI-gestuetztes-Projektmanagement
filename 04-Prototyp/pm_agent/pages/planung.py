"""Page "Planung": team, project, planning, result, edit, export. Started through app.py.

All six steps are tabs on this page, so every widget is rendered on every run. Streamlit drops
the state of widgets that are not rendered. For the other pages of the site the simple widgets
use persist_state="session"; the two table editors cannot, so their content is kept in the
session state and restored when the user comes back (see restore_editors).
"""

import math
import time
from datetime import date, datetime
from html import escape

import altair as alt
import pandas as pd
import streamlit as st
from anthropic import APIError
from pydantic import ValidationError

from pm_agent.agent import PlanningError, run_planning, run_replanning
from pm_agent.models import Project
from pm_agent.planning import check_plan
from pm_agent.tracking import adopt, has_progress, rest_project
from pm_agent.tracking import load as load_tracking
from pm_agent.ui import BUSY_HINT, chip, round_printer, strip
from pm_agent.workbench import (
    PLAN_COLUMNS,
    RUNS_CSV,
    TEAM_COLUMNS,
    TEAM_FILE,
    InputError,
    append_run,
    check_changes,
    explain_task,
    gantt,
    load_run,
    load_team,
    pair_tasks,
    plan_changes,
    plan_rows,
    rows_to_plan,
    rows_to_team,
    save_team,
    saved_runs,
    suggested_wishes,
    table_plan,
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
        # The conversation that changes the plan (step 5) and its open proposal.
        chat=[],
        proposal=None,
        rounds_start=None,
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


def show_plan(plan, rounds, source, agent_seconds, rounds_start=None) -> None:
    """A new plan from the agent or from a log becomes the current plan. `rounds_start` is
    the plan the rounds started from, if they changed a plan instead of drafting one."""
    state.update(
        plan=plan,
        original=plan,
        rounds=rounds,
        rounds_start=rounds_start,
        source=source,
        agent_seconds=agent_seconds,
        round_count=len(rounds),
        shown_at=time.monotonic(),
        edited=False,
        hand_edited=False,
        plan_df=pd.DataFrame(plan_rows(plan), columns=PLAN_COLUMNS),
        plan_current=None,
        risks_text="\n".join(plan.risks),
        editor_version=state.editor_version + 1,
    )


def forget_conversation() -> None:
    """A new plan is on the table: the conversation, an open proposal and a wish that was
    not answered yet were about another one."""
    state.update(chat=[], proposal=None)
    state.pop("asked", None)


def table_matches_plan() -> bool:
    """Whether the table of step 5, as the editor last returned it, says what the current
    plan says. False while hand edits wait for "Erneut prüfen". Compared in the form the
    table gives a plan back (table_plan): an untouched table is never an edit."""
    if state.get("plan_current") is None:  # not shown since the plan changed
        return True
    try:
        typed = rows_to_plan(
            state.plan_current.to_dict("records"),
            state.original,
            state.get("risks_text", "").splitlines(),
        )
    except InputError:  # unreadable as it stands: certainly not the current plan
        return False
    return typed == table_plan(state.plan)


def reset_table() -> None:
    """Callback: the table of step 5 shows the current plan again, hand edits are dropped."""
    state.update(
        plan_df=pd.DataFrame(plan_rows(state.plan), columns=PLAN_COLUMNS),
        plan_current=None,
        risks_text="\n".join(state.plan.risks),
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
    forget_conversation()
    state.step = STEPS[3]  # straight to the result


def load_rest() -> None:
    """The unfinished part of the adopted project becomes the current plan, starting today,
    so that it can be changed in the conversation and adopted again. Runs before the
    widgets, so it may fill their keys. Raises InputError if there is nothing to load."""
    adopted = load_tracking()
    if adopted is None:
        raise InputError("Es ist kein Projekt übernommen")
    project, plan = rest_project(adopted, date.today())
    state.team_df = pd.DataFrame(team_rows(adopted.team), columns=TEAM_COLUMNS)
    state.team_current = None
    state.team_version += 1
    state.update(idea=project.idea, start=project.start_date, deadline=project.deadline)
    show_plan(plan, [], "Rest des übernommenen Projekts", None)
    forget_conversation()
    state.step = STEPS[4]  # straight to the step with the conversation


def ask(wish: str | None = None) -> None:
    """Callback of the chat input and of the suggested wishes: keep the wish for the run that
    follows. Without an argument it is what was typed."""
    state.asked = wish or state.wish


def decide(accept: bool) -> None:
    """Callback: the project lead takes or drops the change Claude proposed."""
    proposal = state.proposal
    if proposal is None:
        # The second click of a double click: Streamlit calls the callback again although
        # the first click has already decided. Nothing is left to decide.
        return
    state.proposal = None
    state.chat.append(
        {"wish": proposal["wish"], "changes": proposal["changes"], "accepted": accept}
    )
    if accept:
        # What the export record says about the plan as a whole goes on: the agent's time
        # and rounds add up, a hand edit stays a hand edit, the review began when it began.
        seconds = (state.agent_seconds or 0) + proposal["seconds"]
        rounds = state.get("round_count", len(state.rounds)) + len(proposal["rounds"])
        hand_edited, shown_at = state.get("hand_edited", state.edited), state.shown_at
        show_plan(
            proposal["plan"],
            proposal["rounds"],
            "Agent, auf Wunsch geändert",
            round(seconds, 1),
            rounds_start=proposal["basis"],
        )
        state.update(round_count=rounds, hand_edited=hand_edited, shown_at=shown_at)


def whole_percent(share: float | None) -> float | None:
    """A share for a table column, rounded up to whole per cent like the overload warning:
    100.2 % must not read as 100 %. None (away until the deadline) stays empty."""
    return None if share is None else math.ceil(round(share * 100, 9)) / 100


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
rest_error = None
if state.pop("rest_requested", False):  # set by the Kontrolle page
    try:
        load_rest()
    except InputError as err:
        rest_error = str(err)
st.header("Planung")
st.caption(
    "Claude schlägt einen Plan vor, Python prüft ihn deterministisch, die Projektleitung "
    "entscheidet."
)
if rest_error:
    st.error(f"Der Rest des Projekts konnte nicht geladen werden: {rest_error}")
status_strip = st.empty()  # filled at the end, when team, project and plan are known
# on_change="rerun" makes the selection a value in the session state, so buttons can open a
# step. Every step is still rendered on every run (see the module docstring).
tabs = st.tabs(STEPS, key="step", on_change="rerun")

# 1 · Team ---------------------------------------------------------------------------------
with tabs[0]:
    st.subheader("Team")
    st.caption(
        "Wer arbeitet mit? Skills mit Stufe 1–5 und die Stunden pro Woche bestimmen, wem "
        "welche Aufgabe zugewiesen wird. An Tagen unter „Abwesend“ wird für die Person keine "
        "Arbeit eingeplant."
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
            "Abwesend": st.column_config.TextColumn(
                help="Tage ohne Arbeit, z. B. 01.12.2026–05.12.2026, 23.12.2026. Feiertage "
                "kennt der Kalender nicht: bei allen Personen eintragen."
            ),
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
                st.caption(BUSY_HINT)
                show_round = round_printer()

                def on_round(record):
                    rounds.append(record)
                    show_round(record)

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
                    forget_conversation()
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
        # Open by default: how the plan came about is part of the result, not a detail.
        title = f"So ist der Plan entstanden ({state.source}, {len(state.rounds)} Runden)"
        with st.expander(title, expanded=True), st.container(key="rounds-log"):
            show_logged_round = round_printer(state.rounds_start)
            for record in state.rounds:
                show_logged_round(record)
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
                        # A dark outline for the tasks without slack.
                        stroke=alt.condition(
                            "datum.Kritisch", alt.value("#18352d"), alt.value("transparent")
                        ),
                        strokeWidth=alt.value(2),
                        tooltip=[
                            "Aufgabe",
                            "Person",
                            "Zeitraum",
                            alt.Tooltip("Puffer:Q", title="Puffer (Arbeitstage)"),
                        ],
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
                st.caption(
                    "Dunkel umrandet: Aufgaben ohne Puffer. Wie viele Arbeitstage Puffer eine "
                    "Aufgabe hat, steht im Tooltip und in der Tabelle der Zuweisungen. Der "
                    "kritische Pfad ist die Kette, die das Ende bestimmt."
                )
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
                            "Auslastung": whole_percent(item.utilization),
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
            reasons = pd.DataFrame(plan_rows(state.plan))[["ID", "Aufgabe", "Person", "Begründung"]]
            if result.slack:
                reasons.insert(3, "Puffer (Tage)", reasons["ID"].map(result.slack))
            st.dataframe(reasons, hide_index=True)

        if result.schedule:
            with st.container(border=True, key="panel-task"):
                st.markdown("#### :material/search: Aufgabe im Detail")
                st.caption(
                    "Warum diese Person, was hängt an der Aufgabe, und wer könnte sie sonst "
                    "übernehmen? Die Begründung stammt von Claude, alles andere rechnet Python."
                )
                names = {task.id: f"{task.id} · {task.title}" for task in state.plan.tasks}
                chosen = st.selectbox("Aufgabe", list(names), format_func=names.get)
                view = explain_task(state.plan, team, result, chosen)
                room = (
                    chip("Kein Puffer: jede Verzögerung verschiebt das Ende", "warn")
                    if view["critical"]
                    else chip(
                        f"{view['slack']} Arbeitstag{'' if view['slack'] == 1 else 'e'} Puffer",
                        "on" if view["slack"] else "",
                    )
                )
                st.html(
                    strip(
                        chip(view["member"], "plain"),
                        chip(f"{view['hours']:g} h", "plain"),
                        chip(f"{view['start']:%d.%m.} – {view['end']:%d.%m.%Y}", "plain"),
                        room,
                    )
                )
                if view["description"]:
                    st.markdown(view["description"])
                why, around = st.columns(2, gap="medium")
                with why:
                    st.markdown(f"**Warum {view['member']}?**")
                    st.markdown(view["reason"])
                    for skill, level in view["skills"]:
                        have = (
                            f"Stufe {level}" if level else f"bei {view['member']} nicht angegeben"
                        )
                        st.markdown(f"- {skill}: {have}")
                with around:
                    st.markdown("**Braucht vorher**")
                    st.markdown(
                        "\n".join(f"- {tid} · {title}" for tid, title in view["depends_on"])
                        or "Nichts: Die Aufgabe kann sofort beginnen."
                    )
                    st.markdown("**Darauf warten**")
                    st.markdown(
                        "\n".join(f"- {tid} · {title}" for tid, title in view["needed_by"])
                        or "Keine andere Aufgabe."
                    )
                st.markdown("**Wer könnte es sonst?**")
                if view["alternatives"]:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Person": other["member"],
                                    "Passende Skills": ", ".join(
                                        f"{skill} {level}"
                                        for skill, level in other["skills"].items()
                                    ),
                                    "Auslastung": whole_percent(other["utilization"]),
                                }
                                for other in view["alternatives"]
                            ]
                        ),
                        hide_index=True,
                        column_config={
                            "Auslastung": st.column_config.ProgressColumn(
                                format="percent", min_value=0, max_value=1
                            )
                        },
                    )
                    st.caption(
                        "Auslastung bis zur Deadline im aktuellen Plan. Eine Umverteilung "
                        "lässt sich im Schritt Anpassen durchspielen."
                    )
                else:
                    st.caption("Niemand sonst im Team hat einen der verlangten Skills angegeben.")

        with st.container(horizontal=True):
            st.button("Plan anpassen", icon=":material/edit:", on_click=go, args=(STEPS[4],))
            next_step("Weiter zum Export", STEPS[5], not result.errors, "to_export")

# 5 · Anpassen -----------------------------------------------------------------------------
with tabs[4]:
    st.subheader("Anpassen und erneut prüfen")
    if state.plan is None:
        st.info("Noch kein Plan zum Anpassen.")
    else:
        # The conversation stands above the table but runs after it: it has to know
        # what the table says in this run, not in the one before.
        chat_panel = st.container(border=True, key="panel-chat")
        st.markdown("#### :material/edit: Von Hand ändern")
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
                changed = new != table_plan(state.original)
                state.update(
                    plan=new,
                    edited=changed,
                    hand_edited=state.get("hand_edited", False) or changed,
                )
                st.rerun()
        next_step("Ergebnis ansehen", STEPS[3], False, "back_to_result")

        with chat_panel:
            st.markdown("#### :material/forum: Mit Claude ändern")
            st.caption(
                "Sag, was sich ändern soll, oder spiel eine Annahme durch: „Clara übernimmt die "
                "Tests“, „Was, wenn das Backend doppelt so lange dauert?“. Claude ändert den "
                "Plan, Python prüft ihn, du siehst die Unterschiede und entscheidest."
            )
            for turn in state.chat:
                with st.chat_message("user"):
                    st.text(turn["wish"])
                with st.chat_message("assistant"):
                    st.markdown("**Übernommen**" if turn["accepted"] else "**Verworfen**")
                    st.markdown("\n".join(f"- {c}" for c in turn["changes"]) or "Keine Änderung.")

            proposal = state.proposal
            if proposal is not None and proposal["basis"] != state.plan:
                state.proposal = proposal = None
                st.info(
                    "Der Plan wurde seit dem Vorschlag von Hand geändert. Der Vorschlag passt "
                    "nicht mehr dazu und ist verworfen."
                )
            blocked = [
                text
                for ok, text in [
                    (consent, "die Zustimmung des Teams (Schritt 1)"),
                    (result is not None, "ein gültiges Team und Projekt (Schritt 1 und 2)"),
                ]
                if not ok
            ]
            # Claude gets the current plan, and taking its proposal replaces the table. Hand
            # edits that were not checked would be ignored first and overwritten then: no
            # wish and no "Übernehmen" while they wait.
            unchecked = not table_matches_plan()
            wish = state.pop("asked", None)  # set by the chat input at the end of the panel
            # A second wish must not replace a proposal that is still open.
            if wish and proposal is None and not blocked and not unchecked:
                with st.chat_message("user"):
                    st.text(wish)
                change_rounds = []
                with st.status("Claude ändert den Plan …", expanded=True) as status:
                    st.caption(BUSY_HINT)
                    with st.container(key="rounds-change"):
                        show_change_round = round_printer(state.plan)

                        def on_change_round(record):
                            change_rounds.append(record)
                            show_change_round(record)

                        started = time.monotonic()
                        failure = None
                        try:
                            changed_plan = run_replanning(
                                project, team, state.plan, wish, on_round=on_change_round
                            )
                        except PlanningError as err:
                            failure = str(err)
                        except APIError as err:
                            failure = f"Die Claude API meldet einen Fehler: {err}"
                        else:
                            state.proposal = proposal = {
                                "wish": wish,
                                "basis": state.plan,
                                "plan": changed_plan,
                                "rounds": change_rounds,
                                "seconds": round(time.monotonic() - started, 1),
                            }
                    label = (
                        f"Kein Vorschlag nach {len(change_rounds)} Runden"
                        if failure
                        else f"Vorschlag nach {len(change_rounds)} Runden"
                    )
                    status.update(
                        label=label, state="error" if failure else "complete", expanded=True
                    )
                # The message goes below the box: a collapsed status would hide it.
                if failure:
                    st.error(failure)
                else:
                    # Again from the top: the input is locked while the proposal is open.
                    st.rerun()

            if proposal is not None:
                proposed = check_plan(proposal["plan"], team, project) if result else None
                with st.chat_message("assistant"):
                    st.markdown("**Vorschlag von Claude, von Python geprüft**")
                    st.text(proposal["wish"])
                    proposal["changes"] = plan_changes(state.plan, proposal["plan"])
                    if proposed is not None:
                        proposal["changes"] += check_changes(
                            result, proposed, pair_tasks(state.plan, proposal["plan"])
                        )
                    if proposal["changes"]:
                        st.markdown("\n".join(f"- {c}" for c in proposal["changes"]))
                    else:
                        st.info("Claude schlägt keine Änderung am Plan vor.")
                    with st.container(horizontal=True):
                        st.button(
                            "Übernehmen",
                            type="primary",
                            icon=":material/check:",
                            on_click=decide,
                            args=(True,),
                            disabled=proposed is None or not proposal["changes"] or unchecked,
                        )
                        st.button(
                            "Verwerfen", icon=":material/close:", on_click=decide, args=(False,)
                        )
                    if proposal["rounds"]:
                        title = f"So ist Claude vorgegangen ({len(proposal['rounds'])} Runden)"
                        # Open: how Claude got there belongs to the proposal.
                        with (
                            st.expander(title, expanded=True),
                            st.container(key="rounds-proposal"),
                        ):
                            show_proposal_round = round_printer(proposal["basis"])
                            for record in proposal["rounds"]:
                                show_proposal_round(record)

            # The input comes last, below the conversation. Its callback hands the wish to
            # the run that follows, which answers it above.
            if blocked:
                st.caption("Für eine Änderung mit Claude fehlt noch: " + ", ".join(blocked) + ".")
            elif unchecked:
                st.warning(
                    "In der Tabelle unten stehen Änderungen, die noch nicht geprüft sind. Claude "
                    "bekäme den Plan ohne sie, und sein Vorschlag würde sie überschreiben. "
                    "Übernimm sie mit „Erneut prüfen“ oder setz die Tabelle zurück."
                    + (" Dein Wunsch wurde nicht gestellt." if wish else "")
                )
                st.button("Tabelle zurücksetzen", icon=":material/undo:", on_click=reset_table)
            elif proposal is not None:
                st.caption("Entscheide erst über den offenen Vorschlag.")
            else:
                suggestions = suggested_wishes(state.plan, team, result, project)
                if suggestions:
                    st.caption("Naheliegend nach der Prüfung des Plans, mit einem Klick gefragt:")
                    with st.container(horizontal=True, key="suggestions"):
                        for number, suggestion in enumerate(suggestions):
                            st.button(
                                suggestion,
                                key=f"suggestion_{number}",
                                on_click=ask,
                                args=(suggestion,),
                            )
            st.chat_input(
                "Was soll sich ändern?",
                key="wish",
                on_submit=ask,
                disabled=bool(blocked) or proposal is not None or unchecked,
            )

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
                    "runden": state.get("round_count", len(state.rounds)),
                    "pruefung_sekunden": round(time.monotonic() - state.shown_at, 1),
                    "angepasst": state.get("hand_edited", state.edited),
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
