"""Page "Startseite": what the site offers and where the current project stands."""

from datetime import date

import streamlit as st

from pm_agent.tracking import evaluate, forecast, forecast_text, load, next_step, percent
from pm_agent.ui import heading
from pm_agent.workbench import InputError

# How every agent works, as the diagram next to the headline (styled in assets/style.css).
FLOW = """
<div class="flow">
  <div class="flow-top"><span>SO ARBEITET JEDER AGENT</span><span>01 – 03</span></div>
  <div class="flow-nodes">
    <div class="flow-node"><strong>1</strong>Claude schlägt vor</div>
    <div class="flow-node"><strong>2</strong>Python prüft nach</div>
    <div class="flow-node"><strong>3</strong>Du entscheidest</div>
  </div>
  <div class="flow-result">
    Kein Ergebnis ohne deterministische Prüfung. Was sie ablehnt, geht mit Begründung zurück
    an Claude.
  </div>
</div>
"""

AGENTS = [
    (
        "planung",
        "view_timeline",
        "Planung",
        "Aus Projektidee und Team entsteht ein geprüfter Plan: Aufgaben, Aufwand, Zuweisung, "
        "Termine und Risiken. Claude plant, die Projektleitung passt an.",
        "views/planung.py",
    ),
    (
        "durchfuehrung",
        "task_alt",
        "Durchführung",
        "Fortschritt und Ist-Stunden je Aufgabe erfassen. Claude schlägt Zusammenfassung und "
        "nächste Schritte vor. Statusbericht und Arbeitspaketbeschreibungen werden aus Vorlagen "
        "gefüllt.",
        "views/durchfuehrung.py",
    ),
    (
        "kontrolle",
        "monitoring",
        "Kontrolle",
        "Plan und Ist vergleichen: Fortschritt, Abweichung, Verzug, Kosten bei gesetztem "
        "Stundensatz. Claude bewertet den Stand und schlägt Gegenmaßnahmen vor. Dazu der "
        "Aufwand der Agenten.",
        "views/kontrolle.py",
    ),
]

with st.container(key="hero"):
    words, diagram = st.columns([3, 2], gap="large", vertical_alignment="center")
    with words:
        st.html('<p class="eyebrow">KI im Projektmanagement · Prototyp</p>')
        st.title("Der Agent schlägt vor. *Du entscheidest.*")
        st.html(
            '<p class="lead">Diese Seite zeigt an einem Softwareprojekt, welche Aufgaben des '
            "Projektmanagements ein KI-Agent übernehmen kann: Planung, Durchführung und "
            "Kontrolle.</p>"
        )
        with st.container(horizontal=True):
            if st.button("Projekt planen", type="primary", icon=":material/arrow_forward:"):
                st.switch_page("views/planung.py")
            if st.button("KI-Lab öffnen", icon=":material/science:"):
                st.switch_page("views/ki_lab.py")
    diagram.html(FLOW)

with st.container(key="agents"):
    st.subheader("Agenten")
    columns = st.columns(3)
    for number, (column, agent) in enumerate(zip(columns, AGENTS, strict=True), start=1):
        slug, icon, title, text, target = agent
        with column.container(border=True, key=f"card-{slug}", height="stretch"):
            st.html(f'<p class="card-number">0{number} · AGENT</p>')
            heading(icon, title)
            st.write(text)
            st.page_link(target, label=f"{title} öffnen", icon=":material/arrow_forward:")

with st.container(key="lab"):
    st.subheader("Experiment")
    with st.container(border=True, key="card-lab"):
        st.html('<p class="card-number">VERGLEICH OHNE UND MIT KI</p>')
        heading("science", "KI-Lab")
        st.write(
            "Kontrollierter Vergleich: dieselbe Art von Planungsaufgabe einmal ohne und einmal "
            "mit KI-Hilfe, mit Zeitlimit und Protokoll."
        )
        st.page_link("views/ki_lab.py", label="KI-Lab öffnen", icon=":material/arrow_forward:")

with st.container(key="project"):
    st.subheader("Aktuelles Projekt")
    try:
        tracking = load()
    except InputError as err:
        tracking = None
        st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {err}")
    else:
        if tracking is None:
            st.info("Noch kein Projekt übernommen.")
            st.caption(
                "Erstelle einen Plan auf der Seite Planung und übernimm ihn dort im Schritt Export."
            )
        else:
            result = evaluate(tracking, date.today())
            st.markdown(f"**{tracking.project.idea}**")
            st.progress(result.progress, text=f"{percent(result.progress)} der Planstunden fertig")
            a, b, c = st.columns(3)
            a.metric("Aufgaben", len(result.tasks))
            b.metric("Fortschritt", percent(result.progress))
            c.metric("Im Verzug", len(result.overdue))
            outlook = forecast(tracking, date.today())
            heading = forecast_text(outlook, tracking.project.deadline).rstrip(".")
            if outlook.problem:
                st.error(f"Prognose: {heading}.")
            elif outlook.deadline_gap > 0:
                st.warning(f"Prognose: {heading}.")
            else:
                st.caption(f"Prognose: {heading}.")
            advice, where = next_step(tracking, date.today())
            st.markdown(f"**Als Nächstes:** {advice}")
            # The button for the page the advice points to is the primary one.
            with st.container(horizontal=True):
                if st.button(
                    "Fortschritt erfassen",
                    icon=":material/task_alt:",
                    type="primary" if where == "durchfuehrung" else "secondary",
                ):
                    st.switch_page("views/durchfuehrung.py")
                if st.button(
                    "Stand prüfen",
                    icon=":material/monitoring:",
                    type="primary" if where == "kontrolle" else "secondary",
                ):
                    st.switch_page("views/kontrolle.py")
