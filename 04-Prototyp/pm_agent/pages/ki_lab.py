"""Page "KI-Lab": runs the study server from 04-Prototyp/ki_lab and shows it in a frame."""

from urllib.parse import urlsplit

import streamlit as st

from pm_agent import lab_server
from pm_agent.lab_server import LabError

st.header("KI-Lab")
st.caption(
    "Kontrollierter Vergleich: zwei Planungsfälle, einer ohne und einer mit KI-Hilfe, je "
    "25 Minuten, mit Protokoll. Das Lab ist ein eigenes Programm (04-Prototyp/ki_lab) und wird "
    "hier eingebettet."
)

# The lab accepts frames only from pages on this computer, named with their port.
here = urlsplit(st.context.url)
origin = f"{here.scheme}://{here.netloc}"
lab_url = f"http://{here.hostname}:{lab_server.PORT}/"

try:
    status = lab_server.health(lab_server.PORT)
except LabError as err:
    st.error(str(err))
    st.stop()

if status is None:
    st.info("Das KI-Lab läuft noch nicht.")
    if st.button("KI-Lab starten", type="primary"):
        try:
            with st.spinner("KI-Lab startet …"):
                lab_server.start([origin], lab_server.PORT)
        except LabError as err:
            st.error(str(err))
            st.stop()
        st.rerun()
    st.stop()

left, middle, right = st.columns(3)
left.metric("KI konfiguriert", "ja" if status["ai_configured"] else "nein")
middle.metric("Modell", status["model"] or "–")
right.metric("Fallversion", status["case_version"])
if not status["ai_configured"]:
    st.warning(
        "OPENAI_API_KEY und PM_MODEL sind nicht gesetzt. Runden ohne KI funktionieren. In "
        "KI-Runden meldet das Lab einen Fehler; es gibt keine Demo-Antworten."
    )

open_tab, stop = st.columns([1, 4])
open_tab.link_button("In neuem Tab öffnen", lab_url)
if lab_server.started_here():
    stop.button("KI-Lab stoppen", on_click=lab_server.stop)

try:
    framed = lab_server.allows_frame(origin, lab_server.PORT)
except OSError as err:
    st.error(f"Das KI-Lab antwortet nicht mehr: {err}")
    st.stop()
if framed:
    st.iframe(lab_url, height=900)
else:
    st.info(
        "Dieses Lab wurde ohne Einbettung gestartet und lässt sich hier nicht anzeigen. Öffne es "
        "in einem neuen Tab, oder beende es und starte es über diese Seite."
    )

st.caption(
    "Daten: Sitzungen und Antworten liegen lokal in 04-Prototyp/ki_lab/data/lab.db und nicht im "
    "Repository. In KI-Runden gehen Fallmaterial, Entwurf und Frage an OpenAI; das Lab fragt "
    "vorher nach der Einwilligung."
)
