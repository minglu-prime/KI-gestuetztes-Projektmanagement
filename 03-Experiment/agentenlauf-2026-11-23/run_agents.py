"""Runs the two agents PR 86 changed, three times each, against the real model. Costs quota.

- Umplanung with the absence wish: does the agent now move tasks so the end stays in time?
- Durchführung: does the summary now name the forecast end date when it is after the deadline?

The inputs are those of the run of 21.11.2026, read from its local logs (LAUF21, default
pm_agent/logs/lauf-20261121): the plan with requirements and the design. Nothing goes to
data/: project, Vorhaben, team and logs point into a temporary folder or OUT (default
pm_agent/logs/lauf-<date>, which git ignores); data/ is compared before and after.

From the repository root (key and model come from .env, see CLAUDE.md):

    uv run --project 04-Prototyp/pm_agent --env-file 04-Prototyp/pm_agent/.env \\
        python 03-Experiment/agentenlauf-2026-11-23/run_agents.py [OUT] [LAUF21]
"""

import hashlib
import json
import shutil
import sys
import tempfile
import time
import traceback
from datetime import date
from pathlib import Path

from pm_agent import agent, followup, lifecycle, tracking, workbench
from pm_agent.models import Design, Member, Plan, Project, Requirement

ROOT = Path(__file__).resolve().parents[2]
PM = ROOT / "04-Prototyp" / "pm_agent"
DATA = PM / "data"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else PM / "logs" / f"lauf-{date.today():%Y%m%d}"
LAUF21 = Path(sys.argv[2]) if len(sys.argv) > 2 else PM / "logs" / "lauf-20261121"
REPEATS = 3
# The day Durchführung evaluates the project on: the same as on 20. and 21.11.2026.
STAND = date(2026, 11, 20)
PROJECT = Project(
    idea=(
        "Web-App, mit der Studierende Lernräume der Hochschule buchen: Anmeldung mit dem "
        "Hochschul-Login, Liste freier Räume, Buchen und Stornieren, Erinnerung per E-Mail."
    ),
    start_date=date(2026, 11, 9),
    deadline=date(2026, 12, 18),
)
# Invented team, as in the README and the runs of 20. and 21.11.2026.
TEAM = [
    Member(name="Anna", skills={"Python": 4, "SQL": 3}, hours_per_week=20),
    Member(name="Ben", skills={"React": 4, "CSS": 3}, hours_per_week=15),
    Member(name="Clara", skills={"Testing": 3, "UX": 4, "Python": 2}, hours_per_week=12),
]
WISH = "Clara ist vom 7.12. bis 11.12. auf einer Exkursion."


def digest(folder: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.glob("*"))
        if p.is_file()
    }


def inputs_of_21_11() -> tuple[Plan, list[Requirement], Design]:
    """The plan with requirements (a planning log without a wish) and the design of 21.11."""
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(LAUF21.glob("run-*.json"))]
    (base,) = [r for r in runs if r.get("requirements") and not r.get("wish")]
    (design_log,) = [
        json.loads(p.read_text(encoding="utf-8")) for p in LAUF21.glob("entwurf-*.json")
    ]
    return (
        Plan.model_validate(base["plan"]),
        [Requirement.model_validate(r) for r in base["requirements"]],
        Design.model_validate(design_log["result"]),
    )


def main() -> int:
    plan, requirements, design = inputs_of_21_11()
    before = digest(DATA)
    sandbox = Path(tempfile.mkdtemp(prefix="pm-agentenlauf-"))
    tracking.PROJECT_FILE = sandbox / "projekt.json"
    lifecycle.FILE = sandbox / "vorhaben.json"
    workbench.TEAM_FILE = sandbox / "team.json"
    workbench.RUNS_CSV = sandbox / "runs.csv"
    agent.LOG_DIR = sandbox / "logs"
    shutil.copy(DATA / "projekt.json", tracking.PROJECT_FILE)
    adopted = tracking.load(tracking.PROJECT_FILE)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Logs: {OUT}")

    results: dict[str, str] = {}

    def step(name, call):
        started = time.monotonic()
        try:
            call()
        except Exception as err:  # noqa: BLE001 (recorded and shown; the next runs still go)
            results[name] = f"Fehler: {type(err).__name__}: {err}"
            traceback.print_exc()
        else:
            results[name] = "ok"
        print(f"{name}: {results[name]} ({time.monotonic() - started:.0f} s)", flush=True)

    for number in range(1, REPEATS + 1):
        step(
            f"umplanung_abwesenheit_{number}",
            lambda: agent.run_replanning(
                PROJECT, TEAM, plan, WISH, log_dir=OUT, design=design, requirements=requirements
            ),
        )
        step(
            f"durchfuehrung_{number}",
            lambda: followup.run_status_summary(adopted, STAND, log_dir=OUT),
        )

    after = digest(DATA)
    print("data/ unverändert" if before == after else "WARNUNG: data/ hat sich geändert")
    (OUT / "zusammenfassung-lauf.json").write_text(
        json.dumps({"results": results, "data_unchanged": before == after}, indent=2),
        encoding="utf-8",
    )
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())
