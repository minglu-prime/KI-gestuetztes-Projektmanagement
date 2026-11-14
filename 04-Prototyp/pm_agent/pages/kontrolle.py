"""Page "Kontrolle": plan against actual for the adopted project, and what the agent cost."""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from pm_agent import followup, workbench
from pm_agent.tracking import agent_runs, evaluate, has_progress, percent
from pm_agent.ui import adopted_project, consent, run_with_progress

state = st.session_state

st.header("Kontrolle")
st.caption(
    "Plan und Ist im Vergleich, mit einer Bewertung von Claude. Alle Zahlen rechnet Python aus "
    "dem übernommenen Plan, dem erfassten Fortschritt und den Protokollen."
)

st.subheader("Projektstand")
tracking = adopted_project()
if tracking is not None:
    result = evaluate(tracking, date.today())
    if not has_progress(tracking):
        st.info("Noch kein Fortschritt erfasst. Trage ihn auf der Seite Durchführung ein.")
    a, b, c, d = st.columns(4)
    a.metric("Fortschritt", percent(result.progress))
    b.metric("Planstunden", f"{result.planned_hours:g} h")
    c.metric("Ist-Stunden bisher", f"{result.actual_hours:g} h")
    d.metric("Abweichung fertiger Aufgaben", f"{result.finished_deviation:+g} h")

    if result.overdue:
        st.warning(
            "Im Verzug:\n\n"
            + "\n".join(
                f"- {t.id} · {t.title} ({t.member}), geplant bis {t.planned_end:%d.%m.%Y}, "
                f"Status: {t.status}"
                for t in result.overdue
            )
        )
    else:
        st.success("Keine Aufgabe im Verzug.")

    st.markdown("**Plan und Ist je Aufgabe**")
    per_task = pd.DataFrame(
        [
            {
                "ID": t.id,
                "Aufgabe": t.title,
                "Person": t.member,
                "Status": t.status,
                "Geplantes Ende": t.planned_end.strftime("%d.%m.%Y"),
                "Plan (h)": t.planned_hours,
                "Ist (h)": t.actual_hours,
            }
            for t in result.tasks
        ]
    )
    st.dataframe(per_task, hide_index=True)
    bars = per_task.melt(
        id_vars="ID", value_vars=["Plan (h)", "Ist (h)"], var_name="Art", value_name="Stunden"
    )
    st.altair_chart(
        alt.Chart(bars)
        .mark_bar()
        .encode(
            x=alt.X("ID:N", sort=None, title="Aufgabe"),
            xOffset=alt.XOffset("Art:N", sort=["Plan (h)", "Ist (h)"]),
            y=alt.Y("Stunden:Q"),
            color=alt.Color("Art:N", sort=["Plan (h)", "Ist (h)"], title=None),
            tooltip=["ID", "Art", "Stunden"],
        ),
        width="stretch",
    )

    st.markdown("**Plan und Ist je Person**")
    st.dataframe(pd.DataFrame(result.by_member), hide_index=True)

    st.markdown("**Kosten**")
    rate = st.number_input(
        "Stundensatz (€)", min_value=0.0, value=None, step=5.0, placeholder="nicht gesetzt"
    )
    if rate:
        plan_cost, actual_cost = st.columns(2)
        plan_cost.metric("Plankosten gesamt", f"{result.planned_hours * rate:,.2f} €")
        actual_cost.metric("Ist-Kosten bisher", f"{result.actual_hours * rate:,.2f} €")
    else:
        st.caption("Ohne Stundensatz werden keine Kosten berechnet.")

    st.subheader("Kontroll-Agent")
    st.caption(
        "Claude bewertet den Stand und schlägt Gegenmaßnahmen vor. Python nimmt den Vorschlag nur "
        "an, wenn jede Aufgabe im Verzug eine Gegenmaßnahme hat. Was umgesetzt wird, entscheidest "
        "du."
    )
    agreed = consent("consent_kontrolle")
    if st.button("Stand mit Claude bewerten", disabled=not agreed):
        proposed = run_with_progress(
            "Claude bewertet den Stand …",
            lambda on_round: followup.run_control_report(tracking, date.today(), on_round=on_round),
        )
        if proposed is not None:
            state.control_report = (tracking, proposed)
    if "control_report" in state:
        basis, report = state.control_report
        if basis != tracking:
            st.info("Der Fortschritt hat sich seit der Bewertung geändert. Lass sie neu erstellen.")
        else:
            st.metric("Bewertung", report.assessment)
            st.markdown("**Feststellungen**")
            for finding in report.findings:
                where = f"**{', '.join(finding.task_ids)}:** " if finding.task_ids else ""
                st.markdown(f"- {where}{finding.observation}")
            st.markdown("**Gegenmaßnahmen**")
            if report.measures:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Aufgaben": ", ".join(m.task_ids),
                                "Maßnahme": m.action,
                                "Erwartete Wirkung": m.effect,
                            }
                            for m in report.measures
                        ]
                    ),
                    hide_index=True,
                )
            else:
                st.caption("Claude schlägt keine Gegenmaßnahmen vor.")

st.subheader("Aufwand der Agenten")
try:
    runs = agent_runs()
except ValueError as err:  # a damaged log file
    runs = []
    st.error(f"Protokolle in logs/ konnten nicht gelesen werden: {err}")
if runs:
    st.dataframe(pd.DataFrame(runs), hide_index=True)
    st.caption(
        "Ein Lauf ist ein Aufruf eines der drei Agenten. Token-Kosten in Euro werden nicht "
        "berechnet: Preise sind in der Anwendung nicht hinterlegt."
    )
else:
    st.caption("Noch keine protokollierten Läufe.")

st.markdown("**Exportierte Pläne**")
if workbench.RUNS_CSV.exists():
    st.dataframe(pd.read_csv(workbench.RUNS_CSV), hide_index=True)
else:
    st.caption("Noch kein Plan exportiert.")
