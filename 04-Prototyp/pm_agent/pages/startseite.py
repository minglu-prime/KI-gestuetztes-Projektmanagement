"""Page "Startseite": what the site offers and where the current project stands."""

from datetime import date

import streamlit as st

from pm_agent.tracking import evaluate, load, percent
from pm_agent.workbench import InputError

st.header("Startseite")
st.markdown(
    "Diese Seite zeigt an einem Beispiel, welche Aufgaben des Projektmanagements ein KI-Agent "
    "übernehmen kann. Der Agent schlägt vor, Python prüft deterministisch nach, die "
    "Projektleitung entscheidet."
)

st.subheader("Agenten")
cards = [
    (
        "Planung",
        "Aus Projektidee und Team entsteht ein geprüfter Plan: Aufgaben, Aufwand, Zuweisung, "
        "Termine und Risiken. Claude plant, die Projektleitung passt an.",
        "pages/planung.py",
    ),
    (
        "Durchführung",
        "Fortschritt und Ist-Stunden je Aufgabe erfassen. Statusbericht und "
        "Arbeitspaketbeschreibungen werden aus Vorlagen gefüllt. Noch ohne LLM.",
        "pages/durchfuehrung.py",
    ),
    (
        "Kontrolle",
        "Plan und Ist vergleichen: Fortschritt, Abweichung, Verzug, Kosten bei gesetztem "
        "Stundensatz und der Aufwand des Planungsagenten. Noch ohne LLM.",
        "pages/kontrolle.py",
    ),
]
for column, (title, text, target) in zip(st.columns(3), cards, strict=True):
    with column.container(border=True):
        st.markdown(f"**{title}**")
        st.write(text)
        st.page_link(target, label="Öffnen", icon=":material/arrow_forward:")

st.subheader("Experiment")
with st.container(border=True):
    st.markdown("**KI-Lab**")
    st.write(
        "Kontrollierter Vergleich: dieselbe Art von Planungsaufgabe einmal ohne und einmal mit "
        "KI-Hilfe, mit Zeitlimit und Protokoll."
    )
    st.page_link("pages/ki_lab.py", label="Öffnen", icon=":material/arrow_forward:")

st.subheader("Aktuelles Projekt")
try:
    tracking = load()
except InputError as err:
    tracking = None
    st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {err}")
else:
    if tracking is None:
        st.info("Noch kein Projekt übernommen.")
    else:
        result = evaluate(tracking, date.today())
        st.markdown(f"**{tracking.project.idea}**")
        a, b, c = st.columns(3)
        a.metric("Aufgaben", len(result.tasks))
        b.metric("Fortschritt", percent(result.progress))
        c.metric("Im Verzug", len(result.overdue))
