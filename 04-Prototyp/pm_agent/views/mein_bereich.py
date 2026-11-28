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
from pm_agent.tracking import (
    load as load_tracking,
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
    TEAM_FILE,
    InputError,
    load_team,
    parse_member,
    save_team,
    team_rows,
)

state = st.session_state
me = state.get("me")
new = me == NEW_MEMBER

st.header("Mein Bereich" if new or not me else f"Mein Bereich · {as_text(me)}")
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
former_member = False
if not new and member is None and not damaged:
    try:
        adopted = load_tracking()
    except InputError as err:
        st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {as_text(str(err))}")
        st.stop()
    former_member = adopted is not None and any(a.member == me for a in adopted.plan.assignments)
    if not former_member:
        st.error(f"{as_text(me)} steht nicht im Team. Wähle links einen anderen Namen.")
        st.stop()


def _save_team_file(updated: list, notice: str, next_me: str | None) -> None:
    """Write team.json, report an OSError without hiding it, or notify and rerun."""
    place = f"{TEAM_FILE.parent.name}/{TEAM_FILE.name}"
    try:
        save_team(updated)
    except OSError as err:
        st.error(
            f"{place} konnte nicht gespeichert werden: {as_text(str(err))}. "
            "Die gespeicherte Datei bleibt, wie sie ist."
        )
    else:
        notify(notice.format(place=place))
        state.me_next = next_me  # the sidebar updates the selection on the next run
        st.rerun()


with st.container(border=True, key="panel-me"):
    heading("person", "Meine Angaben", du="pflegst sie selbst")
    replace = True
    if damaged:
        # The saved file may still be rescued by hand: replaced only on purpose.
        st.error(f"Das gespeicherte Team konnte nicht gelesen werden: {as_text(damaged)}")
        if new:
            replace = st.checkbox(
                "Die beschädigte Team-Datei durch einen neuen Eintrag ersetzen. Ihr Inhalt geht "
                "verloren.",
                key="team_replace_damaged",
            )
    if former_member:
        st.info(
            f"{as_text(me)} steht nicht mehr im Team (data/team.json). Die Aufgaben im "
            "übernommenen Plan lassen sich unten weiter pflegen, bis die Projektleitung umplant. "
            "Über „Neu im Team …“ lässt sich der Eintrag wieder anlegen."
        )
    elif new or member is not None:
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
                step=0.5,
                format="%g",
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
                mine = parse_member(
                    {
                        "Name": name,
                        "Skills": skills,
                        "Stunden/Woche": hours,
                        "Abwesend": away,
                        "Notiz": note,
                    }
                )
            except InputError as err:
                st.error(f"Bitte korrigieren:\n\n{as_text(str(err))}")
            else:
                if new and any(m.name == mine.name for m in team):
                    st.error(f"{as_text(mine.name)} gibt es im Team schon. Wähle links den Namen.")
                else:
                    updated = team + [mine] if new else [mine if m.name == me else m for m in team]
                    _save_team_file(
                        updated, "Deine Angaben sind gespeichert (lokal in {place}).", mine.name
                    )
        if member is not None:
            with st.expander("Team verlassen"):
                st.caption(
                    "Entfernt deinen Eintrag aus dem Team (data/team.json). Aufgaben im "
                    "übernommenen Plan bleiben unter deinem Namen bestehen, bis die "
                    "Projektleitung umplant."
                )
                leave_sure = st.checkbox(
                    f"Ja, {as_text(me)} aus dem Team entfernen.",
                    key=f"leave_team_sure_{me}",
                )
                if st.button(
                    "Team verlassen",
                    icon=":material/person_remove:",
                    disabled=not leave_sure,
                ):
                    _save_team_file(
                        [m for m in team if m.name != me], f"{me} hat das Team verlassen.", None
                    )

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
        my_ids = [r["ID"] for r in rows]
        # Scoped to this member's tasks so unrelated saves to projekt.json do not drop their
        # unsaved edits, while re-adoption or edits to these tasks still flag a conflict.
        basis = (
            tracking.adopted,
            tracking.project,
            [(t.id, t.title, t.estimate_hours) for t in tracking.plan.tasks if t.id in my_ids],
            {tid: tracking.progress[tid] for tid in my_ids},
        )
        version_key = f"progress_version_{me}"
        # Unsaved edits survive a visit to another page; the forecast columns are computed
        # anew. Saving raises the version: the editor starts again from the saved state.
        edited, conflict = kept_editor(
            f"progress_editor_{me}_",
            version_key,
            basis,
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
        can_save = not conflict
        if (
            st.button(
                "Fortschritt speichern",
                type="primary",
                icon=":material/save:",
                disabled=not can_save,
            )
            and can_save
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
                    state[version_key] = state.get(version_key, 0) + 1
                    st.rerun()

with st.container(border=True, key="panel-lab-me"):
    heading("science", "KI-Lab", du="probierst es aus und sagst, wie es war")
    st.caption(
        "Zwei Planungsfälle, einer ohne und einer mit KI-Hilfe. Am Ende fragt das Lab nach "
        "deiner Reflexion: Daraus erfährt die Gruppe, ob die KI wirklich hilft."
    )
    st.page_link("views/ki_lab.py", label="Im KI-Lab mitmachen", icon=":material/arrow_forward:")
