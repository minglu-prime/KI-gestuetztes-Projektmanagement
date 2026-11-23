"""Page "Kontrolle": plan against actual for the adopted project, and what the agent cost."""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from pm_agent import followup, lifecycle, workbench
from pm_agent.tracking import (
    NO_COST_INDEX,
    NO_SCHEDULE_INDEX,
    Retro,
    agent_runs,
    check_retros,
    control_document,
    demo_mondays,
    demo_status,
    earned_value,
    euro,
    evaluate,
    forecast,
    forecast_bars,
    has_progress,
    hours_text,
    index_text,
    measure_effect,
    open_measures,
    percent,
    planned_curve,
    quality_summary,
    record_retro,
    requirement_progress,
    save_if_current,
    signed_hours,
)
from pm_agent.ui import (
    LEGEND,
    TASK_AXIS,
    adopted_project,
    as_text,
    consent,
    forecast_verdict,
    heading,
    history_table,
    messages,
    on_panel,
    roles,
    run_with_progress,
    verdict,
)
from pm_agent.workbench import InputError

state = st.session_state


def days(count: int) -> str:
    return "Arbeitstag" if abs(count) == 1 else "Arbeitstage"


st.header("Kontrolle")
st.caption(
    "Plan und Ist im Vergleich, mit einer Bewertung vom Agenten. Alle Zahlen rechnet Python aus "
    "dem übernommenen Plan, dem erfassten Fortschritt und den Protokollen."
)

tracking = adopted_project()
if tracking is not None:
    result = evaluate(tracking, date.today())
    outlook = forecast(tracking, date.today())
    verdict(*forecast_verdict(outlook, tracking.project.deadline, result))
    st.subheader("Projektstand")
    st.html(roles(python="rechnet aus Plan und Fortschritt"))
    if not has_progress(tracking):
        st.info("Noch kein Fortschritt erfasst. Trage ihn auf der Seite Durchführung ein.")
    a, b, c, d = st.columns(4)
    a.metric("Fortschritt", percent(result.progress))
    b.metric("Planstunden", f"{hours_text(result.planned_hours)} h")
    c.metric("Ist-Stunden bisher", f"{hours_text(result.actual_hours)} h")
    d.metric("Abweichung fertiger Aufgaben", f"{signed_hours(result.finished_deviation)} h")

    if result.overdue:
        st.warning(
            "Im Verzug:\n\n"
            + "\n".join(
                f"- {as_text(t.id)} · {as_text(t.title)} ({as_text(t.member)}), geplant bis "
                f"{t.planned_end:%d.%m.%Y}, "
                f"Status: {t.status}"
                for t in result.overdue
            )
        )
    else:
        st.success("Keine Aufgabe im Verzug.")
    if st.button("Fortschritt erfassen", icon=":material/edit_note:"):
        st.switch_page("views/durchfuehrung.py")

    with st.container(border=True, key="panel-forecast"):
        heading("trending_up", "Prognose", python="rechnet")
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
            # The late tasks themselves stand in the box "Im Verzug" above.
            holding = {late: waiting for late, waiting in outlook.blocked.items() if waiting}
            if holding:
                st.markdown(
                    "**Verspätet und halten andere auf:**\n"
                    + "\n".join(
                        f"- **{as_text(late)} · {as_text(titles[late])}**: "
                        f"{as_text(', '.join(waiting))}"
                        for late, waiting in holding.items()
                    )
                )

            # From here the project lead can act: plan the rest again, with the agent.
            if st.button(
                "Rest mit dem Agenten umplanen",
                icon=":material/forum:",
                type="primary" if outlook.deadline_gap > 0 else "secondary",
            ):
                state.rest_requested = True
                st.switch_page("views/planung.py")
            st.caption(
                "Lädt die unfertigen Aufgaben als Plan ab heute in die Planung. Dort lässt er "
                "sich im Gespräch mit dem Agenten ändern und wieder als Projekt übernehmen. Das "
                "übernommene Projekt bleibt bis dahin, wie es ist. Beim Übernehmen entscheidest "
                "du, ob fertige Aufgaben und erfasste Stunden als frühere Arbeit bleiben."
            )

            kinds = ["Plan", "Prognose"]
            bars = (
                alt.Chart(pd.DataFrame(forecast_bars(result, outlook)))
                .mark_bar(cornerRadius=3)
                .encode(
                    x=alt.X("Start:T", title=None, axis=alt.Axis(format="%d.%m.")),
                    x2="Ende:T",
                    y=alt.Y("Aufgabe:N", sort=None, title=None, axis=TASK_AXIS),
                    yOffset=alt.YOffset("Art:N", sort=kinds),
                    color=alt.Color(
                        "Art:N",
                        sort=kinds,
                        legend=LEGEND,
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
            st.altair_chart(
                on_panel(
                    bars + lines + names,
                    "Balkendiagramm: je unfertiger Aufgabe der Zeitraum laut Plan und der "
                    "Zeitraum laut Prognose, mit senkrechten Linien für heute und die "
                    "Deadline. Die Prognose je Aufgabe steht auch in der Spalte „Prognose "
                    "Ende“ auf der Seite Durchführung.",
                ),
                width="stretch",
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
        heading("monitoring", "Earned Value", python="rechnet")
        value = earned_value(tracking, result)
        # Two rows: five tiles in one row cut their labels off.
        pv, ev, ac = st.columns(3)
        pv.metric("Planwert bis heute", f"{hours_text(value.planned)} h")
        ev.metric("Fertigstellungswert", f"{hours_text(value.earned)} h")
        ac.metric("Ist-Stunden", f"{hours_text(value.actual)} h")
        spi, cpi = st.columns(2)
        # The names of the Kontrollbericht: the short form alone means nothing to most.
        spi.metric("Termin-Kennzahl (SPI)", index_text(value.schedule_index, "–"))
        cpi.metric("Aufwands-Kennzahl (CPI)", index_text(value.cost_index, "–"))
        if value.schedule_index is None:
            st.caption(f"SPI: {NO_SCHEDULE_INDEX}.")
        if value.cost_index is None:
            st.caption(f"CPI: {NO_COST_INDEX}.")

        kinds = ["Planwert", "Fertigstellungswert", "Ist-Stunden"]
        colour = alt.Color(
            "Wert:N",
            sort=kinds,
            legend=LEGEND,
            scale=alt.Scale(domain=kinds, range=["#90ad9a", "#23654c", "#ba8d42"]),
        )
        curve = (
            alt.Chart(pd.DataFrame(planned_curve(tracking)).assign(Wert=kinds[0]))
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
        st.altair_chart(
            on_panel(
                curve + now,
                "Liniendiagramm: der Planwert in Stunden über die Tage des Projekts, dazu "
                "als Punkte Fertigstellungswert und Ist-Stunden von heute. Die Werte von "
                "heute stehen in den Kacheln darüber.",
            ),
            width="stretch",
        )
        st.caption(
            "Die Linie ist der Planwert: was laut Plan bis zum Ende jedes Tages erledigt sein "
            "sollte. Die Punkte zeigen heute. SPI ist Fertigstellungswert durch Planwert, CPI "
            "Fertigstellungswert durch Ist-Stunden; unter 1 liegt das Projekt hinter dem Plan "
            "oder braucht mehr Stunden als geplant. Gerechnet wird nach der 0/100-Methode: "
            "Eine Aufgabe zählt erst, wenn sie fertig ist, ihre Ist-Stunden zählen sofort. "
            "Mitten in einer Aufgabe wirken beide Kennzahlen deshalb schlechter als die Lage."
        )

    with st.container(border=True, key="panel-tasks"):
        heading("bar_chart", "Plan und Ist je Aufgabe", python="rechnet")
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
            on_panel(
                alt.Chart(bars)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("ID:N", sort=None, title="Aufgabe"),
                    xOffset=alt.XOffset("Art:N", sort=["Plan (h)", "Ist (h)"]),
                    y=alt.Y("Stunden:Q"),
                    color=alt.Color("Art:N", sort=["Plan (h)", "Ist (h)"], legend=LEGEND),
                    tooltip=["ID", "Art", "Stunden"],
                ),
                "Säulendiagramm: je Aufgabe die geplanten und die erfassten Stunden "
                "nebeneinander. Dieselben Zahlen stehen in der Tabelle darunter.",
            ),
            width="stretch",
        )
        st.dataframe(per_task, hide_index=True)
        if tracking.history:
            st.caption(
                "Nur die Aufgaben des aktuellen Plans. Die Stunden früherer Pläne stehen "
                "darunter; die Kennzahlen oben zählen beides."
            )
        history_table(tracking)

    with st.container(border=True, key="panel-members"):
        heading("groups", "Plan und Ist je Person", python="rechnet")
        per_member = pd.DataFrame(result.by_member)
        # A person with only a part from an earlier plan whose booked hours stood for none
        # of its estimate has 0 planned hours: nothing to show a share of.
        planned = per_member["Plan (h)"].where(per_member["Plan (h)"] > 0)
        per_member["Erledigt"] = (per_member["Fertig (Plan-h)"] / planned).round(2)
        st.dataframe(
            per_member,
            hide_index=True,
            column_config={
                "Erledigt": st.column_config.ProgressColumn(
                    format="percent", min_value=0, max_value=1
                )
            },
        )

    with st.container(border=True, key="panel-requirements"):
        heading("checklist", "Plan und Ist je Anforderung", python="rechnet")
        if tracking.requirements:
            st.dataframe(pd.DataFrame(requirement_progress(tracking)), hide_index=True)
            st.caption(
                "Die Anforderungen, mit denen der Plan übernommen wurde. Mitgezählt sind "
                "fertige Aufgaben früherer Pläne."
            )
        else:
            st.caption(
                "Der Plan wurde ohne freigegebene Anforderungen übernommen: Es gibt keinen "
                "Stand je Anforderung. Gib sie auf der Seite Anforderungen frei und übernimm "
                "den Plan erneut."
            )

    with st.container(border=True, key="panel-quality"):
        heading("bug_report", "Test und Fehler", python="zählt")
        try:
            plan_of_tests = lifecycle.case_plan(lifecycle.load())
        except InputError as err:
            plan_of_tests = None
            st.caption(f"Der Testplan ist nicht lesbar: {as_text(str(err))}")
        if plan_of_tests is None:
            st.caption("Noch kein Testplan. Lege ihn auf der Seite Testplan an.")
        else:
            figures = quality_summary(tracking, plan_of_tests)
            for column, (label, value) in zip(st.columns(3), figures.items(), strict=True):
                column.metric(label, value)
            st.page_link("views/testlauf.py", label="Zum Test", icon=":material/arrow_forward:")

    with st.container(border=True, key="panel-retro"):
        heading(
            "slideshow",
            "Wochen-Demos und Rückblick",
            python="zählt, was fertig ist",
            du="trägst ein, was gezeigt wurde",
        )
        if not tracking.plan.demos:
            st.caption(
                "Der Plan hat keine Wochen-Demos. Bitte den Agenten in der Planung darum, zum "
                "Beispiel "
                "„Plane für jede Woche eine Demo“, und übernimm den Plan erneut."
            )
        else:
            st.caption(
                "Jede Woche ein Ergebnis, das sich vorführen lässt, und danach ein kurzer "
                "Rückblick: Was wurde gezeigt, was ging schief, warum, und was ändern wir? "
                "Fand eine Demo nicht oder nur teilweise statt, braucht der Rückblick eine "
                "Maßnahme."
            )
            st.dataframe(pd.DataFrame(demo_status(tracking, date.today())), hide_index=True)
            messages([], check_retros(tracking, date.today()).warnings)
            titles = {d.week: d.title for d in tracking.plan.demos}
            mondays = demo_mondays(tracking)
            earlier = {r.monday: r for r in tracking.retros}
            week = st.selectbox(
                "Rückblick für",
                sorted(titles),
                format_func=lambda w: f"Woche {w} · {titles[w]}",
                key="retro_week",
            )
            was = earlier.get(mondays.get(week))
            shown = st.radio(
                "Demo gezeigt?",
                ["ja", "teilweise", "nein"],
                index=["ja", "teilweise", "nein"].index(was.shown) if was else 0,
                horizontal=True,
                key=f"retro_shown_{week}",
            )
            wrong = st.text_input(
                "Was ging schief?", value=was.went_wrong if was else "", key=f"retro_wrong_{week}"
            )
            cause = st.text_input(
                "Vermutete Ursache", value=was.cause if was else "", key=f"retro_cause_{week}"
            )
            measure = st.text_input(
                "Maßnahme", value=was.measure if was else "", key=f"retro_measure_{week}"
            )
            if st.button("Rückblick speichern", icon=":material/save:"):
                retro = Retro(
                    monday=mondays[week],
                    shown=shown,
                    went_wrong=wrong,
                    cause=cause,
                    measure=measure,
                    measure_done=was.measure_done if was and was.measure == measure else False,
                )
                try:
                    updated = record_retro(tracking, retro)
                    save_if_current(tracking, updated)
                except InputError as err:
                    st.error(as_text(str(err)))
                except OSError as err:
                    st.error(f"Der Rückblick konnte nicht gespeichert werden: {as_text(str(err))}.")
                else:
                    st.rerun()
        measures = open_measures(tracking)
        if measures:
            st.markdown("**Offene Maßnahmen**")
            for retro in measures:
                if st.checkbox(
                    f"Woche ab {retro.monday:%d.%m.%Y}: {as_text(retro.measure)}",
                    key=f"measure_done_{retro.monday:%Y%m%d}",
                ):
                    done = retro.model_copy(update={"measure_done": True})
                    try:
                        save_if_current(tracking, record_retro(tracking, done))
                    except (InputError, OSError) as err:
                        st.error(
                            f"Die Maßnahme konnte nicht gespeichert werden: {as_text(str(err))}."
                        )
                    else:
                        st.rerun()

    with st.container(border=True, key="panel-cost"):
        heading("euro", "Kosten", du="setzt den Stundensatz", python="rechnet")
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
        heading(
            "smart_toy",
            "Kontroll-Agent",
            agent="bewertet und schlägt vor",
            python="prüft",
            du="entscheidest, was umgesetzt wird",
        )
        st.caption(
            "Der Agent bewertet den Stand und schlägt Gegenmaßnahmen vor. Python nimmt den "
            "Vorschlag "
            "nur an, wenn jede Aufgabe im Verzug eine Gegenmaßnahme hat. Was umgesetzt wird, "
            "entscheidest du."
        )
        agreed = consent("consent_kontrolle")
        if st.button(
            "Stand mit dem Agenten bewerten", icon=":material/play_arrow:", disabled=not agreed
        ):
            proposed = run_with_progress(
                "Der Agent bewertet den Stand …",
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
                    ids = as_text(", ".join(finding.task_ids))
                    where = f"**{ids}:** " if finding.task_ids else ""
                    st.markdown(f"- {where}{as_text(finding.observation)}")
                st.markdown("**Gegenmaßnahmen**")
                if report.measures:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Aufgaben": ", ".join(m.task_ids),
                                    "Maßnahme": m.action,
                                    "Erwartete Wirkung (Agent)": m.effect,
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
                    st.caption("Der Agent schlägt keine Gegenmaßnahmen vor.")

if tracking is not None:
    with st.container(border=True, key="panel-document"):
        heading("description", "Kontrollbericht", python="fasst alles zusammen")
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

with st.container(border=True, key="panel-effort"):
    heading("timer", "Aufwand der Agenten", python="zählt aus den Protokollen")
    runs = agent_runs()  # a damaged log is a row that says so
    if runs:
        st.dataframe(pd.DataFrame(runs), hide_index=True)
        st.caption(
            "Ein Lauf ist ein Aufruf eines Agenten. Token-Kosten in Euro werden nicht "
            "berechnet: Preise sind in der Anwendung nicht hinterlegt."
        )
    else:
        st.caption("Noch keine protokollierten Läufe.")

    st.markdown("**Exportierte Pläne**")
    record = workbench.RUNS_CSV
    try:
        exports = workbench.read_runs()
    except workbench.InputError as err:
        st.error(
            f"{record.parent.name}/{record.name} konnte nicht gelesen werden: "
            f"{as_text(str(err))}. Die Datei bleibt, wie sie ist; der nächste Export legt sie "
            "beiseite und beginnt eine neue."
        )
    except OSError as err:  # cannot be opened at all: the next export cannot either
        st.error(
            f"{record.parent.name}/{record.name} konnte nicht gelesen werden: {as_text(str(err))}."
        )
    else:
        if exports:
            st.dataframe(pd.DataFrame(exports), hide_index=True)
        else:
            st.caption("Noch kein Plan exportiert.")
    aside = workbench.put_aside()
    if aside:
        st.caption(
            f"Ältere Exporte mit anderen Spalten liegen daneben in {record.parent.name}/: "
            + ", ".join(aside)
        )
