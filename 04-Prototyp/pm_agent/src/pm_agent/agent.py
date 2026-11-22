"""The agent loop and the planning agent. The model (an OpenAI model; the pages still call it
Claude, after the model the site was built with) drafts a result, a deterministic tool checks
it, and the model corrects it until the submit tool accepts it. The project lead reviews the
result. The agents for Durchführung and Kontrolle (followup.py) use the same loop.
"""

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple, TypeVar

from openai import OpenAI, OpenAIError

from pm_agent.models import Design, Member, MemberAbsence, Plan, Project, Requirement
from pm_agent.tools import PlanningTools, Submission, Tool, ToolError

# One round is one reply from Claude. Drafting, a few checks and the submission take about
# five; ten without an accepted result means Claude is stuck.
MAX_ROUNDS = 10
PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (PROMPTS / "planning.md").read_text(encoding="utf-8")
# Changing a plan follows the same rules for a plan, plus how to treat the existing one.
REPLANNING_PROMPT = SYSTEM_PROMPT + "\n\n" + (PROMPTS / "replanning.md").read_text(encoding="utf-8")
# 04-Prototyp/pm_agent/logs, next to the package and git-ignored: logs hold team data.
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

T = TypeVar("T")


class AgentError(RuntimeError):
    """An agent produced no result. The message is German and meant for the project lead."""


PlanningError = AgentError  # the name the planning page and its tests use


def run_planning(
    project: Project,
    team: list[Member],
    log_dir: Path | None = None,
    on_round: Callable[[dict[str, Any]], None] | None = None,
    *,
    requirements: list[Requirement] | None = None,
    covered: frozenset[str] = frozenset(),
    design: Design | None = None,
) -> Plan:
    """Let Claude plan the project. Returns the first plan that submit_plan accepts: no
    errors, warnings possible. Raises PlanningError; errors of the API itself propagate.
    Each run, successful or not, is written to `log_dir` as one JSON file (None: LOG_DIR).
    `on_round` gets each round as soon as its tools have run, for live progress.
    `requirements`: the approved ones; Claude links each task to them and the check traces
    the plan (`covered`: served by finished work outside the plan). `design`: the approved
    one; Claude cuts tasks along its parts and interfaces."""
    trace = Trace(requirements, covered, design)
    request = (
        f"{_inputs(project, team, trace)}\n\n"
        "Erstelle den Plan, prüfe ihn mit check_plan und reiche ihn mit submit_plan ein."
    )
    return _plan_run(SYSTEM_PROMPT, request, project, team, {}, log_dir, on_round, trace).plan


class Replan(NamedTuple):
    """A changed plan, and the absences the wish named that Claude set for it. The plan was
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
) -> "Replan":
    """Let Claude change `plan` the way the project lead asks in `wish`. Same tools, same
    check and same kind of log as run_planning; the log also keeps the wish. Claude may also
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
    )
    return Replan(plan, tools.absences)


def run_submission(
    name: str,
    submission: Submission[T],
    data: str,
    log_dir: Path | None = None,
    on_round: Callable[[dict[str, Any]], None] | None = None,
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
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "started": started.isoformat(timespec="seconds"),
            "seconds": round((datetime.now().astimezone() - started).total_seconds(), 1),
            "requested_model": _model(),
            "outcome": noun.lower() if accepted is not None else "error",
            "error": error,
            "rounds": [{"round": n, **item} for n, item in enumerate(rounds, start=1)],
            **record(accepted),
        }
        _write_log(log_dir, log_prefix, started, entry)


def _run(
    noun: str,
    system: str,
    request: str,
    tools: list[Tool],
    result: Callable[[], T | None],
    rounds: list[dict[str, Any]],
    on_round: Callable[[dict[str, Any]], None],
) -> T:
    try:
        client = OpenAI()  # reads OPENAI_API_KEY and, for another endpoint, OPENAI_BASE_URL
    except OpenAIError:
        raise AgentError(
            "Kein Zugang zur OpenAI API: OPENAI_API_KEY ist nicht gesetzt. Trage den "
            "Schlüssel in 04-Prototyp/pm_agent/.env ein und starte mit --env-file .env."
        ) from None
    model = _model()
    if not model:  # no default: which models an account may use differs
        raise AgentError(
            "Kein Modell gewählt: PM_AGENT_MODEL ist nicht gesetzt. Trage den Namen eines "
            "OpenAI-Modells in 04-Prototyp/pm_agent/.env ein und starte mit --env-file .env."
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
    said = ""
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
        on_round(rounds[-1])
        accepted = result()
        if accepted is not None:
            return accepted
        if not calls:  # an answer in words: nothing to correct, the model has stopped
            raise AgentError(
                f"Der Agent hat aufgehört, ohne einen {noun} einzureichen. {said}".rstrip()
            )
    raise AgentError(f"Der Agent hat nach {MAX_ROUNDS} Runden noch keinen gültigen {noun}.")


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
