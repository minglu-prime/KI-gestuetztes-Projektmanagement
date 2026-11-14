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
from typing import Any, TypeVar

from anthropic import Anthropic

from pm_agent.models import Member, Plan, Project
from pm_agent.tools import PlanningTools

DEFAULT_MODEL = "claude-opus-5-5"
# One round is one reply from Claude. Drafting, a few checks and the submission take about
# five; ten without an accepted result means Claude is stuck.
MAX_ROUNDS = 10
PROMPTS = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (PROMPTS / "planning.md").read_text(encoding="utf-8")
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
) -> Plan:
    """Let Claude plan the project. Returns the first plan that submit_plan accepts: no
    errors, warnings possible. Raises PlanningError; errors of the API itself propagate.
    Each run, successful or not, is written to `log_dir` as one JSON file (None: no log).
    `on_round` gets each round as soon as its tools have run, for live progress."""
    tools = PlanningTools(project, team)
    return run_agent(
        log_prefix="run",
        noun="Plan",
        system=SYSTEM_PROMPT,
        request=_request(project, team),
        tools=[tools.check_plan, tools.submit_plan],
        result=lambda: tools.plan,
        # Project and team are kept so that a run can be reopened in the UI.
        record=lambda plan: {
            "project": project.model_dump(mode="json"),
            "team": [member.model_dump(mode="json") for member in team],
            "plan": plan.model_dump(mode="json") if plan is not None else None,
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
            path = log_dir / f"{log_prefix}-{started:%Y%m%d-%H%M%S}.json"
            path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _request(project: Project, team: list[Member]) -> str:
    members = json.dumps([m.model_dump() for m in team], ensure_ascii=False, indent=2)
    return (
        f"Projekt:\n{project.model_dump_json(indent=2)}\n\nTeam:\n{members}\n\n"
        "Erstelle den Plan, prüfe ihn mit check_plan und reiche ihn mit submit_plan ein."
    )
