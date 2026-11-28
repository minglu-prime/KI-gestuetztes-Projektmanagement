"""Page "Planung": team, project, planning, result, edit, export. Started through app.py.

All six steps are tabs on this page, so every widget is rendered on every run. Streamlit drops
the state of widgets that are not rendered. For the other pages of the site the simple widgets
use persist_state="session"; the plan table editor cannot, so its content is kept in the
session state and restored when the user comes back (see restore_editors).
"""

import math
import time
from datetime import date, datetime
from html import escape

import altair as alt
import pandas as pd
import streamlit as st
from openai import APIError
from pydantic import ValidationError

from pm_agent import lifecycle
from pm_agent.agent import (
    PlanningError,
    collect_log_errors,
    describe_api_error,
    run_planning,
    run_replanning,
)
from pm_agent.models import Project
from pm_agent.planning import check_plan
from pm_agent.tools import with_absences
from pm_agent.tracking import (
    PROJECT_WRITE_LOCK,
    adopt,
    covered_requirements,
    current_team,
    finished_again,
    has_progress,
    require_current,
    rest_project,
)
from pm_agent.tracking import load as load_tracking
from pm_agent.tracking import next_step as project_step
from pm_agent.ui import (
    BUSY_HINT,
    LEGEND,
    PAGES,
    TASK_AXIS,
    Track,
    as_text,
    check_verdict,
    chip,
    comparison_card,
    heading,
    messages,
    notify,
    on_panel,
    phase_chip,
    roles,
    round_printer,
    rounds_text,
    said_in_full,
    strip,
    style_priority,
    verdict,
)
from pm_agent.ui import (
    consent as ask_consent,
)
from pm_agent.workbench import (
    PLAN_COLUMNS,
    RUNS_CSV,
    TEAM_COLUMNS,
    InputError,
    append_run,
    check_changes,
    demo_rows,
    explain_task,
    free_days,
    free_days_text,
    gantt,
    load_run,
    load_team,
    pair_tasks,
    plan_changes,
    plan_rows,
    rows_to_plan,
    rows_to_team,
    saved_runs,
    suggested_wishes,
    table_plan,
    team_rows,
    to_csv,
    to_markdown,
    trace_rows,
)

state = st.session_state
STEPS = ["1 · Team", "2 · Projekt", "3 · Planung", "4 · Ergebnis", "5 · Anpassen", "6 · Übernehmen"]
# What becomes of the recorded progress when a plan is adopted again.
KEEP = "Als frühere Arbeit behalten"
DROP = "Verwerfen"


def set_team(members: list, override: str | None = None) -> None:
    """Update the displayed team table. `override` names the source when it differs from
    team.json (a logged run, the rest of the adopted project, or an accepted absence)."""
    frame = pd.DataFrame(team_rows(members), columns=TEAM_COLUMNS)
    state.team_override = members if override is not None else None
    state.team_override_source = override
    if "team_df" not in state or not state.team_df.equals(frame):
        state.team_df = frame
        state.team_version = state.get("team_version", 0) + 1


def sync_team() -> None:
    """Reload team.json on every run unless an explicit override is active."""
    if state.get("team_override") is not None:
        state.team_file_error = None
        return
    try:
        members, state.team_file_error = load_team(), None
    except InputError as err:
        members, state.team_file_error = [], str(err)
    set_team(members)


def clear_team_override() -> None:
    """Callback: drop a logged-run or what-if team override and reload team.json."""
    state.team_override = None
    state.team_override_source = None


def init() -> None:
    if "team_df" in state:
        return
    state.update(
        team_version=0,
        team_override=None,
        team_override_source=None,
        team_file_error=None,
    )
    sync_team()
    # Widget defaults live in the session state, so open_run can overwrite them.
    state.update(idea="", start=date.today(), deadline=None, free_days="", consent=False)
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
        # The conversation that changes the plan (step 5) and its open proposal.
        chat=[],
        proposal=None,
        rounds_start=None,
        planning_rest=False,
    )


def restore_editors() -> None:
    """After a visit to another page the plan table editor starts again from its last content."""
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


def fill_project(project: Project) -> None:
    """Put a project into the fields of step 2. Only before they are drawn: from a callback,
    or from code that runs before the widgets."""
    state.update(
        idea=project.idea,
        start=project.start_date,
        deadline=project.deadline,
        free_days=free_days_text(project.free_days),
    )


def take_dates(project: Project) -> None:
    """Callback: idea and dates from the Projektauftrag. Free days stay: they are entered
    here."""
    state.update(idea=project.idea, start=project.start_date, deadline=project.deadline)


def open_run(path) -> None:
    """Callback: runs before the widgets, so it may fill their keys."""
    project, team, plan, record = load_run(path)
    set_team(team, override=f"Protokoll {path.name}")
    fill_project(project)
    state.planning_rest = False  # a whole plan: nothing done outside it
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
    set_team(current_team(adopted), override="Rest des übernommenen Projekts")
    fill_project(project)
    show_plan(plan, [], "Rest des übernommenen Projekts", None)
    forget_conversation()
    state.planning_rest = True
    state.step = STEPS[4]  # straight to the step with the conversation


def ask(wish: str | None = None) -> None:
    """Callback of the chat input and of the suggested wishes: keep the wish for the run that
    follows. Without an argument it is what was typed."""
    state.asked = wish or state.wish


def decide(accept: bool) -> None:
    """Callback: the project lead takes or drops the change the agent proposed."""
    proposal = state.proposal
    if proposal is None:
        # The second click of a double click: Streamlit calls the callback again although
        # the first click has already decided. Nothing is left to decide.
        return
    state.proposal = None
    state.chat.append(
        {"wish": proposal["wish"], "changes": proposal["changes"], "accepted": accept}
    )
    if accept and proposal.get("absences"):
        # The absences the wish named go into the team table for this planning session.
        team = with_absences(proposal["team"], proposal["absences"])
        set_team(team, override="Übernommener Änderungsvorschlag")
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
sync_team()
try:
    life = lifecycle.load()
except InputError:
    life = None  # the project path above the page says why
# Step 2 starts with what the Projektauftrag says; typed in here, it stays as typed.
if life is not None and life.project is not None and not state.idea.strip() and not state.deadline:
    take_dates(life.project)
needs = lifecycle.approved_requirements(life)
# Only with approved requirements does the plan get traced; without, all stays as before.
state.covered = frozenset()
if state.get("planning_rest") and needs is not None:
    try:
        baseline = load_tracking()
    except InputError:
        baseline = None  # the project path above the page says why
    if baseline is not None:
        state.covered = covered_requirements(baseline, needs)
trace = {"requirements": needs, "covered": state.covered} if needs is not None else {}
# The agents also get the approved design, as context; the check does not use it.
design = lifecycle.approved_design(life)
context = {**trace, **({"design": design} if design is not None else {})}
# Right below the project path, where every page says what is next.
next_line = st.container()
st.header("Planung")
st.caption(
    "Der Agent schlägt einen Plan vor, Python prüft ihn deterministisch, die Projektleitung "
    "entscheidet."
)
if rest_error:
    st.error(f"Der Rest des Projekts konnte nicht geladen werden: {as_text(rest_error)}")
status = st.container()  # filled at the end, when team, project and plan are known
# on_change="rerun" makes the selection a value in the session state, so buttons can open a
# step. Every step is still rendered on every run (see the module docstring).
tabs = st.tabs(STEPS, key="step", on_change="rerun")

# 1 · Team ---------------------------------------------------------------------------------
with tabs[0]:
    st.subheader("Team")
    st.html(roles(python="zeigt, was das Team eingetragen hat"))
    st.caption(
        "Skills mit Stufe 1–5, Stunden pro Woche und Abwesenheit trägt jedes Teammitglied "
        "selbst ein (Ansicht Team, Mein Bereich). Damit weist der Agent die Aufgaben zu; an "
        "Tagen unter „Abwesend“ plant er für die Person keine Arbeit ein."
    )
    if state.team_file_error:
        st.error(
            f"Gespeichertes Team konnte nicht geladen werden: {as_text(state.team_file_error)}"
        )
    if state.get("team_override") is not None:
        st.caption(
            f"Angezeigt wird das Team aus „{as_text(state.team_override_source or '')}“ "
            "(nicht die aktuelle Datei data/team.json)."
        )
        st.button(
            "Aktuelles Team laden",
            icon=":material/refresh:",
            on_click=clear_team_override,
        )
    edited_team = st.data_editor(
        state.team_df,
        key=f"team_editor_{state.team_version}",
        placeholder="",
        disabled=True,  # each member keeps their own row, on Mein Bereich
        width="stretch",
        column_config={
            "Name": st.column_config.TextColumn(required=True),
            "Skills": st.column_config.TextColumn(
                help="Skill mit Stufe 1–5, z. B. Python 4, SQL 3"
            ),
            "Stunden/Woche": st.column_config.NumberColumn(
                format="localized", min_value=1, max_value=120
            ),
            "Abwesend": st.column_config.TextColumn(
                help="Tage ohne Arbeit, z. B. 01.12.2026–05.12.2026, 23.12.2026. Feiertage "
                "und andere freie Tage für alle stehen beim Projekt (Schritt 2)."
            ),
            "Notiz": st.column_config.TextColumn(help="z. B. Urlaub, Prüfungsphase"),
        },
    )
    try:
        team = rows_to_team(edited_team.to_dict("records"))
    except InputError as err:
        team = None
        st.error(f"Bitte korrigieren:\n\n{as_text(str(err))}")
    if team == []:
        st.info(
            "Noch niemand im Team. Jedes Teammitglied trägt sich in der Ansicht Team unter "
            "„Mein Bereich“ ein (links unter „Ich bin“: „Neu im Team …“)."
        )
    consent = ask_consent(
        "consent",
        "ihre Angaben (Name, Skills, Stunden, Abwesenheiten, Notiz) zur Planung",
        persist_state="session",
    )
    next_step("Weiter zum Projekt", STEPS[1], bool(team) and consent, "to_project")

# 2 · Projekt ------------------------------------------------------------------------------
with tabs[1]:
    st.subheader("Projekt")
    st.html(roles(du="beschreibst Ziel und Termine"))
    st.caption("Was soll bis wann entstehen? Aus der Idee leitet der Agent die Aufgaben ab.")
    charter = life.project if life is not None else None
    if charter is not None and (state.idea, state.start, state.deadline) != (
        charter.idea,
        charter.start_date,
        charter.deadline,
    ):
        st.button(
            "Eckdaten aus dem Projektauftrag übernehmen",
            icon=":material/input:",
            on_click=take_dates,
            args=(charter,),
            help="Idee, Start und Deadline, wie sie auf der Seite Projektauftrag stehen. "
            "Freie Tage bleiben, wie sie hier stehen.",
        )
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
    days_off = st.text_input(
        "Freie Tage für alle (optional)",
        key="free_days",
        persist_state="session",
        placeholder="z. B. 24.12.2026–01.01.2027, 06.01.2027",
        help="Feiertage oder eine Pause: An diesen Tagen plant die Prüfung für niemanden "
        "Arbeit ein. Einzelne Tage oder Zeiträume, getrennt durch Komma. Abwesenheiten "
        "einzelner Personen stehen in der Teamtabelle.",
    )
    project = None
    project_gap = "Projektidee und Deadline (Schritt 2)"  # what step 3 says is missing
    if not idea.strip() or deadline is None:
        st.info("Beschreibe die Projektidee und wähle eine Deadline.")
    else:
        try:
            project = Project(
                idea=idea, start_date=start, deadline=deadline, free_days=free_days(days_off)
            )
        except InputError as err:
            st.error(f"Freie Tage: {as_text(str(err))}")
            project_gap = "lesbare freie Tage (Schritt 2)"
        except ValidationError as err:
            st.error("; ".join(e["msg"].removeprefix("Value error, ") for e in err.errors()))
            project_gap = "ein gültiges Projekt (Schritt 2)"
    next_step("Weiter zur Planung", STEPS[2], project is not None, "to_planning")

# 3 · Planung ------------------------------------------------------------------------------
with tabs[2]:
    st.subheader("Planung mit dem Agenten")
    new_plan, logged_run = st.columns([3, 2], gap="medium")
    with new_plan.container(border=True, key="panel-agent", height="stretch"):
        heading(
            "smart_toy",
            "Neuen Plan erstellen",
            agent="entwirft",
            python="prüft jede Runde",
        )
        st.caption(
            "Der Agent entwirft, Python prüft, der Agent bessert nach, bis der Plan ohne Fehler "
            "ist."
        )
        missing = [
            text
            for ok, text in [
                (bool(team), "ein gültiges Team (Schritt 1)"),
                (consent, "die Zustimmung des Teams (Schritt 1)"),
                (project is not None, project_gap),
            ]
            if not ok
        ]
        if missing:
            st.info("Für die Planung fehlt noch: " + ", ".join(missing) + ".")
        # The status box of a run lists its rounds; the folded log below is for later runs.
        ran_now = st.button(
            "Plan mit dem Agenten erstellen",
            type="primary",
            icon=":material/play_arrow:",
            disabled=bool(missing),
        )
        if ran_now:
            rounds = []
            track = Track()
            with st.status("Der Agent plant …", expanded=True) as status:
                st.caption(BUSY_HINT)
                show_round = round_printer()

                def on_round(record):
                    rounds.append(record)
                    track.round(record)
                    show_round(record)

                started = time.monotonic()
                failure = None
                log_errors: list[str] = []
                try:
                    with collect_log_errors() as log_errors:
                        plan = run_planning(project, team, on_round=on_round, **context)
                except PlanningError as err:
                    failure = str(err)
                except APIError as err:
                    failure = describe_api_error(err)
                else:
                    show_plan(plan, rounds, "Agent", round(time.monotonic() - started, 1))
                    forget_conversation()
                # The message goes below the box: a collapsed status would hide it.
                track.end(not failure)
                label = (
                    f"Kein Plan nach {rounds_text(len(rounds))}" if failure else "Plan angenommen"
                )
                status.update(label=label, state="error" if failure else "complete", expanded=True)
            if failure:
                st.error(as_text(failure))
            else:
                st.success(
                    f"Plan angenommen nach {rounds_text(len(rounds))}. Er steht in Schritt 4 und 5."
                )
            if log_errors:
                st.warning("\n".join(as_text(msg) for msg in log_errors))

    with logged_run.container(border=True, key="panel-run", height="stretch"):
        heading("history", "Protokollierten Lauf öffnen", du="öffnest einen früheren Lauf")
        st.caption("Zeigt einen früheren Plan ohne neuen Aufruf vom Agenten.")
        try:
            runs = saved_runs()
        except (OSError, ValueError) as err:  # a damaged log file, or one that cannot be read
            runs = []
            st.error(f"Protokolle in logs/ konnten nicht gelesen werden: {as_text(str(err))}")
        if not runs:
            st.caption("Noch keine protokollierten Läufe mit Plan.")
        else:
            chosen = st.selectbox("Lauf", runs, format_func=lambda p: p.name)
            st.button(
                "Lauf öffnen", icon=":material/folder_open:", on_click=open_run, args=(chosen,)
            )

    if state.rounds and not ran_now:
        # Folded: the result is the plan in step 4; how it came about is a detail.
        title = f"So ist der Plan entstanden ({state.source}, {rounds_text(len(state.rounds))})"
        with st.expander(title), st.container(key="rounds-log"):
            show_logged_round = round_printer(state.rounds_start)
            for record in state.rounds:
                show_logged_round(record)
    if state.plan is not None:
        next_step("Ergebnis ansehen", STEPS[3], False, "to_result")

# The current check, shared by steps 4–6. No LLM: it runs on every rerun.
result = check_plan(state.plan, team, project, **trace) if state.plan and team and project else None

# 4 · Ergebnis -----------------------------------------------------------------------------
with tabs[3]:
    st.subheader("Ergebnis")
    st.html(roles(python="hat geprüft und gerechnet", du="liest und beurteilst"))
    if state.plan is None:
        st.info("Noch kein Plan. Erstelle ihn in Schritt 3 oder öffne einen protokollierten Lauf.")
    elif result is None:
        st.warning("Team oder Projekt sind unvollständig, der Plan kann nicht geprüft werden.")
    else:
        st.caption(
            f"Quelle: {state.source}"
            + (" · von der Projektleitung angepasst" if state.edited else "")
        )
        # The result first: a missed deadline outweighs every other warning.
        kinds = zip(result.warnings, result.warning_kinds, strict=True)
        late = [warning for warning, kind in kinds if kind[0] == "late"]
        end = result.end_date.strftime("%d.%m.%Y") if result.end_date else "–"
        if late and not result.errors:
            verdict("bad", late[0])
            said = late[0]
        else:
            said = said_in_full(result.errors, result.warnings)
            fine = f"Planende {end}: keine Fehler, keine Warnungen."
            verdict(*check_verdict(result.errors, result.warnings, fine))
        a, b, c = st.columns(3)
        a.metric("Planende", end)
        b.metric("Fehler", len(result.errors))
        c.metric("Warnungen", len(result.warnings))

        with st.container(border=True, key="panel-schedule"):
            heading("view_timeline", "Terminplan")
            if result.schedule:
                bars, deadline_line = gantt(state.plan, result, project.deadline)
                chart = (
                    alt.Chart(pd.DataFrame(bars))
                    .mark_bar(cornerRadius=3)
                    .encode(
                        x=alt.X("Start:T", title=None, axis=alt.Axis(format="%d.%m.")),
                        x2="Ende:T",
                        y=alt.Y("Aufgabe:N", sort=None, title=None, axis=TASK_AXIS),
                        color=alt.Color("Person:N", legend=LEGEND),
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
                layered = on_panel(
                    chart + deadline_rule + deadline_label,
                    "Gantt-Diagramm: je Aufgabe ein Balken von Start bis Ende, gefärbt nach "
                    "Person, mit einer senkrechten Linie an der Deadline. Dieselben Termine "
                    "stehen in der Tabelle des Plans.",
                )
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
        # Every finding, below the chart it is about.
        messages(result.errors, result.warnings, said=said)  # not again what the verdict says

        with st.container(border=True, key="panel-load"):
            heading("groups", "Auslastung bis zur Deadline")
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
            heading("warning", "Risiken")
            if state.plan.risks:
                st.markdown("\n".join(f"- {as_text(r)}" for r in state.plan.risks))
            else:
                st.caption("Der Plan nennt keine Risiken.")

        with st.container(border=True, key="panel-trace"):
            heading("checklist", "Anforderungen und Aufgaben", python="ordnet zu")
            if needs is None:
                st.caption(
                    "Keine freigegebenen Anforderungen: Die Aufgaben sind keiner Anforderung "
                    "zugeordnet. Lege sie auf der Seite Anforderungen an und gib sie frei."
                )
            else:
                st.dataframe(
                    style_priority(pd.DataFrame(trace_rows(needs, state.plan))), hide_index=True
                )

        with st.container(border=True, key="panel-demos"):
            heading(
                "slideshow",
                "Demos je Woche",
                agent="schlägt vor",
                python="prüft gegen den Zeitplan",
            )
            demos = demo_rows(state.plan, result, project) if project else []
            if demos:
                st.caption(
                    "Jede Woche ein Ergebnis, das sich vorführen lässt: So zeigt sich früh, wo das "
                    "Projekt hängt. Ob eine Demo stattfand, trägst du in der Kontrolle ein."
                )
                st.dataframe(pd.DataFrame(demos), hide_index=True)
            else:
                st.caption(
                    "Der Plan nennt keine Wochen-Demos. Bitte den Agenten im Schritt Anpassen "
                    "darum, "
                    "zum Beispiel: „Plane für jede Woche eine Demo.“"
                )

        with st.container(border=True, key="panel-reasons"):
            heading("assignment_ind", "Zuweisungen und Begründungen")
            reasons = pd.DataFrame(plan_rows(state.plan))[["ID", "Aufgabe", "Person", "Begründung"]]
            if result.slack:
                reasons.insert(3, "Puffer (Tage)", reasons["ID"].map(result.slack))
            st.dataframe(reasons, hide_index=True)

        if result.schedule:
            with st.container(border=True, key="panel-task"):
                heading("search", "Aufgabe im Detail")
                st.caption(
                    "Warum diese Person, was hängt an der Aufgabe, und wer könnte sie sonst "
                    "übernehmen? Die Begründung stammt vom Agenten, alles andere rechnet Python."
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
                    st.markdown(as_text(view["description"]))
                why, around = st.columns(2, gap="medium")
                with why:
                    st.markdown(f"**Warum {as_text(view['member'])}?**")
                    st.markdown(as_text(view["reason"]))
                    for skill, level in view["skills"]:
                        have = (
                            f"Stufe {level}" if level else f"bei {view['member']} nicht angegeben"
                        )
                        st.markdown(f"- {as_text(skill)}: {have}")
                with around:
                    st.markdown("**Braucht vorher**")
                    st.markdown(
                        "\n".join(
                            f"- {as_text(tid)} · {as_text(title)}"
                            for tid, title in view["depends_on"]
                        )
                        or "Nichts: Die Aufgabe kann sofort beginnen."
                    )
                    st.markdown("**Darauf warten**")
                    st.markdown(
                        "\n".join(
                            f"- {as_text(tid)} · {as_text(title)}"
                            for tid, title in view["needed_by"]
                        )
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
        heading("edit", "Von Hand ändern", du="änderst die Tabelle", python="prüft erneut")
        st.caption(
            "Ändere Personen, Stunden oder Abhängigkeiten. „Erneut prüfen“ rechnet nur "
            "deterministisch nach, der Agent wird nicht aufgerufen."
        )
        edited_plan = st.data_editor(
            state.plan_df,
            key=f"plan_editor_{state.editor_version}",
            placeholder="",
            num_rows="dynamic",
            width="stretch",
            column_config={
                "Stunden": st.column_config.NumberColumn(format="localized", min_value=0.5),
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
                st.error(f"Bitte korrigieren:\n\n{as_text(str(err))}")
            else:
                changed = new != table_plan(state.original)
                state.update(
                    plan=new,
                    edited=changed,
                    hand_edited=state.get("hand_edited", False) or changed,
                )
                # The result stands in step 4, not here: the notice says what came out.
                if team and project:
                    found = check_plan(new, team, project, **trace)
                    count = len(found.warnings)
                    notify(
                        f"Geprüft: {len(found.errors)} Fehler, {count} "
                        f"Warnung{'' if count == 1 else 'en'}. Details in Schritt 4."
                    )
                else:
                    notify("Gespeichert. Prüfen lässt sich der Plan mit Team und Projekt.")
                st.rerun()
        next_step("Ergebnis ansehen", STEPS[3], False, "back_to_result")

        with chat_panel:
            heading(
                "forum",
                "Mit dem Agenten ändern",
                agent="ändert auf deinen Wunsch",
                python="prüft",
                du="übernimmst oder verwirfst",
            )
            st.caption(
                "Sag, was sich ändern soll, oder spiel eine Annahme durch: „Clara übernimmt die "
                "Tests“, „Was, wenn das Backend doppelt so lange dauert?“. Der Agent ändert den "
                "Plan, Python prüft ihn, du siehst die Unterschiede und entscheidest."
            )
            for turn in state.chat:
                with st.chat_message("user"):
                    st.text(turn["wish"])
                with st.chat_message("assistant"):
                    st.markdown("**Übernommen**" if turn["accepted"] else "**Verworfen**")
                    st.markdown(
                        "\n".join(f"- {as_text(c)}" for c in turn["changes"]) or "Keine Änderung."
                    )

            proposal = state.proposal
            # In the form of the table: "Erneut prüfen" writes an untouched plan anew in
            # that form, and nobody has changed it then.
            if proposal is not None and table_plan(proposal["basis"]) != table_plan(state.plan):
                state.proposal = proposal = None
                st.info(
                    "Der Plan wurde seit dem Vorschlag von Hand geändert. Der Vorschlag passt "
                    "nicht mehr dazu und ist verworfen."
                )
            # Its absences were set for the team as it was then.
            if proposal is not None and proposal.get("absences") and proposal["team"] != team:
                state.proposal = proposal = None
                st.info(
                    "Das Team wurde seit dem Vorschlag geändert. Der Vorschlag rechnete mit dem "
                    "alten Team und ist verworfen."
                )
            blocked = [
                text
                for ok, text in [
                    (consent, "die Zustimmung des Teams (Schritt 1)"),
                    (result is not None, "ein gültiges Team und Projekt (Schritt 1 und 2)"),
                ]
                if not ok
            ]
            # The agent gets the current plan, and taking its proposal replaces the table. Hand
            # edits that were not checked would be ignored first and overwritten then: no
            # wish and no "Übernehmen" while they wait.
            unchecked = not table_matches_plan()
            wish = state.pop("asked", None)  # set by the chat input at the end of the panel
            # A second wish must not replace a proposal that is still open.
            if wish and proposal is None and not blocked and not unchecked:
                with st.chat_message("user"):
                    st.text(wish)
                change_rounds = []
                track = Track()
                with st.status("Der Agent ändert den Plan …", expanded=True) as status:
                    st.caption(BUSY_HINT)
                    with st.container(key="rounds-change"):
                        show_change_round = round_printer(state.plan)

                        def on_change_round(record):
                            change_rounds.append(record)
                            track.round(record)
                            show_change_round(record)

                        started = time.monotonic()
                        failure = None
                        log_errors: list[str] = []
                        try:
                            with collect_log_errors() as log_errors:
                                replanned = run_replanning(
                                    project,
                                    team,
                                    state.plan,
                                    wish,
                                    on_round=on_change_round,
                                    **context,
                                )
                        except PlanningError as err:
                            failure = str(err)
                        except APIError as err:
                            failure = describe_api_error(err)
                        else:
                            state.proposal = proposal = {
                                "wish": wish,
                                "basis": state.plan,
                                "plan": replanned.plan,
                                # Set by the agent from the wish; the plan was checked with them.
                                "absences": replanned.absences,
                                "team": team,
                                "rounds": change_rounds,
                                "seconds": round(time.monotonic() - started, 1),
                            }
                    track.end(not failure)
                    label = (
                        f"Kein Vorschlag nach {rounds_text(len(change_rounds))}"
                        if failure
                        else f"Vorschlag nach {rounds_text(len(change_rounds))}"
                    )
                    status.update(
                        label=label, state="error" if failure else "complete", expanded=True
                    )
                # The message goes below the box: a collapsed status would hide it.
                if failure:
                    st.error(as_text(failure))
                    if log_errors:
                        st.warning("\n".join(as_text(msg) for msg in log_errors))
                else:
                    if log_errors:
                        state.replan_log_warning = "\n".join(log_errors)
                    # Again from the top: the input is locked while the proposal is open.
                    st.rerun()

            if log_warning := state.pop("replan_log_warning", None):
                st.warning(as_text(log_warning))

            if proposal is not None:
                proposed = (
                    check_plan(
                        proposal["plan"],
                        with_absences(team, proposal.get("absences", [])),
                        project,
                        **trace,
                    )
                    if result
                    else None
                )
                with st.chat_message("assistant"):
                    st.markdown("**Vorschlag vom Agenten, von Python geprüft**")
                    st.text(proposal["wish"])
                    proposal["changes"] = [
                        f"Abwesenheit neu: {a.member} {free_days_text([a])}"
                        for a in proposal.get("absences", [])
                    ] + plan_changes(state.plan, proposal["plan"])
                    if proposed is not None:
                        proposal["changes"] += check_changes(
                            result, proposed, pair_tasks(state.plan, proposal["plan"]), project
                        )
                    if proposal["changes"]:
                        st.markdown("\n".join(f"- {as_text(c)}" for c in proposal["changes"]))
                    else:
                        st.info("Der Agent schlägt keine Änderung am Plan vor.")
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

            # The input comes last, below the conversation. Its callback hands the wish to
            # the run that follows, which answers it above.
            if blocked:
                st.caption(
                    "Für eine Änderung mit dem Agenten fehlt noch: " + ", ".join(blocked) + "."
                )
            elif unchecked:
                st.warning(
                    "In der Tabelle unten stehen Änderungen, die noch nicht geprüft sind. Der "
                    "Agent "
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

# 6 · Übernehmen --------------------------------------------------------------------------
with tabs[5]:
    st.subheader("Übernehmen und exportieren")
    if state.plan is None or result is None:
        st.info("Noch kein geprüfter Plan zum Exportieren.")
    else:
        if result.errors:
            st.warning("Der Plan hat noch Fehler (siehe Schritt 4). Export ist trotzdem möglich.")

        def record_export(fmt: str) -> None:
            row = {
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
            try:
                append_run(row)
            except (OSError, ValueError) as err:  # the file, or a value that has no bytes
                # A callback cannot place a message: the run that follows shows it.
                state.export_error = str(err)

        stamp = date.today().strftime("%Y%m%d")
        take_over, download = st.columns(2, gap="medium")
        with download.container(border=True, key="panel-download", height="stretch"):
            heading("download", "Herunterladen")
            not_recorded = state.pop("export_error", None)
            if not_recorded:
                st.error(
                    f"Der Plan ist heruntergeladen, aber nicht in {RUNS_CSV.parent.name}/"
                    f"{RUNS_CSV.name} vermerkt: {not_recorded}"
                )
            with st.container(horizontal=True):
                st.download_button(
                    "Als Markdown herunterladen",
                    to_markdown(project, state.plan, result, needs),
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
            heading("flag", "Als Projekt übernehmen", du="gibst den Plan frei")
            st.caption("Der Plan wird zur Grundlage für die Seiten Durchführung und Kontrolle.")
            overwrite, keep = True, None
            replace_unreadable = False
            try:
                adopted = load_tracking()
            except InputError as err:
                adopted = None
                replace_unreadable = True
                st.error(
                    f"Das übernommene Projekt konnte nicht gelesen werden: {as_text(str(err))}"
                )
                # Its progress may still be rescued by hand: replaced only on purpose.
                overwrite = st.checkbox(
                    "Die beschädigte Datei durch diesen Plan ersetzen. Ihr Inhalt geht verloren.",
                    key="adopt_replace_damaged",
                )
            if adopted is not None and (
                has_progress(adopted) or adopted.results or adopted.signoffs
            ):
                # No choice made in advance: keeping fits only the rest of this project.
                choice = st.radio(
                    f"Das am {adopted.adopted:%d.%m.%Y} übernommene Projekt hat schon erfassten "
                    "Fortschritt, Testergebnisse oder Abnahmen.",
                    [KEEP, DROP],
                    index=None,
                    key="adopt_progress",
                    help="Behalten passt, wenn dieser Plan der neu geplante Rest des Projekts "
                    "ist (Seite Kontrolle, „Rest mit dem Agenten umplanen“): Fertige Aufgaben und "
                    "gebuchte Stunden bleiben in den Kennzahlen, begonnene Aufgaben gehen im "
                    "neuen Plan weiter.",
                )
                if choice is None:
                    overwrite = False
                elif choice == KEEP:
                    keep = adopted
                    if again := finished_again(adopted, state.plan):
                        overwrite = False
                        st.warning(
                            f"Schon fertig und wieder im Plan: {', '.join(again)}. Behalten "
                            "würde diese Arbeit doppelt zählen. Plane den Rest über die Seite "
                            "Kontrolle („Rest mit dem Agenten umplanen“), oder verwirf den "
                            "Fortschritt."
                        )
                else:
                    overwrite = st.checkbox(
                        "Ja, den erfassten Fortschritt verwerfen.", key="adopt_overwrite"
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
                try:
                    with PROJECT_WRITE_LOCK:
                        require_current(adopted, replace_unreadable=replace_unreadable)
                        adopt(project, team, state.plan, keep=keep, requirements=needs)
                except InputError as err:  # the checks above already keep the button off
                    st.error(f"Nicht übernommen: {as_text(str(err))}.")
                except OSError as err:
                    st.error(
                        f"data/projekt.json konnte nicht gespeichert werden: {as_text(str(err))}. "
                        "Das bisher übernommene Projekt bleibt, wie es ist."
                    )
                else:
                    st.success("Übernommen. Weiter auf den Seiten Durchführung und Kontrolle.")

    comparison_card(
        "planung",
        review_seconds=(
            round(time.monotonic() - state.shown_at, 1)
            if state.get("shown_at") is not None
            else None
        ),
        edited=state.get("hand_edited", state.edited) if state.plan is not None else None,
    )


# Where the planning stands, above the steps.
try:
    baseline = load_tracking()
except InputError:
    baseline = None  # ui.journey shows the error above this page
# Nothing else on the table than the adopted project: the planning is done for now. The
# rest of a project to plan again can be the same plan, from another day: project and team
# count too.
planned = baseline is not None and (
    state.plan is None
    or (state.plan, project, team) == (baseline.plan, baseline.project, baseline.team)
)
if state.plan is None and baseline is not None:
    # The path ticks "Planen" for it; "Plan offen" beside the tick said the opposite.
    plan_chip = chip("Plan übernommen", "on")
elif state.plan is None:
    plan_chip = chip("Plan offen")
elif result is None:
    plan_chip = chip("Plan nicht prüfbar", "warn")
elif result.errors:
    plan_chip = chip(f"Plan: {len(result.errors)} Fehler", "warn")
else:
    count = len(result.warnings)
    notes = f", {count} Warnung{'' if count == 1 else 'en'}" if count else ""
    plan_chip = chip(f"Plan geprüft{notes}", "on")
demo_chip = None
if state.plan is not None:
    weeks = len(state.plan.demos)
    demo_chip = chip(f"Wochen-Demos: {weeks or 'keine'}", "on" if weeks else "")
people = f"Team: {len(team)} Person{'' if len(team) == 1 else 'en'}" if team else "Team fehlt"
# What is next, in the order of the steps: one line, and a button that opens that step.
if not team:
    todo, step = (
        "Noch niemand im Team. Bitte das Team, Name, Skills und Stunden pro Woche in "
        "„Mein Bereich“ (Ansicht Team) einzutragen.",
        0,
    )
elif not consent:
    todo, step = "Bestätige die Zustimmung des Teams, dass seine Angaben an den Agenten gehen.", 0
elif project is None:
    todo, step = "Beschreibe Projektidee und Deadline.", 1
elif state.plan is None:
    todo, step = "Lass den Agenten einen Plan erstellen oder öffne einen protokollierten Lauf.", 2
elif result.errors:  # team, project and plan are there, so the plan was checked
    todo, step = "Der Plan hat Fehler. Ändere ihn von Hand oder mit dem Agenten.", 4
else:
    todo, step = "Der Plan ist geprüft. Sieh dir das Ergebnis an und übernimm ihn als Projekt.", 5
with status:
    st.html(
        strip(
            chip(people, "on" if team else ""),
            chip("Zustimmung", "on" if consent else ""),
            chip("Projekt", "on" if project is not None else ""),
            phase_chip("Anforderungen", lifecycle.requirements_state(life)),
            phase_chip("Entwurf", lifecycle.design_state(life)),
            plan_chip,
            *([demo_chip] if demo_chip else []),
        )
    )
with next_line:
    with st.container(horizontal=True, vertical_alignment="center", key="next-step-planung"):
        if planned:
            # The same next step as on the Startseite and the pages of the project.
            advice, where = project_step(baseline, date.today())
            st.markdown(f"**Jetzt dran:** Der Plan ist als Projekt übernommen. {as_text(advice)}")
            target, label = PAGES[where]
            if st.button(label, key="planung-go", type="primary", icon=":material/arrow_forward:"):
                st.switch_page(target)
        else:
            st.markdown(f"**Jetzt dran (Schritt {step + 1}):** {todo}")
        if not planned and state.get("step", STEPS[0]) != STEPS[step]:
            st.button(
                f"Zu Schritt {step + 1}",
                key="planung-go",
                type="primary",
                icon=":material/arrow_forward:",
                on_click=go,
                args=(STEPS[step],),
            )
