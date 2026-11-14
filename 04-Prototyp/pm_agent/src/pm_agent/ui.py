"""Streamlit pieces that several pages share."""

from collections.abc import Callable
from html import escape
from typing import Any, TypeVar

import streamlit as st
from anthropic import APIError

from pm_agent.agent import AgentError
from pm_agent.tracking import Tracking, load
from pm_agent.workbench import InputError, round_summary

T = TypeVar("T")


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


MARKS = {"on": "✓", "warn": "!", "": "○"}


def chip(text: str, state: str = "") -> str:
    """One entry of a status strip as HTML (styled in assets/style.css). `state` is "on" for
    done, "warn" for something that needs attention, and empty for open."""
    return f'<span class="chip {state}">{MARKS[state]} {escape(text)}</span>'


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


def run_with_progress(label: str, run: Callable[[Callable[[dict[str, Any]], None]], T]) -> T | None:
    """Run an agent and show each round as it happens. `run` gets the on_round callback.
    If the agent fails, the page shows why and gets None."""
    rounds = 0
    result = failure = None
    with st.status(label, expanded=True) as status:

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
