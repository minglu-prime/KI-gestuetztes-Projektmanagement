"""Page "Impressum": what can be said today. The legal details are for the team to fill in."""

import streamlit as st

st.header("Impressum")
with st.container(border=True, key="panel-impressum"):
    st.markdown(
        """
Studentisches Projekt der Projektgruppe 4 im Modul IPM an der Hochschule Bielefeld (HSBI).
Kein kommerzielles Angebot.

Die Anwendung läuft nur auf dem eigenen Rechner (`localhost`) und ist nicht öffentlich
erreichbar.
"""
    )
st.warning(
    "Angaben fehlen noch: verantwortliche Person und Anschrift. Das Team trägt sie ein, bevor "
    "die Website öffentlich erreichbar gemacht wird."
)
