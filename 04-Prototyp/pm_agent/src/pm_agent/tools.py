"""The tools the agents work with. The planning tools take the plan itself as input and run
the deterministic `planning.check_plan`, so Claude sees the same errors and warnings as the
project lead and corrects the plan itself. `Submission` is the same idea for one result with
one check, used by the agents for Durchführung and Kontrolle.
"""

from collections.abc import Callable
from typing import Any, Generic, TypeVar

from anthropic import beta_tool
from anthropic.lib.tools import ToolError
from pydantic import BaseModel, ValidationError

from pm_agent.models import CheckResult, Member, Plan, Project, Requirement
from pm_agent.planning import check_plan

T = TypeVar("T", bound=BaseModel)

# The schedule stays out: it is long, and the warnings already name late tasks.
REPORTED = {"errors", "warnings", "end_date", "critical_path", "load"}


class PlanningTools:
    """The tools of one planning run. `plan` is set when submit_plan accepts a plan."""

    def __init__(
        self,
        project: Project,
        team: list[Member],
        requirements: list[Requirement] | None = None,
        covered: frozenset[str] = frozenset(),
    ) -> None:
        self.project = project
        self.team = team
        # The approved requirements: with them the check traces each task (check_plan).
        self.requirements = requirements
        self.covered = covered
        self.plan: Plan | None = None
        self.check_plan = beta_tool(
            self._check,
            name="check_plan",
            description=(
                "Prüft einen Planentwurf deterministisch und rechnet dabei mit den "
                "Abwesenheiten des Teams. Liefert Fehler, Warnungen, Enddatum, kritischen Pfad "
                "und die Auslastung je Person bis zur Deadline."
            ),
            input_schema=Plan,
        )
        self.submit_plan = beta_tool(
            self._submit,
            name="submit_plan",
            description=(
                "Reicht den fertigen Plan bei der Projektleitung ein. Lehnt einen Plan mit "
                "Fehlern ab und nennt die Gründe. Warnungen hindern die Einreichung nicht."
            ),
            input_schema=Plan,
        )

    def _check(self, /, **plan: Any) -> str:
        return self._review(plan)[1].model_dump_json(include=REPORTED)

    def _submit(self, /, **plan: Any) -> str:
        parsed, result = self._review(plan)
        if result.errors:
            raise ToolError(
                "Plan abgelehnt. Behebe diese Fehler und reiche ihn erneut ein:\n"
                + "\n".join(f"- {error}" for error in result.errors)
            )
        self.plan = parsed
        return "Plan angenommen."

    def _review(self, data: dict[str, Any]) -> tuple[Plan | None, CheckResult]:
        try:
            plan = Plan.model_validate(data)
        except ValidationError as err:
            return None, CheckResult(errors=invalid_input(err))
        return plan, check_plan(
            plan, self.team, self.project, requirements=self.requirements, covered=self.covered
        )


# The project lead reads these too (each round is shown on the page): German for the usual
# slips, pydantic's English text for the rest.
GERMAN = {
    "missing": "Feld fehlt",
    "extra_forbidden": "Feld ist nicht vorgesehen",
    "greater_than": "muss größer als {gt} sein",
    "greater_than_equal": "muss mindestens {ge} sein",
    "less_than_equal": "darf höchstens {le} sein",
    "string_too_short": "darf nicht leer sein",
    "too_short": "braucht mindestens {min_length} Einträge",
    "string_type": "muss Text sein",
    "float_type": "muss eine Zahl sein",
    "float_parsing": "muss eine Zahl sein",
    "int_type": "muss eine ganze Zahl sein",
    "int_parsing": "muss eine ganze Zahl sein",
    "finite_number": "muss eine endliche Zahl sein",
    "list_type": "muss eine Liste sein",
    "dict_type": "muss ein Objekt sein",
    "model_type": "muss ein Objekt sein",
    "string_pattern_mismatch": "darf nur Buchstaben, Ziffern, Punkt, Binde- und Unterstrich "
    "enthalten",
    "literal_error": "muss {expected} sein",
    "date_type": "muss ein Datum sein, z. B. 2026-12-01",
    "date_parsing": "muss ein Datum sein, z. B. 2026-12-01",
    "date_from_datetime_parsing": "muss ein Datum sein, z. B. 2026-12-01",
    "date_from_datetime_inexact": "muss ein Datum ohne Uhrzeit sein",
}


def german(e: Any) -> str:
    """What is wrong in one pydantic error, in German where GERMAN knows the type."""
    # Limits as written in German: 0 and 7,5, not 0.0 and 7.5.
    limits = {
        key: f"{value:g}".replace(".", ",") if isinstance(value, float) else value
        for key, value in e.get("ctx", {}).items()
    }
    if isinstance(limits.get("expected"), str):  # "'Muss', 'Soll' or 'Kann'"
        limits["expected"] = limits["expected"].replace("'", "").replace(" or ", " oder ")
    if e["type"] == "value_error":  # our own validators speak German already
        return e["msg"].removeprefix("Value error, ")
    if e["type"] in GERMAN:
        return GERMAN[e["type"]].format(**limits)
    return e["msg"]


def invalid_input(err: ValidationError) -> list[str]:
    messages = []
    for e in err.errors():
        where = ".".join(map(str, e["loc"]))
        text = german(e)
        messages.append(
            f"Ungültige Eingabe bei {where}: {text}" if where else f"Ungültige Eingabe: {text}"
        )
    return messages


class Submission(Generic[T]):
    """One submit tool. It accepts a result only if it parses and `check` finds no error;
    otherwise Claude gets the reasons and corrects the result. `result` is set on acceptance."""

    def __init__(
        self,
        name: str,
        noun: str,
        description: str,
        schema: type[T],
        check: Callable[[T], list[str]],
    ) -> None:
        self.noun = noun
        self.schema = schema
        self.check = check
        self.result: T | None = None
        self.tool = beta_tool(self._submit, name=name, description=description, input_schema=schema)

    def _submit(self, /, **data: Any) -> str:
        try:
            parsed = self.schema.model_validate(data)
            errors = self.check(parsed)
        except ValidationError as err:
            errors = invalid_input(err)
        if errors:
            raise ToolError(
                f"{self.noun} abgelehnt. Behebe diese Fehler und reiche ihn erneut ein:\n"
                + "\n".join(f"- {error}" for error in errors)
            )
        self.result = parsed
        return f"{self.noun} angenommen."
