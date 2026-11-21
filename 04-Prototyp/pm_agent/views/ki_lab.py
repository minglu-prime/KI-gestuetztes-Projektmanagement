"""Page "KI-Lab": runs the study server from 04-Prototyp/ki_lab and shows it in a frame."""

from urllib.parse import urlsplit

import streamlit as st

from pm_agent import lab_server
from pm_agent.lab_server import LabError
from pm_agent.ui import ai_service, as_text, heading

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
    # Nothing listening can take two seconds to tell on Windows: the page said nothing meanwhile.
    with st.spinner("Prüfe, ob das KI-Lab läuft …"):
        status = lab_server.health(lab_server.PORT)
except LabError as err:
    st.error(str(err))
    st.stop()

if status is None:
    with st.container(border=True, key="panel-lab-start"):
        heading("science", "Eine Sitzung im KI-Lab")
        st.markdown(
            """
1. Du bearbeitest zwei Planungsfälle, jeden höchstens 25 Minuten.
2. Einen ohne KI-Hilfe, einen mit: Dort beantwortet ein Sprachmodell deine Fragen zum Fall.
3. Das Lab protokolliert die Sitzung für die Auswertung.
"""
        )
        st.info("Das KI-Lab läuft noch nicht.")
        if st.button("KI-Lab starten", type="primary", icon=":material/play_arrow:"):
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

with st.container(horizontal=True):
    st.link_button("In neuem Tab öffnen", lab_url, icon=":material/open_in_new:")
    if lab_server.started_here():
        st.button("KI-Lab stoppen", icon=":material/stop:", on_click=lab_server.stop)

try:
    framed = lab_server.allows_frame(origin, lab_server.PORT)
except OSError as err:
    st.error(f"Das KI-Lab antwortet nicht mehr: {as_text(str(err))}")
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
    f"Repository. In KI-Runden gehen Fallmaterial, Entwurf und Frage an {ai_service()}; das Lab "
    "fragt vorher nach der Einwilligung."
)
