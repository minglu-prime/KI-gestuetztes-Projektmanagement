"""Page "Projektstand" (view "Team"): where the whole project stands, for every member.
The same numbers and the same forecast the project lead sees, without anything to change."""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from pm_agent.tracking import evaluate, forecast, load, percent
from pm_agent.ui import LEGEND, as_text, forecast_chart, heading, on_panel
from pm_agent.workbench import InputError

me = st.session_state.get("me")
st.header("Projektstand")
st.caption(
    "Wo das ganze Projekt steht: dieselben Zahlen und dieselbe Prognose, die die "
    "Projektleitung sieht. Python rechnet sie aus dem übernommenen Plan und dem Stand, den "
    "jedes Teammitglied einträgt."
)
try:
    tracking = load()
except InputError as err:
    st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {as_text(str(err))}")
    st.stop()
if tracking is None:
    st.info(
        "Noch kein Projekt übernommen. Sobald die Projektleitung einen Plan übernimmt, "
        "steht er hier."
    )
    st.stop()

result = evaluate(tracking, date.today())
outlook = forecast(tracking, date.today())
st.markdown(f"**{as_text(tracking.project.idea)}**")
a, b, c, d = st.columns(4)
a.metric("Aufgaben", len(result.tasks))
b.metric("Fortschritt", percent(result.progress))
c.metric("Im Verzug", len(result.overdue))
d.metric(
    "Voraussichtliches Ende",
    f"{outlook.end:%d.%m.%Y}" if outlook.end else ("–" if outlook.problem else "fertig"),
)
st.caption(f"Deadline: {tracking.project.deadline:%d.%m.%Y}")

with st.container(border=True, key="panel-people"):
    heading("group", "Wer wie weit ist", python="rechnet")
    kinds = ["fertig", "in Arbeit", "offen"]
    rows = pd.DataFrame(
        [
            {
                "Person": f"{t.member} (du)" if t.member == me else t.member,
                "Status": t.status,
                "Stunden": t.planned_hours,
            }
            for t in result.tasks
        ]
    )
    st.altair_chart(
        on_panel(
            alt.Chart(rows)
            .mark_bar(cornerRadius=3)
            .encode(
                x=alt.X("sum(Stunden):Q", title="Geplante Stunden"),
                y=alt.Y("Person:N", title=None),
                color=alt.Color(
                    "Status:N",
                    sort=kinds,
                    legend=LEGEND,
                    scale=alt.Scale(domain=kinds, range=["#23654c", "#ba8d42", "#d5dccf"]),
                ),
                tooltip=["Person", "Status", alt.Tooltip("sum(Stunden):Q", title="Stunden")],
            ),
            "Balkendiagramm: je Person die geplanten Stunden ihrer Aufgaben, geteilt nach "
            "fertig, in Arbeit und offen.",
        ),
        width="stretch",
    )

with st.container(border=True, key="panel-outlook"):
    heading("event", "Plan und Prognose", python="plant den Rest ab heute neu ein")
    if outlook.problem:
        st.caption(f"Keine Prognose: {as_text(outlook.problem)}")
    elif outlook.end is None:
        st.caption("Alle Aufgaben sind fertig.")
    else:
        st.altair_chart(forecast_chart(tracking, result, outlook), width="stretch")
