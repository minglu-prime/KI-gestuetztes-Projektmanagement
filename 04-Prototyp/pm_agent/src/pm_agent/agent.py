"""The agent loop and the planning agent. The model (through the OpenAI Responses API; the
pages call it "der Agent") drafts a result, a deterministic tool checks it, and the model
corrects it until the submit tool accepts it. The project lead reviews the
result. The agents for Durchführung and Kontrolle (followup.py) use the same loop.
"""

import json
import logging
import math
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple, TypeVar
from urllib.parse import urlsplit

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
    Timeout,
)

from pm_agent.models import Design, Member, MemberAbsence, Plan, Project, Requirement
from pm_agent.tools import PlanningTools, Submission, Tool, ToolError

logger = logging.getLogger(__name__)

# One round is one reply from the agent. Drafting, a few checks and the submission take about
# five; ten without an accepted result means the agent is stuck.
MAX_ROUNDS = 10
# Limit each API call: the SDK defaults to 10 minutes per try with 2 retries (~30 min).
REQUEST_TIMEOUT = 120.0
CONNECT_TIMEOUT = 10.0
MAX_RETRIES = 1
PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (PROMPTS / "planning.md").read_text(encoding="utf-8")
# Changing a plan follows the same rules for a plan, plus how to treat the existing one.
REPLANNING_PROMPT = SYSTEM_PROMPT + "\n\n" + (PROMPTS / "replanning.md").read_text(encoding="utf-8")
# 04-Prototyp/pm_agent/logs, next to the package and git-ignored: logs hold team data.
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

T = TypeVar("T")
_log_error_sink: ContextVar[list[str] | None] = ContextVar("_log_error_sink", default=None)


class AgentError(RuntimeError):
    """An agent produced no result. The message is German and meant for the project lead."""


PlanningError = AgentError  # the name the planning page and its tests use


def service_host() -> str:
    """Host of OPENAI_BASE_URL, or api.openai.com when none is set. Read when called,
    like the OpenAI client reads it."""
    return urlsplit(os.environ.get("OPENAI_BASE_URL", "").strip()).hostname or "api.openai.com"


def describe_api_error(err: APIError) -> str:
    """Translate a provider APIError into an actionable German message naming the
    configured service host (OPENAI_BASE_URL, or api.openai.com)."""
    host = service_host()
    if isinstance(err, APITimeoutError):
        return (
            f"Zeitüberschreitung bei der Anfrage an den KI-Dienst {host}: keine rechtzeitige "
            "Antwort. Versuche es erneut oder erhöhe PM_AGENT_TIMEOUT in "
            "04-Prototyp/pm_agent/.env."
        )
    if isinstance(err, APIConnectionError):
        return (
            f"Keine Verbindung zum KI-Dienst {host}. Prüfe Netzwerk, VPN und OPENAI_BASE_URL "
            "in 04-Prototyp/pm_agent/.env."
        )
    if isinstance(err, APIStatusError):
        code = err.status_code
        if isinstance(err, AuthenticationError) or code == 401:
            return (
                f"Anmeldung beim KI-Dienst {host} fehlgeschlagen (HTTP 401). Prüfe "
                "OPENAI_API_KEY und OPENAI_BASE_URL in 04-Prototyp/pm_agent/.env."
            )
        if isinstance(err, PermissionDeniedError) or code == 403:
            return (
                f"Zugriff auf den KI-Dienst {host} verweigert (HTTP 403). Prüfe Berechtigungen "
                "für OPENAI_API_KEY und PM_AGENT_MODEL."
            )
        if isinstance(err, NotFoundError) or code == 404:
            model = _model()
            model_hint = f" (PM_AGENT_MODEL={model})" if model else ""
            return (
                f"Modell oder Endpunkt beim KI-Dienst {host} nicht gefunden "
                f"(HTTP 404){model_hint}. Prüfe PM_AGENT_MODEL und OPENAI_BASE_URL in "
                "04-Prototyp/pm_agent/.env."
            )
        if isinstance(err, RateLimitError) or code == 429:
            return (
                f"Anfragelimit oder Kontingent beim KI-Dienst {host} erreicht (HTTP 429). "
                "Warte kurz und versuche es erneut, oder prüfe dein Kontingent."
            )
        if isinstance(err, InternalServerError) or code >= 500:
            return (
                f"Der KI-Dienst {host} hat vorübergehend ein Problem (HTTP {code}). Versuche es "
                "in einigen Minuten erneut."
            )
        return (
            f"Der KI-Dienst {host} hat die Anfrage abgewiesen (HTTP {code}). Prüfe "
            "Modell-Einstellungen und Eingaben oder versuche es erneut."
        )
    return (
        f"Der KI-Dienst {host} meldet einen unerwarteten Fehler. Versuche es erneut oder prüfe "
        "das Laufprotokoll in logs/."
    )


@contextmanager
def collect_log_errors() -> Iterator[list[str]]:
    """Collect German warnings for run-log write errors raised inside the block."""
    errors: list[str] = []
    token = _log_error_sink.set(errors)
    try:
        yield errors
    finally:
        _log_error_sink.reset(token)


def run_planning(
    project: Project,
    team: list[Member],
    log_dir: Path | None = None,
    on_round: Callable[[dict[str, Any]], None] | None = None,
    *,
    requirements: list[Requirement] | None = None,
    covered: frozenset[str] = frozenset(),
    design: Design | None = None,
    on_log_error: Callable[[OSError], None] | None = None,
) -> Plan:
    """Let the agent plan the project. Returns the first plan that submit_plan accepts: no
    errors, warnings possible. Raises PlanningError; errors of the API itself propagate.
    Each run, successful or not, is written to `log_dir` as one JSON file (None: LOG_DIR).
    `on_round` gets each round as soon as its tools have run, for live progress.
    `requirements`: the approved ones; the agent links each task to them and the check traces
    the plan (`covered`: served by finished work outside the plan). `design`: the approved
    one; the agent cuts tasks along its parts and interfaces."""
    trace = Trace(requirements, covered, design)
    request = (
        f"{_inputs(project, team, trace)}\n\n"
        "Erstelle den Plan, prüfe ihn mit check_plan und reiche ihn mit submit_plan ein."
    )
    return _plan_run(
        SYSTEM_PROMPT,
        request,
        project,
        team,
        {},
        log_dir,
        on_round,
        trace,
        on_log_error=on_log_error,
    ).plan


class Replan(NamedTuple):
    """A changed plan, and the absences the wish named that the agent set for it. The plan was
    checked with them; the project lead takes both into plan and team, or neither."""

    plan: Plan
    absences: list[MemberAbsence]


def run_replanning(
    project: Project,
    team: list[Member],
    plan: Plan,
    wish: str,
    log_dir: Path | None = None,
    on_round: Callable[[dict[str, Any]], None] | None = None,
    *,
    requirements: list[Requirement] | None = None,
    covered: frozenset[str] = frozenset(),
    design: Design | None = None,
    on_log_error: Callable[[OSError], None] | None = None,
) -> "Replan":
    """Let the agent change `plan` the way the project lead asks in `wish`. Same tools, same
    check and same kind of log as run_planning; the log also keeps the wish. The agent may also
    set absences the wish names (set_absence); they come back with the plan and are logged."""
    wish = wish.strip()
    if not wish:
        raise AgentError("Beschreibe, was sich ändern soll.")
    trace = Trace(requirements, covered, design)
    request = (
        f"{_inputs(project, team, trace)}\n\nAktueller Plan:\n"
        f"{plan.model_dump_json(indent=2)}\n\n"
        f"Wunsch der Projektleitung:\n{wish}\n\n"
        "Passe den Plan an, prüfe ihn mit check_plan und reiche ihn mit submit_plan ein."
    )
    return _plan_run(
        REPLANNING_PROMPT,
        request,
        project,
        team,
        {"wish": wish},
        log_dir,
        on_round,
        trace,
        absences=True,
        on_log_error=on_log_error,
    )


def _plan_run(
    system: str,
    request: str,
    project: Project,
    team: list[Member],
    extra: dict[str, Any],
    log_dir: Path | None,
    on_round: Callable[[dict[str, Any]], None] | None,
    trace: "Trace",
    absences: bool = False,
    on_log_error: Callable[[OSError], None] | None = None,
) -> Replan:
    tools = PlanningTools(project, team, trace.requirements, trace.covered, absences=absences)
    if trace.requirements is not None:  # what the plan was traced to, for the record
        extra = {**extra, "requirements": [r.model_dump(mode="json") for r in trace.requirements]}
    plan = run_agent(
        log_prefix="run",
        noun="Plan",
        system=system,
        request=request,
        tools=[tools.check_plan, tools.submit_plan, *filter(None, [tools.set_absence])],
        result=lambda: tools.plan,
        # Project and team are kept so that a run can be reopened in the UI.
        record=lambda plan: {
            "project": project.model_dump(mode="json"),
            "team": [member.model_dump(mode="json") for member in team],
            "plan": plan.model_dump(mode="json") if plan is not None else None,
            **extra,
            **(
                {"absences": [a.model_dump(mode="json") for a in tools.absences]}
                if absences
                else {}
            ),
        },
        log_dir=log_dir,
        on_round=on_round,
        on_log_error=on_log_error,
    )
    return Replan(plan, tools.absences)


def run_submission(
    name: str,
    submission: Submission[T],
    data: str,
    log_dir: Path | None = None,
    on_round: Callable[[dict[str, Any]], None] | None = None,
    *,
    on_log_error: Callable[[OSError], None] | None = None,
) -> T:
    """An agent with one submit tool: the system prompt is prompts/<name>.md, the request
    the JSON text `data`, and the log keeps input and result under the prefix `name`."""
    return run_agent(
        log_prefix=name,
        noun=submission.noun,
        system=(PROMPTS / f"{name}.md").read_text(encoding="utf-8"),
        request=f"{data}\n\nReiche dein Ergebnis mit {submission.tool.name} ein.",
        tools=[submission.tool],
        result=lambda: submission.result,
        record=lambda result: {
            "input": json.loads(data),
            "result": result.model_dump(mode="json") if result is not None else None,
        },
        log_dir=log_dir,
        on_round=on_round,
        on_log_error=on_log_error,
    )


def run_agent(
    *,
    log_prefix: str,
    noun: str,
    system: str,
    request: str,
    tools: list[Tool],
    result: Callable[[], T | None],
    record: Callable[[T | None], dict[str, Any]],
    log_dir: Path | None = None,
    on_round: Callable[[dict[str, Any]], None] | None = None,
    on_log_error: Callable[[OSError], None] | None = None,
) -> T:
    """One agent run. `result` returns what the submit tool accepted, or None until then.
    `noun` names the result in messages ("Plan", "Statusbericht"; a masculine German noun).
    `record` adds the agent's own fields to the log file `<log_prefix>-<time>.json`."""
    rounds: list[dict[str, Any]] = []
    accepted: T | None = None
    error = None
    started = datetime.now().astimezone()
    log_dir = log_dir or LOG_DIR  # read at call time: scripts and tests point it elsewhere
    try:
        accepted = _run(noun, system, request, tools, result, rounds, on_round or (lambda _: None))
        return accepted
    except Exception as err:
        error = f"{type(err).__name__}: {err}"
        raise
    finally:
        entry = {
            "started": started.isoformat(timespec="seconds"),
            "seconds": round((datetime.now().astimezone() - started).total_seconds(), 1),
            "requested_model": _model(),
            "outcome": noun.lower() if accepted is not None else "error",
            "error": error,
            "rounds": [{"round": n, **item} for n, item in enumerate(rounds, start=1)],
            **record(accepted),
        }
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            _write_log(log_dir, log_prefix, started, entry)
        except OSError as log_err:
            # Never lose an accepted result or mask the original run error on log-write failure.
            message = f"Das Laufprotokoll konnte nicht in {log_dir} gespeichert werden: {log_err}"
            logger.warning("%s", message)
            if on_log_error is not None:
                on_log_error(log_err)
            if (sink := _log_error_sink.get()) is not None:
                sink.append(message)


def _run(
    noun: str,
    system: str,
    request: str,
    tools: list[Tool],
    result: Callable[[], T | None],
    rounds: list[dict[str, Any]],
    on_round: Callable[[dict[str, Any]], None],
) -> T:
    timeout = _timeout()
    host = service_host()
    try:
        # Reads OPENAI_API_KEY and, for another endpoint, OPENAI_BASE_URL.
        client = OpenAI(timeout=timeout, max_retries=MAX_RETRIES)
    except OpenAIError as err:
        if not os.environ.get("OPENAI_API_KEY"):
            raise AgentError(
                f"Kein Zugang zum KI-Dienst {host}: OPENAI_API_KEY ist nicht gesetzt. Trage den "
                "Schlüssel in 04-Prototyp/pm_agent/.env ein und starte mit --env-file .env."
            ) from None
        raise AgentError(
            f"Der Zugang zum KI-Dienst {host} konnte nicht eingerichtet werden: {err}"
        ) from None
    model = _model()
    if not model:  # no default: which models an account may use differs
        raise AgentError(
            "Kein Modell gewählt: PM_AGENT_MODEL ist nicht gesetzt. Trage den Namen eines "
            f"Modells für {host} in 04-Prototyp/pm_agent/.env ein und starte mit --env-file .env."
        )
    by_name = {tool.name: tool for tool in tools}
    # Responses API: function tools work together with reasoning, which the planning needs.
    # The whole history goes along in every request (store=False: nothing is kept on the
    # server). The model's own output items go back with the answers, reasoning included.
    items: list[dict[str, Any]] = [{"role": "user", "content": request}]
    base = {
        "model": model,
        "instructions": system,
        "tools": [tool.definition() for tool in tools],
        "reasoning": {"effort": _effort()},
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "max_output_tokens": 16_000,
    }
    said = rejected = ""
    for _ in range(MAX_ROUNDS):
        response = client.responses.create(input=items, **base)
        calls = [
            (item, _arguments(item)) for item in response.output if item.type == "function_call"
        ]
        rounds.append(_round(response, calls))
        raise_for_stop_reason(_stop_reason(response), _refusal(response))
        said = response.output_text or ""
        items += [item.model_dump(exclude_none=True) for item in response.output]
        for item, data in calls:
            content, is_error = _call(by_name.get(item.name), data)
            items.append(
                {"type": "function_call_output", "call_id": item.call_id, "output": content}
            )
            rounds[-1]["tool_results"].append(
                {"tool": item.name, "is_error": is_error, "content": content}
            )
            if is_error:
                rejected = content
        on_round(rounds[-1])
        accepted = result()
        if accepted is not None:
            return accepted
        if not calls:  # an answer in words: nothing to correct, the model has stopped
            raise AgentError(
                f"Der Agent hat aufgehört, ohne einen {noun} einzureichen. {said}".rstrip()
            )
    # The last reason goes along: the project lead reads it below the box, without opening
    # every round.
    last = f" Zuletzt abgelehnt: {rejected}" if rejected else ""
    raise AgentError(f"Der Agent hat nach {MAX_ROUNDS} Runden noch keinen gültigen {noun}.{last}")


def _timeout() -> Timeout:
    """Per-request timeout. Default REQUEST_TIMEOUT; PM_AGENT_TIMEOUT overrides it."""
    raw = os.environ.get("PM_AGENT_TIMEOUT", "").strip()
    if not raw:
        seconds = REQUEST_TIMEOUT
    else:
        try:
            seconds = float(raw)
        except ValueError:
            raise AgentError(
                f"Ungültiges Zeitlimit in PM_AGENT_TIMEOUT ({raw!r}): Zahl in Sekunden erwartet."
            ) from None
        if not math.isfinite(seconds) or seconds <= 0:
            raise AgentError(
                f"Ungültiges Zeitlimit in PM_AGENT_TIMEOUT ({raw!r}): Wert muss größer als 0 sein."
            )
    return Timeout(seconds, connect=min(CONNECT_TIMEOUT, seconds))


def _effort() -> str:
    """Reasoning effort. Default medium; PM_AGENT_REASONING_EFFORT overrides it."""
    return os.environ.get("PM_AGENT_REASONING_EFFORT") or "medium"


def _stop_reason(response: Any) -> str:
    """`completed`, or why the reply stopped early: "length" or "content_filter"."""
    if response.status == "incomplete" and response.incomplete_details:
        reason = response.incomplete_details.reason or ""
        return "length" if reason == "max_output_tokens" else reason
    return response.status or ""


def _refusal(response: Any) -> str | None:
    """What the model said when it declined, if it did."""
    for item in response.output:
        if item.type == "message":
            for part in item.content:
                if part.type == "refusal":
                    return part.refusal
    return None


def _arguments(call: Any) -> Any:
    """The input of a tool call. The API sends it as JSON text; text that is none stays text."""
    try:
        return json.loads(call.arguments)
    except ValueError:
        return call.arguments


def _call(tool: Tool | None, data: Any) -> tuple[str, bool]:
    """Runs a tool: what it answers, and whether that is a rejection the model must correct."""
    if tool is None:
        return "Dieses Werkzeug gibt es nicht.", True
    if not isinstance(data, dict):
        return "Ungültige Eingabe: kein gültiges JSON-Objekt.", True
    try:
        return tool.call(data), False
    except ToolError as err:
        return err.content, True


def _write_log(log_dir: Path, prefix: str, started: datetime, entry: dict[str, Any]) -> Path:
    """Write a run log under a name of its own. The name has seconds only, and two runs can
    start in the same second: the second one gets "-2", and so on. "x" never overwrites."""
    stem = f"{prefix}-{started:%Y%m%d-%H%M%S}"
    text = json.dumps(entry, ensure_ascii=False, indent=2)
    number = 1
    while True:
        path = log_dir / (f"{stem}.json" if number == 1 else f"{stem}-{number}.json")
        try:
            with path.open("x", encoding="utf-8") as file:
                file.write(text)
            return path
        except FileExistsError:
            number += 1


def raise_for_stop_reason(stop_reason: str | None, refusal: str | None) -> None:
    """Replies that cannot lead to a result. `refusal` is what the model said when it declined."""
    if stop_reason == "content_filter" or refusal:
        why = f": {refusal.rstrip('.')}" if refusal else ""
        raise AgentError(
            f"Der Agent hat die Anfrage abgelehnt{why}. Formuliere die Projektidee um."
        )
    if stop_reason == "length":
        raise AgentError(
            "Die Antwort vom Agenten wurde abgeschnitten, weil sie zu lang war. "
            "Beschreibe das Projekt knapper oder plane es in Teilen."
        )


def _model() -> str:
    return os.environ.get("PM_AGENT_MODEL") or os.environ.get("PM_MODEL") or ""


def _round(response: Any, calls: list[tuple[Any, Any]]) -> dict[str, Any]:
    """What the model did in one reply, in the shape the logs have had from the start
    (`input_tokens`, `output_tokens`), so that earlier logs and new ones read alike."""
    usage = response.usage
    return {
        "model": response.model,
        "stop_reason": _stop_reason(response),
        "usage": (
            {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
            if usage
            else {}
        ),
        "text": response.output_text or "",
        "tool_calls": [{"name": item.name, "input": data} for item, data in calls],
        "tool_results": [],
    }


class Trace(NamedTuple):
    """The approved requirements a plan is traced to, and those finished work served."""

    requirements: list[Requirement] | None
    covered: frozenset[str]
    design: Design | None = None


def _inputs(project: Project, team: list[Member], trace: Trace) -> str:
    members = json.dumps([m.model_dump(mode="json") for m in team], ensure_ascii=False, indent=2)
    text = f"Projekt:\n{project.model_dump_json(indent=2)}\n\nTeam:\n{members}"
    if trace.requirements is not None:
        needs = json.dumps(
            [r.model_dump(mode="json") for r in trace.requirements], ensure_ascii=False, indent=2
        )
        text += f"\n\nFreigegebene Anforderungen:\n{needs}"
        if trace.covered:
            text += f"\n\nSchon durch fertige Arbeit erfüllt: {', '.join(sorted(trace.covered))}"
    if trace.design is not None:
        # Parts and contracts only: the flows name requirements the planner may not trace.
        parts = trace.design.model_dump(mode="json", include={"components", "interfaces"})
        text += f"\n\nFreigegebener Entwurf:\n{json.dumps(parts, ensure_ascii=False, indent=2)}"
    return text
