"""Reads the agent logs of one or more runs and writes one row per agent run to a CSV:
rounds, rejections by the Python check, time, tokens, and how long the free texts are.
No text of the model goes into the CSV, only counts.

    uv run --project 04-Prototyp/pm_agent python \\
        03-Experiment/agentenlauf-2026-11-21/summarize.py OUT.csv LABEL=LOGDIR [LABEL=LOGDIR ...]
"""

import csv
import json
import sys
from pathlib import Path
from typing import Any

from pm_agent.models import Member, MemberAbsence, Plan, Project
from pm_agent.planning import check_plan
from pm_agent.tools import LIMITS, with_absences

COLUMNS = [
    "lauf",
    "agent",
    "modell",
    "ergebnis",
    "sekunden",
    "runden",
    "abgelehnt",
    "abgelehnt_zu_lang",
    "eingabe_token",
    "ausgabe_token",
    "freitexte",
    "freitext_zeichen",
    "freitext_max",
    "ueber_grenze",
    "planende",
    "fehler",
    "warnungen",
]


def agent_name(path: Path, log: dict[str, Any]) -> str:
    prefix = path.stem.split("-")[0]
    if prefix != "run":
        return prefix
    if log.get("wish"):
        return "umplanung_abwesenheit" if log.get("absences") else "umplanung"
    return "planung_mit_anforderungen" if log.get("requirements") else "planung"


def free_texts(value: Any, key: str = "") -> list[tuple[str, str]]:
    """(field, text) for every free text the length limits cover."""
    if isinstance(value, dict):
        return [t for k, v in value.items() for t in free_texts(v, k)]
    if isinstance(value, list):
        return [t for item in value for t in free_texts(item, key)]
    return [(key, value)] if isinstance(value, str) and key in LIMITS else []


def row(label: str, path: Path) -> dict[str, Any]:
    log = json.loads(path.read_text(encoding="utf-8"))
    if path.stem.startswith("ki_lab"):
        usage = log.get("usage") or {}
        return {
            "lauf": label,
            "agent": "ki_lab",
            "modell": log.get("returned_model") or log.get("requested_model"),
            "ergebnis": log.get("outcome"),
            "sekunden": log.get("seconds"),
            "runden": 1,
            "abgelehnt": 0,
            "abgelehnt_zu_lang": 0,
            "eingabe_token": usage.get("input_tokens"),
            "ausgabe_token": usage.get("output_tokens"),
            "freitexte": 1,
            "freitext_zeichen": len(log.get("answer") or ""),
            "freitext_max": len(log.get("answer") or ""),
        }
    rounds = log.get("rounds", [])
    results = [r for rnd in rounds for r in rnd.get("tool_results", [])]
    rejected = [r for r in results if r["tool"].startswith("submit") and r["is_error"]]
    final = log.get("plan") if "plan" in log else log.get("result")
    texts = free_texts(final or {})
    lengths = [len(text) for _, text in texts]
    out = {
        "lauf": label,
        "agent": agent_name(path, log),
        "modell": rounds[0]["model"] if rounds else log.get("requested_model"),
        "ergebnis": "ok"
        if final is not None and not log.get("error")
        else "kein Ergebnis",
        "sekunden": log.get("seconds"),
        "runden": len(rounds),
        "abgelehnt": len(rejected),
        "abgelehnt_zu_lang": sum("Zu lang bei" in r["content"] for r in rejected),
        "eingabe_token": sum(
            (r.get("usage") or {}).get("input_tokens", 0) for r in rounds
        ),
        "ausgabe_token": sum(
            (r.get("usage") or {}).get("output_tokens", 0) for r in rounds
        ),
        "freitexte": len(texts),
        "freitext_zeichen": sum(lengths),
        "freitext_max": max(lengths, default=0),
        "ueber_grenze": sum(len(text) > LIMITS[field] for field, text in texts),
    }
    if "plan" in log and final is not None:
        team = with_absences(
            [Member.model_validate(m) for m in log["team"]],
            [MemberAbsence.model_validate(a) for a in log.get("absences") or []],
        )
        result = check_plan(
            Plan.model_validate(final), team, Project.model_validate(log["project"])
        )
        out.update(
            planende=result.end_date.isoformat() if result.end_date else "",
            fehler=len(result.errors),
            warnungen=len(result.warnings),
        )
    return out


def main() -> None:
    target = Path(sys.argv[1])
    rows = []
    for spec in sys.argv[2:]:
        label, folder = spec.split("=", 1)
        logs = sorted(
            p for p in Path(folder).glob("*.json") if not p.stem.startswith("zusammen")
        )
        rows += [row(label, p) for p in logs]
    with target.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} Zeilen nach {target}")


if __name__ == "__main__":
    main()
