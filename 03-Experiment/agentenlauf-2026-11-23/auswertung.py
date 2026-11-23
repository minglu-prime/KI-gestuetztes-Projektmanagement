"""Counts for the two questions of this run, from the agent logs; no text of the model.

- Umplanung with the absence: plan end with the absences, days after the deadline, how many
  tasks changed owner against the input plan, and whether Clara's tasks left her week away.
- Durchführung: whether the accepted summary names the forecast end date, and how often
  check_summary sent it back for that.

    uv run --project 04-Prototyp/pm_agent python \\
        03-Experiment/agentenlauf-2026-11-23/auswertung.py OUT.csv BASE=LAUF21 LABEL=LOGDIR ...

BASE is the log folder of 21.11.2026; its planning log with requirements is the input plan.
"""

import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from pm_agent import tracking
from pm_agent.models import Member, MemberAbsence, Plan, Project
from pm_agent.planning import check_plan
from pm_agent.tools import with_absences

DATA = Path(__file__).resolve().parents[2] / "04-Prototyp" / "pm_agent" / "data"
STAND = date(2026, 11, 20)
DATE_RULE = "die Zusammenfassung nennt dieses Datum aber nicht"
COLUMNS = [
    "lauf",
    "agent",
    "datei",
    "runden",
    "abgelehnt",
    "abgelehnt_datum",
    "planende",
    "kalendertage_nach_deadline",
    "abwesenheiten",
    "aufgaben_umverteilt",
    "datum_genannt",
]


def owners(plan: dict[str, Any]) -> dict[str, str]:
    return {a["task_id"]: a["member"] for a in plan["assignments"]}


def row(label: str, path: Path, base: dict[str, str], forecast_end: str) -> dict[str, Any]:
    log = json.loads(path.read_text(encoding="utf-8"))
    rounds = log.get("rounds", [])
    results = [r for rnd in rounds for r in rnd.get("tool_results", [])]
    rejected = [r for r in results if r["tool"].startswith("submit") and r["is_error"]]
    out = {
        "lauf": label,
        "datei": path.name,
        "runden": len(rounds),
        "abgelehnt": len(rejected),
        "abgelehnt_datum": sum(DATE_RULE in r["content"] for r in rejected),
    }
    if path.stem.startswith("durchfuehrung"):
        summary = (log.get("result") or {}).get("summary", "")
        return out | {"agent": "durchfuehrung", "datum_genannt": forecast_end in summary}
    project = Project.model_validate(log["project"])
    absences = [MemberAbsence.model_validate(a) for a in log.get("absences") or []]
    team = with_absences([Member.model_validate(m) for m in log["team"]], absences)
    checked = check_plan(Plan.model_validate(log["plan"]), team, project)
    late = (checked.end_date - project.deadline).days if checked.end_date else ""
    moved = sum(base.get(task) != member for task, member in owners(log["plan"]).items())
    return out | {
        "agent": "umplanung_abwesenheit",
        "planende": checked.end_date.isoformat() if checked.end_date else "",
        "kalendertage_nach_deadline": late,
        "abwesenheiten": len(absences),
        "aufgaben_umverteilt": moved,
    }


def main() -> None:
    target = Path(sys.argv[1])
    specs = dict(spec.split("=", 1) for spec in sys.argv[2:])
    base_folder = Path(specs.pop("BASE"))
    (base,) = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(base_folder.glob("run-*.json"))
        if (log := json.loads(p.read_text(encoding="utf-8"))).get("requirements")
        and not log.get("wish")
    ]
    outlook = tracking.forecast(tracking.load(DATA / "projekt.json"), STAND)
    forecast_end = tracking.as_shown(outlook.end)
    rows = []
    for label, folder in specs.items():
        for path in sorted(Path(folder).glob("*.json")):
            log = json.loads(path.read_text(encoding="utf-8"))
            if path.stem.startswith("durchfuehrung") or log.get("absences"):
                rows.append(row(label, path, owners(base["plan"]), forecast_end))
    with target.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Prognose am {STAND:%d.%m.%Y}: Ende {forecast_end}; {len(rows)} Zeilen nach {target}")


if __name__ == "__main__":
    main()
