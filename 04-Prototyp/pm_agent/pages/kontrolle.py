"""Page "Kontrolle": plan against actual for the adopted project, and what the agent cost."""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from pm_agent import followup, workbench
from pm_agent.tracking import (
    NO_COST_INDEX,
    NO_SCHEDULE_INDEX,
    agent_runs,
    control_document,
    earned_value,
    euro,
    evaluate,
    forecast,
    forecast_bars,
    has_progress,
    hours_text,
    index_text,
    measure_effect,
    percent,
    planned_curve,
)
from pm_agent.ui import adopted_project, consent, run_with_progress

state = st.session_state


def days(count: int) -> str:
    return "Arbeitstag" if abs(count) == 1 else "Arbeitstage"


st.header("Kontrolle")
st.caption(
    "Plan und Ist im Vergleich, mit einer Bewertung von Claude. Alle Zahlen rechnet Python aus "
    "dem übernommenen Plan, dem erfassten Fortschritt und den Protokollen."
)

tracking = adopted_project()
if tracking is not None:
    result = evaluate(tracking, date.today())
    st.subheader("Projektstand")
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
    if st.button("Fortschritt erfassen", icon=":material/edit_note:"):
        st.switch_page("pages/durchfuehrung.py")

    with st.container(border=True, key="panel-forecast"):
        st.markdown("#### :material/trending_up: Prognose")
        outlook = forecast(tracking, date.today())
        if outlook.problem:
            st.error(
                f"Die Prognose lässt sich nicht berechnen: {outlook.problem}. Prüfe Status und "
                "Rest-Stunden auf der Seite Durchführung."
            )
        elif outlook.end is None:
            st.success("Alle Aufgaben sind fertig.")
        else:
            end, deadline = st.columns(2)
            end.metric(
                "Voraussichtliches Ende",
                f"{outlook.end:%d.%m.%Y}",
                # A later end is the bad direction: "inverse" paints it red.
                delta=f"{outlook.shift:+d} {days(outlook.shift)} gegenüber dem Plan"
                if outlook.shift
                else None,
                delta_color="inverse",
            )
            if outlook.deadline_gap > 0:
                deadline.metric(
                    "Deadline verpasst um",
                    f"{outlook.deadline_gap} {days(outlook.deadline_gap)}",
                )
            else:
                deadline.metric(
                    "Puffer bis zur Deadline",
                    f"{-outlook.deadline_gap} {days(outlook.deadline_gap)}",
                )
            titles = {task.id: task.title for task in tracking.plan.tasks}
            for late, waiting in outlook.blocked.items():
                held = ", ".join(waiting) if waiting else "keine weitere Aufgabe"
                st.markdown(f"- **{late} · {titles[late]}** hält auf: {held}")

            # From here the project lead can act: plan the rest again, with Claude.
            if st.button(
                "Rest mit Claude umplanen",
                icon=":material/forum:",
                type="primary" if outlook.deadline_gap > 0 else "secondary",
            ):
                state.rest_requested = True
                st.switch_page("pages/planung.py")
            st.caption(
                "Lädt die unfertigen Aufgaben als Plan ab heute in die Planung. Dort lässt er "
                "sich im Gespräch mit Claude ändern und wieder als Projekt übernehmen. Das "
                "übernommene Projekt bleibt bis dahin, wie es ist. Wird der neue Plan "
                "übernommen, ersetzt er es: Fertige Aufgaben und erfasste Stunden gehören "
                "dann nicht mehr dazu."
            )

            kinds = ["Plan", "Prognose"]
            bars = (
                alt.Chart(pd.DataFrame(forecast_bars(result, outlook)))
                .mark_bar(cornerRadius=3)
                .encode(
                    x=alt.X("Start:T", title=None, axis=alt.Axis(format="%d.%m.")),
                    x2="Ende:T",
                    y=alt.Y("Aufgabe:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
                    yOffset=alt.YOffset("Art:N", sort=kinds),
                    color=alt.Color(
                        "Art:N",
                        sort=kinds,
                        title=None,
                        scale=alt.Scale(domain=kinds, range=["#b9cdbd", "#23654c"]),
                    ),
                    tooltip=["Aufgabe", "Art", "Zeitraum"],
                )
            )
            # The forecast starts today; the deadline line sits at the end of its day.
            marks = alt.Chart(
                pd.DataFrame(
                    {
                        "Tag": [date.today(), workbench.bar_end(tracking.project.deadline)],
                        "Linie": ["Heute", "Deadline"],
                    }
                )
            )
            lines = marks.mark_rule(strokeDash=[4, 4]).encode(x="Tag:T")
            names = marks.mark_text(align="left", baseline="top", dx=4, fontSize=11).encode(
                x="Tag:T", y=alt.value(0), text="Linie:N"
            )
            # White like the panel around it; the theme would paint the page colour.
            st.altair_chart(
                (bars + lines + names).properties(background="#ffffff"), width="stretch"
            )
            st.caption(
                "Annahme: Die restliche Arbeit beginnt heute. Als Nächstes kommt, was am "
                "frühesten beginnen kann; bei Gleichstand Begonnenes vor Offenem. Eine offene "
                "Aufgabe zählt mit ihrer Schätzung, eine begonnene mit Schätzung minus "
                "Ist-Stunden; ist die Schätzung aufgebraucht, mit einer Stunde. Ein Rest, den "
                "du auf der Seite "
                "Durchführung einträgst, geht vor."
            )

    with st.container(border=True, key="panel-earned"):
        st.markdown("#### :material/monitoring: Earned Value")
        value = earned_value(tracking, result)
        # Two rows: five tiles in one row cut their labels off.
        pv, ev, ac = st.columns(3)
        pv.metric("Planwert bis heute", f"{hours_text(value.planned)} h")
        ev.metric("Fertigstellungswert", f"{hours_text(value.earned)} h")
        ac.metric("Ist-Stunden", f"{hours_text(value.actual)} h")
        spi, cpi = st.columns(2)
        spi.metric("SPI", index_text(value.schedule_index, "–"))
        cpi.metric("CPI", index_text(value.cost_index, "–"))
        if value.schedule_index is None:
            st.caption(f"SPI: {NO_SCHEDULE_INDEX}.")
        if value.cost_index is None:
            st.caption(f"CPI: {NO_COST_INDEX}.")

        kinds = ["Planwert", "Fertigstellungswert", "Ist-Stunden"]
        colour = alt.Color(
            "Wert:N",
            sort=kinds,
            title=None,
            scale=alt.Scale(domain=kinds, range=["#90ad9a", "#23654c", "#ba8d42"]),
        )
        curve = (
            alt.Chart(pd.DataFrame(planned_curve(tracking, result)).assign(Wert=kinds[0]))
            # With points: a plan of one day has no line to draw.
            .mark_line(point=True)
            .encode(
                x=alt.X("Tag:T", title=None, axis=alt.Axis(format="%d.%m.")),
                y=alt.Y("Stunden:Q", title="Stunden"),
                color=colour,
                tooltip=[
                    alt.Tooltip("Tag:T", format="%d.%m.%Y"),
                    "Wert",
                    alt.Tooltip("Stunden:Q", format=".1f"),
                ],
            )
        )
        now = (
            alt.Chart(
                pd.DataFrame(
                    {
                        "Tag": [result.today, result.today],
                        "Stunden": [value.earned, value.actual],
                        "Wert": kinds[1:],
                    }
                )
            )
            .mark_point(size=140, filled=True, opacity=1)
            .encode(
                x="Tag:T",
                y="Stunden:Q",
                color=colour,
                tooltip=[
                    alt.Tooltip("Tag:T", format="%d.%m.%Y"),
                    "Wert",
                    alt.Tooltip("Stunden:Q", format=".1f"),
                ],
            )
        )
        # White like the panel around it; the theme would paint the page colour.
        st.altair_chart((curve + now).properties(background="#ffffff"), width="stretch")
        st.caption(
            "Die Linie ist der Planwert: was laut Plan bis zum Ende jedes Tages erledigt sein "
            "sollte. Die Punkte zeigen heute. SPI ist Fertigstellungswert durch Planwert, CPI "
            "Fertigstellungswert durch Ist-Stunden; unter 1 liegt das Projekt hinter dem Plan "
            "oder braucht mehr Stunden als geplant. Gerechnet wird nach der 0/100-Methode: "
            "Eine Aufgabe zählt erst, wenn sie fertig ist, ihre Ist-Stunden zählen sofort. "
            "Mitten in einer Aufgabe wirken beide Kennzahlen deshalb schlechter als die Lage."
        )

    with st.container(border=True, key="panel-tasks"):
        st.markdown("#### :material/bar_chart: Plan und Ist je Aufgabe")
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
        bars = per_task.melt(
            id_vars="ID", value_vars=["Plan (h)", "Ist (h)"], var_name="Art", value_name="Stunden"
        )
        st.altair_chart(
            alt.Chart(bars)
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("ID:N", sort=None, title="Aufgabe"),
                xOffset=alt.XOffset("Art:N", sort=["Plan (h)", "Ist (h)"]),
                y=alt.Y("Stunden:Q"),
                color=alt.Color("Art:N", sort=["Plan (h)", "Ist (h)"], title=None),
                tooltip=["ID", "Art", "Stunden"],
            )
            # White like the panel around it; the theme would paint the page colour.
            .properties(background="#ffffff"),
            width="stretch",
        )
        st.dataframe(per_task, hide_index=True)

    with st.container(border=True, key="panel-members"):
        st.markdown("#### :material/groups: Plan und Ist je Person")
        per_member = pd.DataFrame(result.by_member)
        # Every person in this table has at least one task, so the planned hours are not zero.
        share = per_member["Fertig (Plan-h)"] / per_member["Plan (h)"]
        per_member["Erledigt"] = share.round(2)  # the column shows whole per cent
        st.dataframe(
            per_member,
            hide_index=True,
            column_config={
                "Erledigt": st.column_config.ProgressColumn(
                    format="percent", min_value=0, max_value=1
                )
            },
        )

    with st.container(border=True, key="panel-cost"):
        st.markdown("#### :material/euro: Kosten")
        rate = st.number_input(
            "Stundensatz (€)", min_value=0.0, value=None, step=5.0, placeholder="nicht gesetzt"
        )
        if rate is not None:
            plan_cost, actual_cost = st.columns(2)
            plan_cost.metric("Plankosten gesamt", euro(result.planned_hours * rate))
            actual_cost.metric("Ist-Kosten bisher", euro(result.actual_hours * rate))
        else:
            st.caption("Ohne Stundensatz werden keine Kosten berechnet.")

    with st.container(border=True, key="panel-agent"):
        st.markdown("#### :material/smart_toy: Kontroll-Agent")
        st.caption(
            "Claude bewertet den Stand und schlägt Gegenmaßnahmen vor. Python nimmt den Vorschlag "
            "nur an, wenn jede Aufgabe im Verzug eine Gegenmaßnahme hat. Was umgesetzt wird, "
            "entscheidest du."
        )
        agreed = consent("consent_kontrolle")
        if st.button(
            "Stand mit Claude bewerten", icon=":material/play_arrow:", disabled=not agreed
        ):
            proposed = run_with_progress(
                "Claude bewertet den Stand …",
                lambda on_round: followup.run_control_report(
                    tracking, date.today(), on_round=on_round
                ),
            )
            if proposed is not None:
                state.control_report = (tracking, proposed)
        if "control_report" in state:
            basis, report = state.control_report
            if basis != tracking:
                st.info(
                    "Der Fortschritt hat sich seit der Bewertung geändert. Lass sie neu erstellen."
                )
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
                                    "Erwartete Wirkung (Claude)": m.effect,
                                    "Nachgerechnet (Python)": measure_effect(
                                        tracking, date.today(), m.task_ids, m.reassign_to
                                    ),
                                }
                                for m in report.measures
                            ]
                        ),
                        hide_index=True,
                    )
                    st.caption(
                        "Gibt eine Maßnahme Aufgaben einer anderen Person, rechnet Python die "
                        "Prognose mit dieser Umverteilung neu. Andere Maßnahmen (priorisieren, "
                        "klären, Umfang ändern) lassen sich nicht nachrechnen."
                    )
                else:
                    st.caption("Claude schlägt keine Gegenmaßnahmen vor.")

if tracking is not None:
    with st.container(border=True, key="panel-document"):
        st.markdown("#### :material/description: Kontrollbericht")
        st.caption(
            "Alles von dieser Seite als ein Dokument: Kennzahlen, Prognose, Verzug, Kosten bei "
            "gesetztem Stundensatz und, wenn erstellt, die Bewertung des Kontroll-Agenten."
        )
        current = state.get("control_report")
        document = control_document(
            tracking,
            result,
            report=current[1] if current and current[0] == tracking else None,
            rate=rate,
        )
        st.download_button(
            "Kontrollbericht als Markdown herunterladen",
            document,
            file_name=f"kontrollbericht-{date.today():%Y%m%d}.md",
            mime="text/markdown",
            icon=":material/download:",
        )
        with st.container(border=True, key="preview-control"):
            st.markdown(document)

with st.container(border=True, key="panel-effort"):
    st.markdown("#### :material/timer: Aufwand der Agenten")
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
