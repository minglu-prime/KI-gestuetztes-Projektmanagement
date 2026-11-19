"""Page "Über uns": the project context. No member names: the repository is public."""

import streamlit as st

from pm_agent.ui import heading

PRINCIPLES = [
    (
        "vorschlag",
        "smart_toy",
        "Die KI schlägt vor",
        "Claude zerlegt, schätzt, verteilt und begründet. Jedes Ergebnis kommt über ein Werkzeug "
        "mit festem Format, nie als freier Text.",
    ),
    (
        "pruefung",
        "fact_check",
        "Python rechnet und prüft",
        "Termine, Auslastung, Puffer, Verzug und Prognose rechnet Python. Was die Prüfung "
        "ablehnt, geht mit den Gründen zurück an Claude.",
    ),
    (
        "entscheidung",
        "how_to_reg",
        "Der Mensch entscheidet",
        "Ein Plan gilt erst, wenn die Projektleitung ihn übernimmt. Warnungen bleiben stehen, "
        "bis sie jemand gesehen hat.",
    ),
]

st.header("Über uns")
st.markdown(
    "Diese Website ist der Prototyp der **Projektgruppe 4** im Modul IPM an der Hochschule "
    "Bielefeld (HSBI), Thema 4: **KI im Projektmanagement**."
)
with st.container(border=True, key="panel-frage"):
    st.html('<p class="card-number">FRAGESTELLUNG</p>')
    st.markdown(
        "#### Welche Aufgaben des klassischen Projektmanagements kann ein KI-Agent "
        "übernehmen, und was ändert sich dadurch?"
    )
    st.markdown(
        "Chancen und Risiken zeigen wir an einem konkreten Beispiel: einem Softwareprojekt."
    )

st.subheader("Grundsätze")
for column, (slug, icon, title, text) in zip(st.columns(3), PRINCIPLES, strict=True):
    with column.container(border=True, key=f"panel-{slug}", height="stretch"):
        heading(icon, title)
        st.write(text)

st.subheader("Was die Website enthält")
st.markdown(
    """
- **Vorbereiten:** Projektauftrag, Anforderungen, Entwurf und Testplan. Claude entwirft,
  Python prüft, dass nichts fehlt, die Projektleitung gibt frei.
- **Agenten:** Planung, Durchführung, Test, Kontrolle, Abschluss, Betrieb und Iteration: vom
  geprüften Plan über Fortschritt und Prognose bis zum Backlog der nächsten Runde.
- **KI-Lab:** kontrollierter Vergleich derselben Art von Planungsaufgabe ohne und mit KI-Hilfe.

Teamdaten und Protokolle bleiben lokal und stehen nicht im Repository.
"""
)
st.link_button(
    "Quellcode auf GitHub",
    "https://github.com/minglu-prime/KI-gestuetztes-Projektmanagement",
    icon=":material/code:",
)
st.caption("Die Namen der Teammitglieder stehen hier erst, wenn alle zugestimmt haben.")
