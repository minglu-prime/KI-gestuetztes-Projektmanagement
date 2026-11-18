"""The agent loop and the planning agent. Claude drafts a result, a deterministic tool checks
it, and Claude corrects it until the submit tool accepts it. The project lead reviews the
result. The agents for Durchführung and Kontrolle (followup.py) use the same loop.
"""

import json
import os
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple, TypeVar

from anthropic import Anthropic

from pm_agent.models import Design, Member, MemberAbsence, Plan, Project, Requirement
from pm_agent.tools import PlanningTools, Submission

DEFAULT_MODEL = "claude-opus-5-5"
# One round is one reply from Claude. Drafting, a few checks and the submission take about
# five; ten without an accepted result means Claude is stuck.
MAX_ROUNDS = 10
PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (PROMPTS / "planning.md").read_text(encoding="utf-8")
# Changing a plan follows the same rules for a plan, plus how to treat the existing one.
REPLANNING_PROMPT = SYSTEM_PROMPT + "\n\n" + (PROMPTS / "replanning.md").read_text(encoding="utf-8")
# 04-Prototyp/pm_agent/logs, next to the package and git-ignored: logs hold team data.
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

# The SDK's tool runner ends quietly on these replies. None of them can lead to a result.
_STOP_ERRORS = {
    "max_tokens": (
        "Die Antwort von Claude wurde abgeschnitten, weil sie zu lang war. "
        "Beschreibe das Projekt knapper oder plane es in Teilen."
    ),
    "model_context_window_exceeded": (
        "Der Verlauf passt nicht mehr ins Kontextfenster von Claude. Starte die Planung neu."
    ),
}

T = TypeVar("T")


class AgentError(RuntimeError):
    """An agent produced no result. The message is German and meant for the project lead."""


PlanningError = AgentError  # the name the planning page and its tests use


def run_planning(
    project: Project,
    team: list[Member],
    log_dir: Path | None = LOG_DIR,
    on_round: Callable[[dict[str, Any]], None] | None = None,
    *,
    requirements: list[Requirement] | None = None,
    covered: frozenset[str] = frozenset(),
    design: Design | None = None,
) -> Plan:
    """Let Claude plan the project. Returns the first plan that submit_plan accepts: no
    errors, warnings possible. Raises PlanningError; errors of the API itself propagate.
    Each run, successful or not, is written to `log_dir` as one JSON file (None: no log).
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
    log_dir: Path | None = LOG_DIR,
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
    log_dir: Path | None = LOG_DIR,
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
    tools: list[Any],
    result: Callable[[], T | None],
    record: Callable[[T | None], dict[str, Any]],
    log_dir: Path | None = LOG_DIR,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> T:
    """One agent run. `result` returns what the submit tool accepted, or None until then.
    `noun` names the result in messages ("Plan", "Statusbericht"; a masculine German noun).
    `record` adds the agent's own fields to the log file `<log_prefix>-<time>.json`."""
    rounds: list[dict[str, Any]] = []
    accepted: T | None = None
    error = None
    started = datetime.now().astimezone()
    try:
        accepted = _run(noun, system, request, tools, result, rounds, on_round or (lambda _: None))
        return accepted
    except Exception as err:
        error = f"{type(err).__name__}: {err}"
        raise
    finally:
        if log_dir is not None:
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
    tools: list[Any],
    result: Callable[[], T | None],
    rounds: list[dict[str, Any]],
    on_round: Callable[[dict[str, Any]], None],
) -> T:
    client = Anthropic()
    # The SDK checks credentials only when it sends, and then raises a bare TypeError.
    if client.api_key is None and client.auth_token is None and client.credentials is None:
        raise AgentError(
            "Kein Zugang zur Claude API: ANTHROPIC_API_KEY ist nicht gesetzt. Trage den "
            "Schlüssel in 04-Prototyp/pm_agent/.env ein und starte mit --env-file .env."
        )
    runner = client.beta.messages.tool_runner(
        model=_model(),
        max_tokens=16_000,
        system=system,
        messages=[{"role": "user", "content": request}],
        tools=tools,
        output_config={"effort": "high"},
        cache_control={"type": "ephemeral"},  # every round resends the history
        # On a refusal the API reruns the request on a fallback model it picks, in the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        # Full history in every request: no conversation copy with team data stays on the server.
        thread=False,
        max_iterations=MAX_ROUNDS,
    )
    message = None
    with closing(runner):
        for message in runner:
            rounds.append(_round(message))
            details = message.stop_details
            raise_for_stop_reason(message.stop_reason, details.category if details else None)
            # Runs the tools now; the runner reuses the result for the next request.
            response = runner.generate_tool_call_response()
            rounds[-1]["tool_results"] = _tool_results(message, response)
            on_round(rounds[-1])
            accepted = result()
            if accepted is not None:
                return accepted
    if message is not None and message.stop_reason == "end_turn":
        said = " ".join(block.text for block in message.content if block.type == "text")
        raise AgentError(f"Claude hat aufgehört, ohne einen {noun} einzureichen. {said}".rstrip())
    raise AgentError(f"Claude hat nach {MAX_ROUNDS} Runden noch keinen gültigen {noun}.")


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


def raise_for_stop_reason(stop_reason: str | None, refusal_category: str | None) -> None:
    if stop_reason == "refusal":
        category = f" (Kategorie: {refusal_category})" if refusal_category else ""
        raise AgentError(
            f"Claude hat die Anfrage abgelehnt{category}. Formuliere die Projektidee um."
        )
    if stop_reason in _STOP_ERRORS:
        raise AgentError(_STOP_ERRORS[stop_reason])


def _model() -> str:
    return os.environ.get("PM_AGENT_MODEL") or DEFAULT_MODEL


def _round(message: Any) -> dict[str, Any]:
    """What Claude did in one reply. `model` can differ from the requested one after a
    refusal fallback."""
    return {
        "model": message.model,
        "stop_reason": message.stop_reason,
        "usage": message.usage.model_dump(exclude_none=True),
        "text": " ".join(b.text for b in message.content if b.type == "text"),
        "tool_calls": [
            {"name": b.name, "input": b.input} for b in message.content if b.type == "tool_use"
        ],
        "tool_results": [],
    }


def _tool_results(message: Any, response: dict[str, Any] | None) -> list[dict[str, Any]]:
    names = {b.id: b.name for b in message.content if b.type == "tool_use"}
    return [
        {
            "tool": names.get(result["tool_use_id"]),
            "is_error": bool(result.get("is_error")),
            "content": _text(result.get("content")),
        }
        for result in (response or {}).get("content", [])
    ]


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content or [])


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
