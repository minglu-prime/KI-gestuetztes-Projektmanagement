"""Runs every agent of the PM-Agent once against the real model, in the order of a project,
with the inputs of the run of 20.11.2026 so the two can be compared. Costs quota.

Nothing goes to data/: the project, the Vorhaben and the team files point into a temporary
folder, and each agent writes its log to OUT (default: pm_agent/logs/lauf-<date>, which git
ignores). The adopted example project for Durchführung, Kontrolle and Lessons is a copy of
data/projekt.json; the original is compared before and after.

From the repository root (the key and the model come from .env, see CLAUDE.md):

    uv run --project 04-Prototyp/pm_agent --env-file 04-Prototyp/pm_agent/.env \\
        python 03-Experiment/agentenlauf-2026-11-21/run_agents.py [OUT]
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

from pm_agent import agent, closing, followup, lifecycle, tracking, workbench
from pm_agent.models import Member, Project

ROOT = Path(__file__).resolve().parents[2]
PM = ROOT / "04-Prototyp" / "pm_agent"
DATA = PM / "data"
OUT = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else PM / "logs" / f"lauf-{date.today():%Y%m%d}"
)
# The day the follow-up agents evaluate the project on: the same as on 20.11.2026.
STAND = date(2026, 11, 20)

PROJECT = Project(
    idea=(
        "Web-App, mit der Studierende Lernräume der Hochschule buchen: Anmeldung mit dem "
        "Hochschul-Login, Liste freier Räume, Buchen und Stornieren, Erinnerung per E-Mail."
    ),
    start_date=date(2026, 11, 9),
    deadline=date(2026, 12, 18),
)
# Invented team, as in the README and the run of 20.11.2026.
TEAM = [
    Member(name="Anna", skills={"Python": 4, "SQL": 3}, hours_per_week=20),
    Member(name="Ben", skills={"React": 4, "CSS": 3}, hours_per_week=15),
    Member(
        name="Clara", skills={"Testing": 3, "UX": 4, "Python": 2}, hours_per_week=12
    ),
]
WISHES = [
    "Was, wenn das Backend doppelt so lange dauert?",
    "Clara ist vom 7.12. bis 11.12. auf einer Exkursion.",
]
LAB_QUESTION = (
    "Welche Arbeitspakete fehlen in meinem Entwurf noch, und in welcher Reihenfolge sollte "
    "das Team sie angehen?"
)


def digest(folder: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.glob("*"))
        if p.is_file()
    }


def main() -> int:
    before = digest(DATA)
    sandbox = Path(tempfile.mkdtemp(prefix="pm-agentenlauf-"))
    tracking.PROJECT_FILE = sandbox / "projekt.json"
    lifecycle.FILE = sandbox / "vorhaben.json"
    workbench.TEAM_FILE = sandbox / "team.json"
    workbench.RUNS_CSV = sandbox / "runs.csv"
    shutil.copy(DATA / "projekt.json", tracking.PROJECT_FILE)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Logs: {OUT}")

    results: dict[str, str] = {}

    def step(name, call):
        started = time.monotonic()
        try:
            value = call()
        except Exception as err:  # noqa: BLE001 (recorded and shown; the next agents still run)
            results[name] = f"Fehler: {type(err).__name__}: {err}"
            traceback.print_exc()
            value = None
        else:
            results[name] = "ok"
        print(
            f"{name}: {results[name]} ({time.monotonic() - started:.0f} s)", flush=True
        )
        return value

    charter = step("auftrag", lambda: lifecycle.run_charter(PROJECT, log_dir=OUT))
    needs = step(
        "anforderungen",
        lambda: lifecycle.run_requirements(PROJECT, charter, log_dir=OUT),
    )
    design = step(
        "entwurf", lambda: lifecycle.run_design(PROJECT, charter, needs, log_dir=OUT)
    )
    step("testplan", lambda: lifecycle.run_cases(PROJECT, needs, design, log_dir=OUT))
    step("planung", lambda: agent.run_planning(PROJECT, TEAM, log_dir=OUT))
    trace = {"requirements": needs.items} if needs is not None else {}
    plan = step(
        "planung_mit_anforderungen",
        lambda: agent.run_planning(PROJECT, TEAM, log_dir=OUT, design=design, **trace),
    )
    for number, wish in enumerate(WISHES, start=1):
        if plan is None:
            results[f"umplanung_{number}"] = "nicht gelaufen: kein Plan"
            continue
        step(
            f"umplanung_{number}",
            lambda wish=wish: agent.run_replanning(
                PROJECT, TEAM, plan, wish, log_dir=OUT, design=design, **trace
            ),
        )
    adopted = tracking.load(tracking.PROJECT_FILE)
    step(
        "durchfuehrung",
        lambda: followup.run_status_summary(adopted, STAND, log_dir=OUT),
    )
    step("kontrolle", lambda: followup.run_control_report(adopted, STAND, log_dir=OUT))
    step("lessons", lambda: closing.run_lessons(adopted, STAND, log_dir=OUT))
    step("ki_lab", lambda: ki_lab_round(sandbox))

    after = digest(DATA)
    print(
        "data/ unverändert" if before == after else "WARNUNG: data/ hat sich geändert"
    )
    (OUT / "zusammenfassung-lauf.json").write_text(
        json.dumps({"results": results, "data_unchanged": before == after}, indent=2),
        encoding="utf-8",
    )
    return 0 if before == after else 1


def ki_lab_round(sandbox: Path) -> dict:
    """One question in the AI round of a pilot session of the KI-Lab, in a database of its own."""
    sys.path.insert(0, str(ROOT / "04-Prototyp" / "ki_lab"))
    from lab import Lab  # the lab is no package; it lives beside the site

    lab = Lab(sandbox / "lab.db")
    try:
        token = lab.create(group=2, pilot=True)[
            "token"
        ]  # group 2 starts with the AI round
        lab.start(token, consent=True, pm_experience="keine", ai_experience="nie")
        started = time.monotonic()
        answer = lab.ask(token, LAB_QUESTION)
        seconds = round(time.monotonic() - started, 1)
        state = lab.raw()[0]
        call = state["rounds"][0]["ai_calls"][-1]
        record = {
            "started": date.today().isoformat(),
            "seconds": seconds,
            "requested_model": call["model_requested"],
            "returned_model": call.get("model_returned"),
            "outcome": call["status"],
            "error": call["error"],
            "question": LAB_QUESTION,
            "answer": call["answer"],
            "usage": call.get("usage"),
            "reply": answer,
        }
        (OUT / f"ki_lab-{date.today():%Y%m%d}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return record
    finally:
        lab.close()


if __name__ == "__main__":
    sys.exit(main())
