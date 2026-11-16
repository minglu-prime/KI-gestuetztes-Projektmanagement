"""Streamlit pieces that several pages share."""

import re
from collections.abc import Callable
from html import escape
from typing import Any, TypeVar

import altair as alt
import pandas as pd
import streamlit as st
from anthropic import APIError

from pm_agent.agent import AgentError
from pm_agent.models import Plan
from pm_agent.tracking import PART, Tracking, history_rows, load
from pm_agent.workbench import InputError, describe_round, round_summary

T = TypeVar("T")

# Charts have to fit a phone as well. The legend goes below the plot, two entries a row. The
# names of the tasks on the left get a share of the width of the chart: with a fixed 260 px
# a phone showed the names and no bars. The share is taken from the container, not from the
# plot, whose width depends on the labels in turn. "0 * width" changes nothing in the value;
# it makes Vega work the limit out again when the chart gets another width (a phone turned,
# a window resized). Without it the limit of the first size stayed.
LEGEND = alt.Legend(orient="bottom", title=None, columns=2)
TASK_AXIS = alt.Axis(
    labelLimit=alt.ExprRef("clamp(containerSize()[0] * 0.35 + 0 * width, 90, 260)")
)


def adopted_project() -> Tracking | None:
    """The adopted project. Without one, the page shows why and gets None."""
    try:
        tracking = load()
    except InputError as err:
        st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {err}")
        return None
    if tracking is None:
        st.info(
            "Noch kein Projekt übernommen. Erstelle oder öffne einen Plan auf der Seite Planung "
            "und wähle dort im Schritt Export „Plan als Projekt übernehmen“."
        )
        if st.button("Zur Planung", type="primary", icon=":material/arrow_forward:"):
            st.switch_page("pages/planung.py")
    return tracking


def heading(icon: str, text: str) -> None:
    """A panel heading with a Material icon in front. Written as a Material shortcode in
    Markdown, Streamlit labels the icon "name icon", and a screen reader reads that English
    word before the German heading. The icon only decorates, so here it is hidden from screen
    readers. `text` shows as written: neither HTML nor Markdown in it is applied."""
    plain = escape(re.sub(r"([\\`*_\[\]~|#])", r"\\\1", text))
    st.markdown(
        f'#### <span class="icon" aria-hidden="true">{escape(icon)}</span> {plain}',
        unsafe_allow_html=True,
    )


def history_table(tracking: Tracking) -> None:
    """The work kept from earlier plans, if the project was adopted again."""
    if not tracking.history:
        return
    with st.expander(f"Aus früheren Plänen ({len(tracking.history)})"):
        st.dataframe(pd.DataFrame(history_rows(tracking)), hide_index=True)
        st.caption(
            f"Bevor der Rest des Projekts neu übernommen wurde. In allen Kennzahlen "
            f"mitgezählt. „{PART}“: die gebuchten Stunden einer Aufgabe, deren Rest im "
            "aktuellen Plan steht; ihr Plananteil zählt als fertig, sobald die Aufgabe fertig "
            "ist."
        )


MARKS = {"on": "✓", "warn": "!", "": "○", "plain": ""}


def chip(text: str, state: str = "") -> str:
    """One entry of a status strip as HTML (styled in assets/style.css). `state` is "on" for
    done, "warn" for something that needs attention, empty for open, and "plain" for a fact
    that is none of these and gets no mark."""
    label = f"{MARKS[state]} {escape(text)}".strip()
    return f'<span class="chip {state}">{label}</span>'


def strip(*chips: str) -> str:
    """Chips in a row, for st.html."""
    return f'<div class="chips">{"".join(chips)}</div>'


def consent(key: str) -> bool:
    """The agents for Durchführung and Kontrolle send the project with its people to Claude."""
    return st.checkbox(
        "Alle Personen im Projekt haben zugestimmt, dass ihre Angaben (Name, Skills, Stunden, "
        "Aufgaben, Notizen) an die Anthropic API gesendet werden.",
        key=key,
    )


# Streamlit ends a running script when any widget on the page is used. With an agent in
# the middle of its rounds that loses the run, and the tokens it has used.
BUSY_HINT = "Solange Claude arbeitet, bricht jeder Klick auf dieser Seite den Lauf ab."

# A first redraft can touch every task. The view names the first changes and counts the rest;
# the proposal the project lead decides on always lists all of them.
SHOWN_CHANGES = 8


def round_printer(start: Plan | None = None) -> Callable[[dict[str, Any]], None]:
    """Returns a function that writes one agent round after the other: what Claude wrote, the
    draft it checked, what it changed since the round before, and what the check answered.
    The first round is compared with `start`, the plan a change started from."""
    number, previous = 0, start

    def show(record: dict[str, Any]) -> None:
        nonlocal number, previous
        number += 1
        view = describe_round(number, record, previous)
        st.markdown(f"**{view['headline']}**")
        if view["said"] and view["said"] not in view["headline"]:
            st.caption(f"Claude: {view['said']}")
        if view["size"]:
            st.caption(f"Entwurf: {view['size']}")
        if view["changes"]:
            shown, rest = view["changes"][:SHOWN_CHANGES], view["changes"][SHOWN_CHANGES:]
            more = f"\n- … und {len(rest)} weitere Änderungen" if rest else ""
            st.markdown(
                "Geändert seit dem Stand davor:\n\n"
                + "\n".join(f"- {change}" for change in shown)
                + more
            )
        for message in view["messages"]:
            st.caption(message)
        previous = view["draft"] or previous

    return show


def run_with_progress(label: str, run: Callable[[Callable[[dict[str, Any]], None]], T]) -> T | None:
    """Run an agent and show each round as it happens. `run` gets the on_round callback.
    If the agent fails, the page shows why and gets None."""
    rounds = 0
    result = failure = None
    with st.status(label, expanded=True) as status:
        st.caption(BUSY_HINT)

        def on_round(record: dict[str, Any]) -> None:
            nonlocal rounds
            rounds += 1
            headline, messages = round_summary(rounds, record)
            st.write(headline)
            for message in messages:
                st.caption(message)

        try:
            result = run(on_round)
        except AgentError as err:
            failure = str(err)
        except APIError as err:
            failure = f"Die Claude API meldet einen Fehler: {err}"
        status.update(
            label=f"Kein Ergebnis nach {rounds} Runden" if failure else "Vorschlag angenommen",
            state="error" if failure else "complete",
            expanded=True,
        )
    # The message goes below the box: a collapsed status would hide it.
    if failure:
        st.error(failure)
    return result


def on_panel(chart: Any, description: str) -> Any:
    """A chart as it sits in a white panel. The theme would paint the page colour behind it.
    `description` is what a screen reader reads out instead of the picture: what the chart
    shows and where the same numbers stand as text."""
    return chart.properties(background="#ffffff", description=description)
