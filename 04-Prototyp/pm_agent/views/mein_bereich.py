"""Page "Mein Bereich" (view "Team"): what a team member keeps up to date themselves.
Skills, hours and absences go into the team the plan is made from, the state of their tasks
into the adopted project. The project lead sees both and plans with them, without changing
them. No sign-in: a view of the site, not access control."""

import pandas as pd
import streamlit as st

from pm_agent.tracking import (
    PROGRESS_COLUMNS,
    PROGRESS_READ_ONLY,
    apply_rows,
    progress_rows,
    save_if_current,
)
from pm_agent.ui import (
    NEW_MEMBER,
    PROGRESS_CONFIG,
    adopted_project,
    as_text,
    heading,
    kept_editor,
    notify,
)
from pm_agent.workbench import (
    TEAM_COLUMNS,
    TEAM_FILE,
    InputError,
    load_team,
    rows_to_team,
    save_team,
    team_rows,
)

state = st.session_state
me = state.get("me")
new = me == NEW_MEMBER

st.header("Mein Bereich" if new or not me else f"Mein Bereich · {me}")
st.caption(
    "Hier trägst du ein, was nur du weißt: deine Fähigkeiten, deine Zeit und den Stand deiner "
    "Aufgaben. Die Projektleitung sieht es und plant damit, ändert es aber nicht."
)
try:
    team, damaged = load_team(), ""
except InputError as err:
    team, damaged = [], str(err)
if not me:
    st.info("Wähle links unter „Ich bin“ deinen Namen.")
    st.stop()
member = None if new else next((m for m in team if m.name == me), None)
if not new and member is None:
    st.error(f"{as_text(me)} steht nicht im Team. Wähle links einen anderen Namen.")
    st.stop()

with st.container(border=True, key="panel-me"):
    heading("person", "Meine Angaben", du="pflegst sie selbst")
    replace = True
    if damaged:
        # The saved file may still be rescued by hand: replaced only on purpose.
        st.error(f"Das gespeicherte Team konnte nicht gelesen werden: {as_text(damaged)}")
        replace = st.checkbox(
            "Die beschädigte Team-Datei durch einen neuen Eintrag ersetzen. Ihr Inhalt geht "
            "verloren.",
            key="team_replace_damaged",
        )
    row = (
        team_rows([member])[0]
        if member
        else {"Name": "", "Skills": "", "Stunden/Woche": 20.0, "Abwesend": "", "Notiz": ""}
    )
    # A form per person: what one typed and did not save does not show up for the next.
    with st.form(f"me_form_{me}", border=False):
        name = st.text_input("Name", row["Name"], disabled=not new)
        skills = st.text_input(
            "Fähigkeiten mit Stufe 1–5",
            row["Skills"],
            help="z. B. Python 4, SQL 3. Danach verteilt der Agent die Aufgaben.",
        )
        hours = st.number_input(
            "Stunden pro Woche",
            min_value=1.0,
            max_value=120.0,
            value=float(row["Stunden/Woche"]),
            step=1.0,
            format="%.0f",  # "30", not "30.00"
        )
        away = st.text_input(
            "Abwesend", row["Abwesend"], help="z. B. 01.12.2026–05.12.2026, 23.12.2026"
        )
        note = st.text_input("Notiz", row["Notiz"], help="z. B. Prüfungsphase")
        saved = st.form_submit_button(
            "Speichern", type="primary", icon=":material/save:", disabled=not replace
        )
    if saved and new and not name.strip():
        st.error("Bitte deinen Namen eintragen.")
    elif saved:
        try:
            [mine] = rows_to_team(
                [
                    {
                        "Name": name,
                        "Skills": skills,
                        "Stunden/Woche": hours,
                        "Abwesend": away,
                        "Notiz": note,
                    }
                ]
            )
        except InputError as err:
            st.error(f"Bitte korrigieren:\n\n{as_text(str(err))}")
        else:
            if new and any(m.name == mine.name for m in team):
                st.error(f"{as_text(mine.name)} gibt es im Team schon. Wähle links den Namen.")
            else:
                updated = team + [mine] if new else [mine if m.name == me else m for m in team]
                place = f"{TEAM_FILE.parent.name}/{TEAM_FILE.name}"
                try:
                    save_team(updated)
                except OSError as err:
                    st.error(
                        f"{place} konnte nicht gespeichert werden: {as_text(str(err))}. "
                        "Die gespeicherte Datei bleibt, wie sie ist."
                    )
                else:
                    notify(f"Deine Angaben sind gespeichert (lokal in {place}).")
                    state.me_next = mine.name  # the sidebar shows the name on the next run
                    # The Planung page of this session shows the team as saved now, not an
                    # earlier copy of its table.
                    state.pop("team_current", None)
                    if "team_df" in state:
                        state.team_df = pd.DataFrame(team_rows(updated), columns=TEAM_COLUMNS)
                        state.team_version += 1
                    st.rerun()

if new:
    st.stop()

with st.container(border=True, key="panel-progress"):
    heading("task_alt", "Meine Aufgaben", du="trägst Status und Stunden ein")
    tracking = adopted_project(
        waiting="Noch kein Plan übernommen. Dann stehen deine Aufgaben hier."
    )
    rows = [r for r in progress_rows(tracking) if r["Person"] == me] if tracking else []
    if tracking and not rows:
        st.caption(f"Im übernommenen Plan hat {as_text(me)} keine Aufgabe.")
    elif rows:
        # Unsaved edits survive a visit to another page; the forecast columns are computed
        # anew. Saving raises the version: the editor starts again from the saved state.
        edited, conflict = kept_editor(
            "progress_editor_",
            "progress_version",
            tracking,
            pd.DataFrame(rows, columns=PROGRESS_COLUMNS),
            columns=[c for c in PROGRESS_COLUMNS if c not in PROGRESS_READ_ONLY],
            hide_index=True,
            width="stretch",
            disabled=PROGRESS_READ_ONLY,
            column_config=PROGRESS_CONFIG,
        )
        st.caption(
            "Status, Fertig am, Ist-Stunden, Rest und Notiz lassen sich ändern. Änderungen "
            "gelten erst nach dem Speichern. „Prognose Ende“ zeigt, wann die Aufgabe nach "
            "heutigem Stand fertig wird."
        )
        if (
            st.button("Fortschritt speichern", type="primary", icon=":material/save:")
            and not conflict
        ):
            try:
                updated = apply_rows(tracking, edited.to_dict("records"))
            except InputError as err:
                st.error(f"Bitte korrigieren:\n\n{as_text(str(err))}")
            else:
                try:
                    save_if_current(tracking, updated)
                except (InputError, OSError) as err:
                    st.error(
                        f"Der Fortschritt konnte nicht gespeichert werden: {as_text(str(err))}"
                    )
                else:
                    notify("Fortschritt gespeichert (lokal in data/projekt.json).")
                    state.progress_version = state.get("progress_version", 0) + 1
                    st.rerun()

with st.container(border=True, key="panel-lab-me"):
    heading("science", "KI-Lab", du="probierst es aus und sagst, wie es war")
    st.caption(
        "Zwei Planungsfälle, einer ohne und einer mit KI-Hilfe. Am Ende fragt das Lab nach "
        "deiner Reflexion: Daraus erfährt die Gruppe, ob die KI wirklich hilft."
    )
    st.page_link("views/ki_lab.py", label="Im KI-Lab mitmachen", icon=":material/arrow_forward:")
