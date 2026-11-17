"""Streamlit pieces that several pages share."""

import datetime
import re
from collections.abc import Callable
from html import escape
from typing import Any, TypeVar

import altair as alt
import pandas as pd
import streamlit as st
from anthropic import APIError

from pm_agent import closing, lifecycle
from pm_agent.agent import AgentError
from pm_agent.lifecycle import Lifecycle
from pm_agent.models import Plan
from pm_agent.tracking import PART, Tracking, has_progress, history_rows, load, next_step
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
            st.switch_page("views/planung.py")
    return tracking


def as_text(text: str) -> str:
    """`text` for st.markdown, shown as written: Markdown in it is not applied."""
    return re.sub(r"([\\`*_\[\]~|#!])", r"\\\1", text)


def saved_lifecycle() -> Lifecycle | None:
    """The Vorhaben (charter, requirements); an empty one before anything was started. A
    damaged file shows why, with a way to start over, and gives None."""
    try:
        return lifecycle.load() or Lifecycle()
    except InputError as err:
        st.error(f"Das Vorhaben konnte nicht gelesen werden: {err}")
        replace = st.checkbox(
            "Die beschädigte Datei durch ein leeres Vorhaben ersetzen. Ihr Inhalt geht verloren.",
            key="vorhaben_replace",
        )
        if st.button("Neu beginnen", icon=":material/restart_alt:", disabled=not replace):
            if store(None, Lifecycle()) is not None:
                # The fields still hold the old project; the next run would save it again.
                for key in [k for k in st.session_state if k.startswith(FIELD_PREFIXES)]:
                    del st.session_state[key]
                st.rerun()
        return None


# Keys of the fields on the pages Projektauftrag, Anforderungen and Entwurf.
FIELD_PREFIXES = ("auftrag_", "charter_", "requirements_", "design_", "cases_")


def store(old: Lifecycle | None, new: Lifecycle) -> Lifecycle | None:
    """Save the Vorhaben. Gives what is saved now: `new`, or `old` if writing failed."""
    try:
        lifecycle.save(new)
    except OSError as err:
        st.error(f"vorhaben.json konnte nicht gespeichert werden: {err}.")
        return old
    return new


# How far a phase before the plan is, as a chip of the status strip.
PHASE_CHIPS = {
    "offen": ("nicht angelegt", ""),
    "entwurf": ("Entwurf, nicht freigegeben", ""),
    "geändert": ("seit der Freigabe geändert", "warn"),
    "freigegeben": ("freigegeben", "on"),
}


def phase_chip(name: str, phase: str) -> str:
    text, mark = PHASE_CHIPS[phase]
    return chip(f"{name}: {text}", mark)


def heading(icon: str, text: str, **who: str) -> None:
    """A panel heading with a Material icon in front. Written as a Material shortcode in
    Markdown, Streamlit labels the icon "name icon", and a screen reader reads that English
    word before the German heading. The icon only decorates, so here it is hidden from screen
    readers. `text` shows as written: neither HTML nor Markdown in it is applied. `who` puts
    the roles under the heading (see `roles`)."""
    plain = escape(as_text(text))
    st.markdown(
        f'#### <span class="icon" aria-hidden="true">{escape(icon)}</span> {plain}',
        unsafe_allow_html=True,
    )
    if who:
        st.html(roles(**who))


# The three who act on every agent page. One word each, the same everywhere, also on the
# Startseite: a reader who does not know agents sees what the machine did and what is theirs.
ROLES = {"claude": "CLAUDE", "python": "PYTHON", "du": "DU"}


def roles(**who: str) -> str:
    """Who does a part of a page, as HTML for st.html: Claude proposes, Python computes and
    checks, the project lead ("du") enters and decides. Each keyword is a role, its value
    what that role does here; the chips keep the order of the keywords."""
    return (
        '<div class="roles">'
        + "".join(
            f'<span class="role {role}"><b>{ROLES[role]}</b> {escape(does)}</span>'
            for role, does in who.items()
        )
        + "</div>"
    )


# The loop of a project, one step per agent page, and who acts in each.
JOURNEY = [
    ("auftrag", "Auftrag", "Claude entwirft, du gibst frei"),
    ("anforderungen", "Anforderungen", "Python prüft die Abdeckung"),
    ("entwurf", "Entwurf", "Python zeichnet die Abläufe"),
    ("testplan", "Testplan", "Python prüft die Abdeckung"),
    ("planung", "Planen", "Claude entwirft, du übernimmst"),
    ("durchfuehrung", "Ausführen", "du trägst den Fortschritt ein"),
    ("testlauf", "Testen", "du trägst Ergebnisse und Fehler ein"),
    ("kontrolle", "Prüfen", "Python rechnet, Claude bewertet"),
    ("abschluss", "Abschluss", "du nimmst ab, Claude zieht Lehren"),
    ("betrieb", "Betrieb", "optional"),
    ("iteration", "Iteration", "Python sammelt den nächsten Backlog"),
]
PAGES = {
    "auftrag": ("views/auftrag.py", "Zum Projektauftrag"),
    "anforderungen": ("views/anforderungen.py", "Zu den Anforderungen"),
    "entwurf": ("views/entwurf.py", "Zum Entwurf"),
    "testplan": ("views/testplan.py", "Zum Testplan"),
    "planung": ("views/planung.py", "Zur Planung"),
    "durchfuehrung": ("views/durchfuehrung.py", "Zur Durchführung"),
    "testlauf": ("views/testlauf.py", "Zum Test"),
    "kontrolle": ("views/kontrolle.py", "Zur Kontrolle"),
    "abschluss": ("views/abschluss.py", "Zum Abschluss"),
    "betrieb": ("views/betrieb.py", "Zum Betrieb"),
    "iteration": ("views/iteration.py", "Zur Iteration"),
}


def journey(page: str) -> None:
    """The project path above every page of a phase: which step is done, which is this page,
    which comes next, and which phase before the plan is not approved (a draft, changed since
    its approval, or skipped once a project is adopted: the gates are soft).

    With an adopted project, one line below says what is next (`next_step`) and, if that is
    another page, a button leads there. Before it, the first phase not approved is next.
    What cannot be read shows no state: its page says why."""
    try:
        tracking, unreadable = load(), False
    except InputError as err:
        tracking, unreadable = None, True
        # Durchführung and Kontrolle show this error themselves (`adopted_project`), the
        # Planung only in its last step.
        if page == "planung":
            st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {err}")
    try:
        life = lifecycle.load()
    except InputError as err:
        life, unreadable = None, True
        if page not in ("auftrag", "anforderungen", "entwurf", "testplan"):  # they say it
            st.caption(f"Die Phasen vor dem Plan sind nicht lesbar: {as_text(str(err))}")
    phases = {
        "auftrag": lifecycle.charter_state(life),
        "anforderungen": lifecycle.requirements_state(life),
        "entwurf": lifecycle.design_state(life),
        "testplan": lifecycle.cases_state(life),
    }
    advice = None
    if unreadable:
        where = None
    elif tracking is None:
        where = next((slug for slug, phase in phases.items() if phase != "freigegeben"), "planung")
    elif page in ("auftrag", "anforderungen", "entwurf", "testplan", "planung"):
        where = None  # these lead through their own steps and need no forecast
    else:
        # Looked up when called, like the pages do: the day is the one they evaluate on.
        advice, where = next_step(tracking, datetime.date.today())
    done = {
        **{slug: phase == "freigegeben" for slug, phase in phases.items()},
        "planung": tracking is not None,
        "durchfuehrung": tracking is not None and has_progress(tracking),
        "testlauf": tracking is not None and bool(tracking.results),
        "kontrolle": False,  # checking never ends while the project runs
        # Closed: decisions taken, and nothing severe left open.
        "abschluss": tracking is not None
        and bool(tracking.signoffs)
        and not closing.check_closing(tracking, None).errors,
        "betrieb": tracking is not None
        and bool(tracking.operations)
        and life is not None
        and not closing.check_operations(life.design, tracking.operations).errors,
        "iteration": False,  # it begins the next run
    }
    # Not approved: a draft or a changed one, or skipped although the project goes on.
    skipped = {
        slug
        for slug, phase in phases.items()
        if not unreadable
        and (phase in ("entwurf", "geändert") or (phase == "offen" and tracking is not None))
    }
    steps = []
    for number, (slug, name, who) in enumerate(JOURNEY, start=1):
        marks = [
            m
            for m, on in [("done", done[slug]), ("next", slug == where), ("warn", slug in skipped)]
            if on
        ]
        here = slug == page
        classes = " ".join(["step", *marks, *(["here"] if here else [])])
        current = ' aria-current="step"' if here else ""
        cue = " <em>als Nächstes</em>" if slug == where else ""
        if slug in skipped:
            cue += " <em>nicht freigegeben</em>"
        steps.append(
            f'<span class="{classes}"{current}>'
            f"<b>{'✓' if done[slug] else number}</b> {name}{cue} <small>{who}</small></span>"
        )
    arrow = '<span class="arrow" aria-hidden="true">→</span>'
    st.html(
        f'<nav class="journey" aria-label="Projektpfad">{arrow.join(steps)}'
        '<span class="loop">↺ Bei Verzug: Rest in der Planung neu planen</span></nav>'
    )
    if advice is None:
        return
    with st.container(horizontal=True, vertical_alignment="center", key="next-step"):
        below = " ↓ Unten auf dieser Seite." if where == page else ""
        st.markdown(f"**Jetzt dran:** {as_text(advice)}{below}")
        if where != page:
            target, label = PAGES[where]
            if st.button(label, key="journey-go", type="primary", icon=":material/arrow_forward:"):
                st.switch_page(target)


def kept_editor(name: str, version: str, basis: Any, data: pd.DataFrame, **options: Any) -> Any:
    """`st.data_editor` whose unsaved edits survive a visit to another page.

    Streamlit drops an editor's edits when another page is shown. On the return the edited
    table comes back as the editor's input, unless `basis` (what `data` was built from)
    changed meanwhile. `version` names the page's counter in session state: raising it starts
    the editor again from `data`. The widget key starts with `name`."""
    state = st.session_state
    restores = f"{name}restores"
    kept = state.get(f"{name}current")
    if state.get("page_changed") and kept is not None and kept[0] == basis:
        state[restores] = state.get(restores, 0) + 1
        state[f"{name}restored"] = (state.get(version, 0), state[restores], basis, kept[1])
    counts = (state.get(version, 0), state.get(restores, 0))
    restored = state.get(f"{name}restored")
    if restored is not None and restored[:2] == counts and restored[2] == basis:
        data = restored[3]
    edited = st.data_editor(data, key=f"{name}{counts[0]}_{counts[1]}", **options)
    state[f"{name}current"] = (basis, edited)
    return edited


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


TEAM_DATA = "ihre Angaben (Name, Skills, Stunden, Aufgaben, Notizen)"


def consent(key: str, data: str = TEAM_DATA) -> bool:
    """Consent before an agent sends what people wrote or are to Claude. `data` names what
    goes: by default the project with its people (Durchführung, Kontrolle)."""
    return st.checkbox(
        f"Alle Personen im Projekt haben zugestimmt, dass {data} an die Anthropic API "
        "gesendet werden.",
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
        st.markdown(f"**{as_text(view['headline'])}**")
        if view["said"] and view["said"] not in view["headline"]:
            st.caption(f"Claude: {as_text(view['said'])}")
        if view["size"]:
            st.caption(f"Entwurf: {view['size']}")
        if view["changes"]:
            shown, rest = view["changes"][:SHOWN_CHANGES], view["changes"][SHOWN_CHANGES:]
            more = f"\n- … und {len(rest)} weitere Änderungen" if rest else ""
            st.markdown(
                "Geändert seit dem Stand davor:\n\n"
                + "\n".join(f"- {as_text(change)}" for change in shown)
                + more
            )
        for message in view["messages"]:
            st.caption(as_text(message))
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
            st.write(as_text(headline))
            for message in messages:
                st.caption(as_text(message))

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
        st.error(as_text(failure))
    return result


def on_panel(chart: Any, description: str) -> Any:
    """A chart as it sits in a white panel. The theme would paint the page colour behind it.
    `description` is what a screen reader reads out instead of the picture: what the chart
    shows and where the same numbers stand as text."""
    return chart.properties(background="#ffffff", description=description)
