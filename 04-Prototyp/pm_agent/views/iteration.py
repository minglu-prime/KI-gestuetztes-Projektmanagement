"""Page "Iteration": what the next run starts from. Python collects deferred requirements,
open defects, open measures of the retros and open incidents, each with its origin. Starting
the next run moves this run's files into data/archiv and begins a new Vorhaben with the
backlog; nothing is deleted."""

from datetime import datetime

import pandas as pd
import streamlit as st

from pm_agent import closing, lifecycle
from pm_agent.tracking import PROJECT_WRITE_LOCK, require_current
from pm_agent.ui import adopted_project, as_text, heading
from pm_agent.workbench import DATA_DIR, InputError

st.header("Iteration")
st.caption(
    "Was kommt in den nächsten Durchlauf? Python stellt den Backlog zusammen, jeder Eintrag "
    "mit seiner Herkunft. Mit dem neuen Durchlauf beginnt ein neues Vorhaben: Claude bekommt "
    "den Backlog beim Entwurf der Anforderungen."
)
tracking = adopted_project()
if tracking is None:
    st.stop()

with st.container(border=True, key="panel-backlog"):
    heading("playlist_add", "Nächster Backlog", python="stellt zusammen")
    backlog = closing.next_backlog(tracking)
    if backlog:
        st.dataframe(
            pd.DataFrame([{"Eintrag": b.text, "Herkunft": b.origin} for b in backlog]),
            hide_index=True,
        )
    else:
        st.info(
            "Der Backlog ist leer: keine zurückgestellte Anforderung, kein offener Fehler, keine "
            "offene Maßnahme, keine offene Störung."
        )

with st.container(border=True, key="panel-next-run"):
    heading("restart_alt", "Neuer Durchlauf", du="entscheidest")
    st.caption(
        "Legt vorhaben.json und projekt.json dieses Durchlaufs unter data/archiv/<Datum> ab "
        "und beginnt ein neues Vorhaben mit dem Backlog. Projektauftrag, Anforderungen und Plan "
        "entstehen dann neu."
    )
    # Test evidence can add closing warnings. Only closing errors prevent archiving.
    errors = closing.check_closing(tracking, None).errors
    if errors:
        # Each one is listed on the Abschluss, where it is decided.
        count = len(errors)
        st.error(
            f"Der Abschluss ist nicht fertig: {count} offene{'r' if count == 1 else ''} "
            f"Punkt{'' if count == 1 else 'e'}."
        )
        st.page_link("views/abschluss.py", label="Zum Abschluss", icon=":material/flag_circle:")
    state = st.session_state
    if state.get("next_run_basis") != tracking:
        state.next_run_basis = tracking
        state.next_run_sure = False
    sure = st.checkbox("Diesen Durchlauf abschließen und ins Archiv legen.", key="next_run_sure")
    start = st.button(
        "Neuen Durchlauf beginnen", icon=":material/restart_alt:", disabled=not sure or bool(errors)
    )
    if start and sure and not errors:
        try:
            with lifecycle.WRITE_LOCK, PROJECT_WRITE_LOCK:
                require_current(tracking)
                folder = closing.start_next_run(tracking, datetime.now(), DATA_DIR / "archiv")
        except InputError as err:
            st.error(as_text(str(err)))
        except OSError as err:
            st.error(
                f"Der neue Durchlauf konnte nicht beginnen: {as_text(str(err))}. Ist eine "
                "Datei in einem anderen Programm geöffnet?"
            )
        else:
            st.success(f"Archiviert unter {as_text(str(folder))}. Weiter mit dem Projektauftrag.")
            st.page_link(
                "views/auftrag.py", label="Zum Projektauftrag", icon=":material/arrow_forward:"
            )
