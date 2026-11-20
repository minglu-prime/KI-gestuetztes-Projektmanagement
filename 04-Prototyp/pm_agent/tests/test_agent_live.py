"""Runs the agent against the real OpenAI API. It costs money and takes a few minutes, so it
is skipped without OPENAI_API_KEY. With the key in .env:

    uv run --env-file .env pytest tests/test_agent_live.py
"""

import os
from datetime import date

import pytest

from pm_agent.agent import run_planning
from pm_agent.models import Member, Project
from pm_agent.planning import check_plan

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY ist nicht gesetzt"
)


def test_agent_plans_a_small_project_without_errors_or_overload():
    project = Project(
        idea=(
            "Web-App, mit der Studierende Lernräume der Hochschule buchen: Anmeldung mit dem "
            "Hochschul-Login, Liste freier Räume, Buchen und Stornieren, Erinnerung per E-Mail."
        ),
        start_date=date(2026, 11, 9),
        deadline=date(2026, 12, 18),
    )
    # Six weeks with 47 h per week leave about 280 h, enough for such an app without overload.
    team = [
        Member(name="Anna", skills={"Python": 4, "SQL": 3}, hours_per_week=20),
        Member(name="Ben", skills={"React": 4, "CSS": 3}, hours_per_week=15),
        Member(name="Clara", skills={"Testing": 3, "UX": 4, "Python": 2}, hours_per_week=12),
    ]

    plan = run_planning(project, team)

    result = check_plan(plan, team, project)
    # ok: valid references, every task assigned once, no dependency cycle
    assert result.ok, result.errors
    assert all(load.utilization <= 1 + 1e-9 for load in result.load), result.warnings
