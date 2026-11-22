"""Page "Startseite": what the site offers and where the current project stands."""

from datetime import date

import streamlit as st

from pm_agent.tracking import evaluate, forecast, load, next_step, percent
from pm_agent.ui import JOURNEY, PAGES, as_text, forecast_verdict, heading, verdict
from pm_agent.workbench import InputError

# How every agent works, as the diagram next to the headline (styled in assets/style.css).
FLOW = """
<div class="flow">
  <div class="flow-top"><span>SO ARBEITET JEDER AGENT</span><span>01 – 03</span></div>
  <div class="flow-nodes">
    <div class="flow-node"><strong>1</strong><span class="role agent"><b>AGENT</b></span>
      schlägt vor</div>
    <div class="flow-node"><strong>2</strong><span class="role python"><b>PYTHON</b></span>
      prüft nach</div>
    <div class="flow-node"><strong>3</strong><span class="role du"><b>DU</b></span>
      entscheidest</div>
  </div>
  <div class="flow-result">
    Kein Ergebnis ohne deterministische Prüfung. Was sie ablehnt, geht mit Begründung zurück
    an den Agenten. Auf jeder Agentenseite zeigen diese drei Marken, wer gerade handelt.
  </div>
</div>
"""

with st.container(key="hero"):
    words, diagram = st.columns([3, 2], gap="large", vertical_alignment="center")
    with words:
        st.title("Der Agent schlägt vor. *Du entscheidest.*")
        st.html(
            '<p class="lead">Diese Seite zeigt an einem Softwareprojekt, welche Aufgaben des '
            "Projektmanagements ein KI-Agent übernehmen kann: vom Projektauftrag über Planung, "
            "Durchführung und Kontrolle bis zur nächsten Iteration.</p>"
        )
        with st.container(horizontal=True):
            if st.button("Projekt planen", type="primary", icon=":material/arrow_forward:"):
                st.switch_page("views/planung.py")
            if st.button("KI-Lab öffnen", icon=":material/science:"):
                st.switch_page("views/ki_lab.py")
    diagram.html(FLOW)

with st.container(key="project"):
    st.subheader("Aktuelles Projekt")
    try:
        tracking = load()
    except InputError as err:
        tracking = None
        st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {as_text(str(err))}")
    else:
        if tracking is None:
            st.info("Noch kein Projekt übernommen.")
            st.caption(
                "Erstelle einen Plan auf der Seite Planung und übernimm ihn dort im Schritt "
                "Übernehmen."
            )
        else:
            result = evaluate(tracking, date.today())
            st.markdown(f"**{as_text(tracking.project.idea)}**")
            outlook = forecast(tracking, date.today())
            verdict(*forecast_verdict(outlook, tracking.project.deadline, result))
            a, b, c = st.columns(3)
            a.metric("Aufgaben", len(result.tasks))
            b.metric("Fortschritt", percent(result.progress))
            c.metric("Im Verzug", len(result.overdue))
            advice, where = next_step(tracking, date.today())
            # Advice for the Kontrolle repeats the forecast or the delay shown above.
            if where != "kontrolle":
                st.markdown(f"**Als Nächstes:** {as_text(advice)}")
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
                # Only when open defects are what is next: then they block the end.
                if where == "testlauf" and st.button(
                    "Fehler beheben", icon=":material/bug_report:", type="primary"
                ):
                    st.switch_page("views/testlauf.py")

with st.container(key="lifecycle"):
    st.subheader("Der ganze Ablauf")
    st.caption(
        "Alle Schritte in der Reihenfolge des Projektpfads. Schritte vor der Planung dürfen "
        "übersprungen werden."
    )
    with st.container(horizontal=True, key="steps"):
        for number, (key, name, hint) in enumerate(JOURNEY, start=1):
            with st.container(border=True, key=f"tile-{key}"):
                st.html(f'<p class="card-number">{number:02d}</p>')
                st.page_link(PAGES[key][0], label=name)
                st.caption(hint)

with st.container(key="lab"):
    with st.container(border=True, key="card-lab"):
        heading("science", "KI-Lab")
        st.write(
            "Kontrollierter Vergleich: dieselbe Art von Planungsaufgabe einmal ohne und einmal "
            "mit KI-Hilfe, mit Zeitlimit und Protokoll."
        )
        st.page_link("views/ki_lab.py", label="KI-Lab öffnen", icon=":material/arrow_forward:")
