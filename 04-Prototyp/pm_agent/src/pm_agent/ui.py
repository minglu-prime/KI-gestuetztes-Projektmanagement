"""Streamlit pieces that several pages share."""

import datetime
import math
import os
import re
from collections.abc import Callable, Sequence
from html import escape
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit

import altair as alt
import pandas as pd
import streamlit as st
from openai import APIError
from pydantic import ValidationError

from pm_agent import closing, comparison, lifecycle
from pm_agent.agent import MAX_ROUNDS, AgentError
from pm_agent.lifecycle import Lifecycle
from pm_agent.models import Plan
from pm_agent.tracking import (
    PART,
    STATUSES,
    Evaluation,
    Forecast,
    Tracking,
    current_results,
    forecast_bars,
    forecast_text,
    has_progress,
    history_rows,
    hours_text,
    load,
    next_step,
    percent,
)
from pm_agent.workbench import InputError, bar_end, describe_round, round_summary

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


def adopted_project(waiting: str = "") -> Tracking | None:
    """The adopted project. Without one, the page shows why and gets None. `waiting`: what
    a team member sees instead of the way to the Planung, which only the project lead has."""
    try:
        tracking = load()
    except InputError as err:
        st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {as_text(str(err))}")
        return None
    if tracking is None and waiting:
        st.caption(waiting)
    elif tracking is None:
        st.info(
            "Noch kein Projekt übernommen. Erstelle oder öffne einen Plan auf der Seite Planung "
            "und wähle dort im Schritt Übernehmen „Plan als Projekt übernehmen“."
        )
        if st.button("Zur Planung", type="primary", icon=":material/arrow_forward:"):
            st.switch_page("views/planung.py")
    return tracking


def as_text(text: str) -> str:
    """`text` for st.markdown, shown as written: Markdown in it is not applied."""
    return re.sub(r"([\\`*_\[\]~|#!])", r"\\\1", text)


def notify(text: str) -> None:
    """Answer a click that saved or changed something: a notice that fades by itself, so the
    page under it does not move. Kept until app.py shows it (`show_notice`): a toast sent
    right before st.rerun() is lost, and a callback runs before the page."""
    st.session_state["notice"] = text


def show_notice() -> None:
    """The notice of `notify`, once. app.py calls it before the page (callbacks, a save that
    reran) and after it (a save without a rerun)."""
    if text := st.session_state.pop("notice", None):
        # It can quote what was typed, as typed: Markdown in it is not applied.
        st.toast(as_text(text), icon=":material/check_circle:")


def next_open(order: Sequence[str], done: set[str], current: str) -> str:
    """The entry to fill in after `current`: the next one in `order` that is not `done`,
    from the start again after the last. `current` when all are done."""
    later = [*order[order.index(current) + 1 :], *order] if current in order else list(order)
    return next((entry for entry in later if entry not in done), current)


def messages(errors: Sequence[str], warnings: Sequence[str] = (), said: str | None = None) -> None:
    """The findings of a check: the errors in one red box, the warnings in one yellow box.
    One box each made a stack of eleven boxes beside the table they came from. `said` is
    the finding the verdict on top already states in full (said_in_full): not repeated."""
    for show, found in ((st.error, errors), (st.warning, warnings)):
        items = [item for item in found if item != said]
        if len(items) == 1:
            show(as_text(items[0]))
        elif items:
            show("\n".join(f"- {as_text(item)}" for item in items))


# The word before a verdict: the state is said, not shown by its colour alone.
VERDICT_WORDS = {"bad": "Achtung", "warn": "Zu entscheiden", "ok": "In Ordnung"}


def verdict(state: str, text: str) -> None:
    """The result of a page in one line on top of it: red when it is bad (`state` "bad"),
    golden when the project lead has to decide ("warn"), green when it is fine ("ok"). The
    details follow below. `text` shows as written."""
    st.html(
        f'<p class="verdict {state}" role="status">'
        f"<b>{VERDICT_WORDS[state]}:</b> {escape(text)}</p>"
    )


# A priority in a table, in the colours of the verdict line (assets/style.css, .verdict):
# Muss red, Soll golden, Kann green. The word stays: the colour is not the only cue.
PRIORITY_STYLE = {
    "Muss": "color: #8f1d14; background-color: #fdecea; font-weight: 700",
    "Soll": "color: #6a4510; background-color: #fdf3e1; font-weight: 600",
    "Kann": "color: #1d5a3f; background-color: #e3f1e6; font-weight: 600",
}
# An editable cell takes no style (st.data_editor styles read-only columns only): a mark.
PRIORITY_MARK = {"Muss": "🔴", "Soll": "🟡", "Kann": "🟢"}


def style_priority(frame: pd.DataFrame) -> Any:
    """`frame` with its column "Priorität" coloured, for st.dataframe."""
    return frame.style.map(lambda value: PRIORITY_STYLE.get(value, ""), subset=["Priorität"])


def priority_column() -> Any:
    """The editable column "Priorität": the word with its mark; the value stays the word."""
    return st.column_config.SelectboxColumn(
        options=list(PRIORITY_MARK), format_func=lambda p: f"{PRIORITY_MARK[p]} {p}"
    )


def check_verdict(errors: Sequence[str], warnings: Sequence[str], ok: str) -> tuple[str, str]:
    """The verdict of a check: its first error or warning and how many there are; `ok`
    without either. The full list stays below (`messages`)."""
    for state, items, noun in (("bad", errors, "Fehler"), ("warn", warnings, "Warnung")):
        if items:
            plural = "en" if noun == "Warnung" and len(items) > 1 else ""
            more = " …" if len(items) > 1 else ""
            return state, f"{len(items)} {noun}{plural}: {items[0]}{more}"
    return "ok", ok


def said_in_full(errors: Sequence[str], warnings: Sequence[str]) -> str | None:
    """The finding check_verdict states completely: the only error, or without errors the
    only warning. More than one, and the verdict names the first with "…": the list below
    says them all."""
    items = errors or warnings
    return items[0] if len(items) == 1 else None


# A phase before the plan whose check finds nothing: what is still to do about it.
PHASE_VERDICTS = {
    "freigegeben": ("ok", "Geprüft ohne Befund und freigegeben."),
    "entwurf": ("warn", "Geprüft ohne Befund, noch nicht freigegeben."),
    "geändert": ("warn", "Seit der Freigabe geändert: prüfen und neu freigeben."),
}


def phase_verdict(phase: str, check: lifecycle.Check | None) -> tuple[str, str] | None:
    """The verdict of a phase before the plan: the findings of its check first, then its
    approval. None while the phase has nothing in it yet."""
    if phase == "offen" or check is None:
        return None
    return check_verdict(*check, "") if any(check) else PHASE_VERDICTS[phase]


# Finished work may take this share more hours than planned before the verdict asks for a
# decision. The CPI on the Kontrolle counts begun work as earning nothing (0/100 rule) and is
# low early on by design, so the verdict reads the finished work only.
COST_TOLERANCE = 0.10


def overrun_text(evaluation: Evaluation) -> str:
    """Finished work that took more hours than planned beyond COST_TOLERANCE, as a
    sentence; empty within it."""
    over = evaluation.finished_deviation
    if not evaluation.earned or over / evaluation.earned <= COST_TOLERANCE:
        return ""
    share = percent(over / evaluation.earned)
    return f"Fertige Aufgaben brauchten {share} mehr Stunden als geplant (+{hours_text(over)} h)."


def forecast_verdict(
    outlook: Forecast, deadline: datetime.date, evaluation: Evaluation
) -> tuple[str, str]:
    """Time and effort as a verdict: bad past the deadline or without a forecast, a warning
    when the end moved later, no buffer is left or finished work took more hours than
    planned beyond COST_TOLERANCE, fine otherwise."""
    said = forecast_text(outlook, deadline)
    if outlook.end is None and not outlook.problem:
        state, text = "ok", said
    else:
        if outlook.problem or outlook.deadline_gap > 0:
            state = "bad"
        elif outlook.shift > 0 or outlook.deadline_gap == 0:
            state = "warn"
        else:
            state = "ok"
        text = f"Prognose: {said}."
    if over := overrun_text(evaluation):
        text += f" {over}"
        state = "bad" if state == "bad" else "warn"
    return state, text


def saved_lifecycle() -> Lifecycle | None:
    """The Vorhaben (charter, requirements); an empty one before anything was started. A
    damaged file shows why, with a way to start over, and gives None."""
    try:
        return lifecycle.load() or Lifecycle()
    except InputError as err:
        st.error(f"Das Vorhaben konnte nicht gelesen werden: {as_text(str(err))}")
        replace = st.checkbox(
            "Die beschädigte Datei durch ein leeres Vorhaben ersetzen. Ihr Inhalt geht verloren.",
            key="vorhaben_replace",
        )
        if st.button("Neu beginnen", icon=":material/restart_alt:", disabled=not replace):
            if store(None, Lifecycle()) is not None:
                # The fields still hold the old project; the next run would save it again.
                for key in [k for k in st.session_state if k.startswith(FIELD_PREFIXES)]:
                    del st.session_state[key]
                notify("Neues, leeres Vorhaben angelegt.")
                st.rerun()
        return None


# Keys of the fields on the pages Projektauftrag, Anforderungen and Entwurf.
FIELD_PREFIXES = ("auftrag_", "charter_", "requirements_", "design_", "cases_")


def store(old: Lifecycle | None, new: Lifecycle) -> Lifecycle | None:
    """Save the Vorhaben and return the saved version. A failed write returns None."""
    try:
        lifecycle.save_if_current(old, new)
    except (InputError, OSError) as err:
        st.error(f"vorhaben.json konnte nicht gespeichert werden: {as_text(str(err))}")
        return None
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
ROLES = {"agent": "AGENT", "python": "PYTHON", "du": "DU"}


def roles(**who: str) -> str:
    """Who does a part of a page, as HTML for st.html: the agent proposes, Python computes and
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
    ("auftrag", "Projektauftrag", "Der Agent entwirft, du gibst frei"),
    ("anforderungen", "Anforderungen", "Python prüft die Abdeckung"),
    ("entwurf", "Entwurf", "Python zeichnet die Abläufe"),
    ("testplan", "Testplan", "Python prüft die Abdeckung"),
    ("planung", "Planung", "Der Agent entwirft, du übernimmst"),
    ("durchfuehrung", "Durchführung", "das Team trägt den Fortschritt ein"),
    ("testlauf", "Test", "du trägst Ergebnisse und Fehler ein"),
    ("kontrolle", "Kontrolle", "Python rechnet, der Agent bewertet"),
    ("abschluss", "Abschluss", "du nimmst ab, der Agent zieht Lehren"),
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
}


# Pages shown as tabs of one menu entry: the menu names the group and opens its first page;
# the others are hidden there (app.py) and reached by `group_tabs`.
GROUPS = {
    "Vorbereiten": [
        ("auftrag", "Projektauftrag"),
        ("anforderungen", "Anforderungen"),
        ("entwurf", "Entwurf"),
        ("testplan", "Testplan"),
    ],
    "Kontrolle": [("kontrolle", "Kontrolle"), ("testlauf", "Test")],
    "Info": [("ueber_uns", "Über uns"), ("impressum", "Impressum")],
}


def group_tabs(page: str) -> None:
    """The pages of the group `page` belongs to, as a row of tabs; nothing outside a group.
    The others are links, this page is marked: a link to itself would only reload it. On a
    hidden page of the group, the group's entry in the sidebar menu is highlighted too."""
    group = next((pages for pages in GROUPS.values() if page in dict(pages)), None)
    if group is None:
        return
    head = group[0][0]
    with st.container(horizontal=True, gap="small", key="group-tabs"):
        for slug, label in group:
            if slug == page:
                sidebar = (
                    f'<style>[data-testid="stSidebarNavLink"][href$="/{head}"] '
                    "{ background-color: var(--mint); font-weight: 600; }</style>"
                    if slug != head
                    else ""
                )
                st.html(
                    f'{sidebar}<span class="group-tab here" aria-current="page">'
                    f"{escape(label)}</span>",
                    width="content",
                )
            else:
                st.page_link(f"views/{slug}.py", label=label, width="content")


def journey(page: str) -> None:
    """The project path above every page of a phase: which step is done, which is this page,
    which comes next, and which phase before the plan is not approved (a draft, changed since
    its approval, or skipped once a project is adopted: the gates are soft).

    With an adopted project, one line below says what is next (`next_step`) and a button
    leads there; on the page it points to, no line. Before it, the first phase not approved
    is next.
    What cannot be read shows no state: its page says why."""
    try:
        tracking, unreadable = load(), False
    except InputError as err:
        tracking, unreadable = None, True
        # Durchführung and Kontrolle show this error themselves (`adopted_project`), the
        # Planung only in its last step.
        if page == "planung":
            st.error(f"Das übernommene Projekt konnte nicht gelesen werden: {as_text(str(err))}")
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
        # These two pages open with the forecast: the line does not say it again.
        shown = page in ("durchfuehrung", "kontrolle")
        advice, where = next_step(tracking, datetime.date.today(), forecast_shown=shown)
        if where == page:  # its verdict says why; the path marks the step in words
            advice = None
    done = {
        **{slug: phase == "freigegeben" for slug, phase in phases.items()},
        "planung": tracking is not None,
        "durchfuehrung": tracking is not None and has_progress(tracking),
        "testlauf": tracking is not None
        and bool(current_results(tracking, lifecycle.case_plan(life))),
        "kontrolle": False,  # checking never ends while the project runs
        # Closed: decisions taken, and nothing severe left open.
        "abschluss": tracking is not None
        and bool(closing.current_signoffs(tracking))
        and not closing.check_closing(tracking, None).errors,
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
        # Seen: the golden or dashed edge, and the words once: with a "Jetzt dran" line below,
        # it says what is next and the words here are for screen readers only (shown, they
        # pushed the last step onto a second row). Who acts took four rows above every page.
        cue = ""
        if slug == where:
            cue = f" <em{' class=sr' if advice else ''}>als Nächstes</em>"
        if slug in skipped:
            cue += ' <span class="sr">nicht freigegeben</span>'
        steps.append(
            f'<span class="{classes}"{current}>'
            f"<b>{'✓' if done[slug] else number}</b> {name}{cue}"
            f' <span class="sr">{who}</span></span>'
        )
    st.html(f'<nav class="journey" aria-label="Projektpfad">{"".join(steps)}</nav>')
    if advice is None:
        return
    with st.container(horizontal=True, vertical_alignment="center", key="next-step"):
        st.markdown(f"**Jetzt dran:** {as_text(advice)}")
        target, label = PAGES[where]
        if st.button(label, key="journey-go", type="primary", icon=":material/arrow_forward:"):
            st.switch_page(target)


def kept_editor(
    name: str,
    version: str,
    basis: Any,
    data: pd.DataFrame,
    columns: list[str] | None = None,
    **options: Any,
) -> tuple[pd.DataFrame, bool]:
    """Keep edits across pages and flag a draft discarded after its saved basis changed.

    Streamlit drops an editor's edits when another page is shown. On the return the edited
    table comes back as the editor's input, unless `basis` (what `data` was built from)
    changed meanwhile. `version` names the page's counter in session state: raising it starts
    the editor again from `data`. The widget key starts with `name`.

    `columns`: only these come back, the others are taken fresh from `data` (computed ones,
    like a forecast). Only for tables with fixed rows."""
    state = st.session_state
    restores = f"{name}restores"
    kept = state.get(f"{name}current")
    current_version = state.get(version, 0)
    original = data
    conflict = False
    if kept is not None and kept[0] != basis:
        state[restores] = state.get(restores, 0) + 1
        conflict = state.get(f"{name}dirty_version") == current_version
        if conflict:
            st.warning(
                "Der gespeicherte Stand wurde inzwischen geändert. "
                "Prüfe die aktuelle Tabelle und trage deine Änderungen erneut ein."
            )
    elif state.get("page_changed") and kept is not None:
        state[restores] = state.get(restores, 0) + 1
        state[f"{name}restored"] = (current_version, state[restores], basis, kept[1])
    counts = (current_version, state.get(restores, 0))
    restored = state.get(f"{name}restored")
    if restored is not None:
        if restored[:2] == counts and restored[2] == basis:
            if columns is None:
                data = restored[3]
            else:
                data = data.copy()
                data[columns] = restored[3][columns].to_numpy()
        else:
            # Saved or started again since: it never applies again, even if the saved data
            # later reads as it did then.
            del state[f"{name}restored"]
    edited = st.data_editor(data, key=f"{name}{counts[0]}_{counts[1]}", placeholder="", **options)
    state[f"{name}current"] = (basis, edited)
    state[f"{name}dirty_version"] = None if edited.equals(original) else current_version
    return edited, conflict


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


def ai_service() -> str:
    """The service the agents send their data to, as consent has to name it: the host of
    OPENAI_BASE_URL (the school's endpoint), or OpenAI's own API without it. Read when called,
    like the OpenAI client reads it."""
    host = urlsplit(os.environ.get("OPENAI_BASE_URL", "")).hostname
    return f"den KI-Dienst {host or 'api.openai.com'}"


def consent(key: str, data: str = TEAM_DATA, **checkbox: Any) -> bool:
    """Consent before an agent sends what people wrote or are to the model. `data` names what
    goes: by default the project with its people (Durchführung, Kontrolle). `checkbox` goes on
    to st.checkbox (the Planung keeps its consent for the session)."""
    return st.checkbox(
        f"Alle Personen im Projekt haben zugestimmt, dass {data} an {ai_service()} "
        "gesendet werden.",
        key=key,
        **checkbox,
    )


# Streamlit ends a running script when any widget on the page is used. With an agent in
# the middle of its rounds that loses the run, and the tokens it has used.
BUSY_HINT = "Solange der Agent arbeitet, bricht jeder Klick auf dieser Seite den Lauf ab."

# A first redraft can touch every task. The view names the first changes and counts the rest;
# the proposal the project lead decides on always lists all of them.
SHOWN_CHANGES = 8


def round_printer(start: Plan | None = None) -> Callable[[dict[str, Any]], None]:
    """Returns a function that writes one agent round after the other: what the agent wrote, the
    draft it checked, what it changed since the round before, and what the check answered.
    The first round is compared with `start`, the plan a change started from."""
    number, previous = 0, start

    def show(record: dict[str, Any]) -> None:
        nonlocal number, previous
        number += 1
        view = describe_round(number, record, previous)
        st.markdown(f"**{as_text(view['headline'])}**")
        if view["said"] and view["said"] not in view["headline"]:
            st.caption(f"Agent: {as_text(view['said'])}")
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


# Under „Ich bin“ in the view Team (app.py), for someone not in the team yet: Mein Bereich
# then asks for their name.
NEW_MEMBER = "Neu im Team …"


# The columns of the progress table: kept up to date on Mein Bereich, shown on Durchführung.
PROGRESS_CONFIG = {
    # Narrower than its longest title (shown in full on hover): otherwise the columns to fill
    # in lay beyond the right edge of the panel.
    "Aufgabe": st.column_config.TextColumn(width="medium"),
    "Status": st.column_config.SelectboxColumn(options=STATUSES, required=True),
    "Fertig am": st.column_config.DateColumn(
        format="DD.MM.YYYY",
        width=95,  # a date; left empty it took twice that and pushed out "Notiz"
        help="Wird beim Speichern auf heute gesetzt, wenn die Aufgabe fertig wird. "
        "Nachtragen, wenn sie früher fertig war.",
    ),
    "Ist (h)": st.column_config.NumberColumn(format="localized", min_value=0.0, step=0.5),
    "Rest (h)": st.column_config.NumberColumn(
        format="localized",
        min_value=0.0,
        step=0.5,
        help="Was noch zu tun ist, wenn es von Plan minus Ist abweicht. Leer lassen, wenn "
        "unbekannt. Die Prognose auf der Seite Kontrolle rechnet damit.",
    ),
}


def forecast_chart(tracking: Tracking, result: Evaluation, outlook: Forecast) -> Any:
    """Each unfinished task as planned and as forecast, with lines for today and the deadline."""
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
                "Tag": [datetime.date.today(), bar_end(tracking.project.deadline)],
                "Linie": ["Heute", "Deadline"],
            }
        )
    )
    lines = marks.mark_rule(strokeDash=[4, 4]).encode(x="Tag:T")
    names = marks.mark_text(align="left", baseline="top", dx=4, fontSize=11).encode(
        x="Tag:T", y=alt.value(0), text="Linie:N"
    )
    return on_panel(
        bars + lines + names,
        "Balkendiagramm: je unfertiger Aufgabe der Zeitraum laut Plan und der Zeitraum laut "
        "Prognose, mit senkrechten Linien für heute und die Deadline. Die Prognose je Aufgabe "
        "steht auch in der Spalte „Prognose Ende“ auf der Seite Durchführung.",
    )


# A small runner for the lane of rounds of an agent run (Track): arms and legs swing.
RUNNER = (
    '<span class="hop"><span class="tilt"><svg class="runner" viewBox="0 0 24 28">'
    '<circle cx="14" cy="4.5" r="3"/><line x1="13" y1="8" x2="10.5" y2="16"/>'
    '<g class="arm-a"><line x1="12.5" y1="10" x2="16.5" y2="13.5"/></g>'
    '<g class="arm-b"><line x1="12.5" y1="10" x2="8" y2="12.5"/></g>'
    '<g class="leg-a"><line x1="10.5" y1="16" x2="14" y2="23.5"/></g>'
    '<g class="leg-b"><line x1="10.5" y1="16" x2="6.5" y2="23"/></g>'
    "</svg></span></span>"
)
FLAG = (
    '<svg class="flag" viewBox="0 0 16 26">'
    '<line x1="2" y1="2" x2="2" y2="25"/><path d="M2 3 L14 7 L2 11 Z"/></svg>'
)


def lap(record: dict[str, Any]) -> str:
    """How a round of an agent run ended: "done" when a submission was accepted, "found"
    when Python refused something or its check of the plan found errors or warnings (the
    agent has to look again), else "ok"."""
    results = record.get("tool_results", [])
    if any(r["tool"].startswith("submit_") and not r["is_error"] for r in results):
        return "done"
    # round_summary lists exactly these: refusals, errors, and what check_plan found.
    return "found" if round_summary(0, record)[1] else "ok"


class Track:
    """A runner on a lane of rounds above the status box of an agent run, a flag at the end
    of the lane. Each finished round leaves a dot: green, or gold where Python sent the agent
    back. Once a submission is accepted the runner reaches the flag: now the project lead
    decides."""

    def __init__(self) -> None:
        self.slot = st.empty()
        self.laps: list[str] = []
        self.state = ""
        self.show("think")

    def show(self, state: str) -> None:
        if state == self.state == "done":  # drawn again, the end would play a second time
            return
        self.state = state
        now = len(self.laps) + 1
        note = {
            "think": f"Runde {now} von höchstens {MAX_ROUNDS}",
            "back": f"Runde {now} von höchstens {MAX_ROUNDS} · zurück an den Agenten",
            "done": "Jetzt entscheidest du",
            "failed": "",
        }[state]
        lane = []
        for number in range(1, MAX_ROUNDS + 1):
            if number <= len(self.laps):
                lane.append(f'<span class="lap {self.laps[number - 1]}"></span>')
            elif number == now and state in ("think", "back"):
                lane.append(f'<span class="lap now">{RUNNER}</span>')
            else:
                lane.append('<span class="lap"></span>')
        lane.append(f'<span class="goal">{RUNNER if state == "done" else ""}{FLAG}</span>')
        # st.html sanitizes SVG away; every part here is fixed text.
        self.slot.markdown(
            f'<div class="run run-{state}" aria-hidden="true">{"".join(lane)}</div>'
            f'<p class="run-note">{note}</p>',
            unsafe_allow_html=True,
        )

    def round(self, record: dict[str, Any]) -> None:
        ended = lap(record)
        self.laps.append("ok" if ended == "done" else ended)
        self.show({"done": "done", "found": "back", "ok": "think"}[ended])

    def end(self, ok: bool) -> None:
        self.show("done" if ok else "failed")


def run_with_progress(label: str, run: Callable[[Callable[[dict[str, Any]], None]], T]) -> T | None:
    """Run an agent and show each round as it happens. `run` gets the on_round callback.
    If the agent fails, the page shows why and gets None."""
    rounds = 0
    result = failure = None
    track = Track()
    with st.status(label, expanded=True) as status:
        st.caption(BUSY_HINT)

        def on_round(record: dict[str, Any]) -> None:
            nonlocal rounds
            rounds += 1
            track.round(record)
            headline, messages = round_summary(rounds, record)
            st.write(as_text(headline))
            for message in messages:
                st.caption(as_text(message))

        try:
            result = run(on_round)
        except AgentError as err:
            failure = str(err)
        except APIError as err:
            failure = f"Die OpenAI API meldet einen Fehler: {err}"
        track.end(not failure)
        status.update(
            label=f"Kein Ergebnis nach {rounds} Runden" if failure else "Vorschlag angenommen",
            state="error" if failure else "complete",
            # Folded once accepted: the result below is what counts, the rounds are a detail.
            expanded=bool(failure),
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


def comparison_card(
    phase: comparison.PhaseId,
    *,
    review_seconds: float | None = None,
    edited: bool | None = None,
    log_dir: Path | None = None,
) -> None:
    """Optional structured choice-based Q&A comparing work with and without the agent.

    All radios start unselected (`index=None`) and keep unsaved drafts across page switches via
    `persist_state="session"`. No validation error is shown until the user clicks submit.
    """
    spec = comparison.PHASES[phase]
    questions = comparison.questions_for(phase)
    state = st.session_state
    prefix = f"cmp_{phase}_"
    saved_key = f"{prefix}saved"
    skipped_key = f"{prefix}skipped"
    error_key = f"{prefix}error"
    note_key = f"{prefix}note"

    def on_submit() -> None:
        answers = {q.id: state.get(f"{prefix}{q.id}") for q in questions}
        missing = [q.short_label for q in questions if answers[q.id] is None]
        if missing:
            state[error_key] = "Bitte wähle eine Option für: " + ", ".join(missing) + "."
            return
        if answers["mode"] == comparison.MANUAL_MODE:
            metrics, skipped = None, []
        else:
            lookup = comparison.latest_run_metrics(phase, log_dir=log_dir)
            metrics, skipped = lookup.metrics, lookup.skipped_corrupt
        clean_review = (
            round(review_seconds, 1)
            if review_seconds is not None and math.isfinite(review_seconds) and review_seconds >= 0
            else None
        )
        try:
            entry = comparison.ComparisonEntry(
                phase=phase,
                mode=answers["mode"],
                time_comparison=answers["time_comparison"],
                manual_estimate=answers["manual_estimate"],
                quality_comparison=answers["quality_comparison"],
                workload_change=answers["workload_change"],
                phase_q1=answers["phase_q1"],
                phase_q2=answers["phase_q2"],
                note=(state.get(note_key) or "").strip(),
                log_file=metrics.log_file if metrics else "",
                agent_seconds=metrics.seconds if metrics else None,
                agent_rounds=metrics.rounds if metrics else None,
                input_tokens=metrics.input_tokens if metrics else None,
                output_tokens=metrics.output_tokens if metrics else None,
                model=metrics.model if metrics else "",
                review_seconds=clean_review,
                edited=edited,
            )
        except ValidationError as err:
            state[error_key] = f"Eingabe ungültig: {err.errors()[0]['msg']}"
            return
        try:
            comparison.record_comparison(entry)
        except (OSError, ValueError) as err:
            state[error_key] = f"Die Bewertung konnte nicht gespeichert werden: {err}"
            return
        state[saved_key] = True
        notify(f"Bewertung für {spec.label} gespeichert.")
        if skipped:
            state[skipped_key] = skipped
        for q in questions:
            state[f"{prefix}{q.id}"] = None
        state[note_key] = ""

    with st.container(border=True, key=f"panel-comparison-{phase}"):
        heading(
            "compare_arrows",
            f"Effizienzvergleich ({spec.label})",
            du="bewertest mit vs. ohne Agent",
            python="protokolliert lokal",
        )
        st.caption(
            "Subjektive Arbeitsweisen-Bewertung (ergänzend zum kontrollierten KI-Lab). Optional – "
            "die Bewertung blockiert keinen Schritt und bleibt lokal in logs/agent_vergleich.csv."
        )
        if state.pop(saved_key, False):
            st.success(
                "Bewertung gespeichert (lokal in logs/agent_vergleich.csv, nicht im Repository)."
            )
        if skipped := state.pop(skipped_key, None):
            st.warning(
                "Neuere beschädigte Protokolle wurden bei der Zuordnung übersprungen: "
                + as_text(", ".join(skipped))
            )
        failure = state.pop(error_key, None)
        if failure:
            st.error(as_text(failure))
        with st.expander("Effizienzvergleich erfassen (optional)", expanded=bool(failure)):
            for question in questions:
                st.radio(
                    question.label,
                    question.options,
                    index=None,
                    key=f"{prefix}{question.id}",
                    persist_state="session",
                )
            st.text_input(
                "Kurze Notiz (optional, höchstens 400 Zeichen)",
                max_chars=comparison.MAX_NOTE_LENGTH,
                key=note_key,
                persist_state="session",
                placeholder="z. B. Welche Aufgabe hat am meisten Zeit gespart oder gekostet?",
            )
            st.button(
                "Bewertung speichern",
                key=f"{prefix}submit",
                icon=":material/save:",
                on_click=on_submit,
            )
