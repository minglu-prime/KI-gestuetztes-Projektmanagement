"""Page "Über uns": the project context. No member names: the repository is public."""

import streamlit as st

st.header("Über uns")
st.markdown(
    """
Diese Website ist der Prototyp der **Projektgruppe 4** im Modul IPM an der Hochschule
Bielefeld (HSBI), Thema 4: **KI im Projektmanagement**.

**Fragestellung:** Welche Aufgaben des klassischen Projektmanagements kann ein KI-Agent
übernehmen, und was ändert sich dadurch? Chancen und Risiken zeigen wir an einem konkreten
Beispiel.

**Was die Website enthält**

- **Agenten:** Planung mit Claude und deterministischer Prüfung; Durchführung und Kontrolle als
  erste Fassung ohne LLM.
- **KI-Lab:** kontrollierter Vergleich derselben Art von Planungsaufgabe ohne und mit KI-Hilfe.

**Grundsätze**

- Die KI schlägt vor, die Projektleitung entscheidet.
- Rechnen und Prüfen übernimmt Python, nicht das Sprachmodell.
- Teamdaten und Protokolle bleiben lokal und stehen nicht im Repository.
"""
)
st.link_button(
    "Quellcode auf GitHub", "https://github.com/minglu-prime/KI-gestuetztes-Projektmanagement"
)
st.caption("Die Namen der Teammitglieder stehen hier erst, wenn alle zugestimmt haben.")
