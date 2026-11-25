"""The tools the agents work with. The planning tools take the plan itself as input and run
the deterministic `planning.check_plan`, so the agent sees the same errors and warnings as the
project lead and corrects the plan itself. `Submission` is the same idea for one result with
one check, used by the agents for Durchführung and Kontrolle.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from pm_agent.models import (
    Absence,
    CheckResult,
    Member,
    MemberAbsence,
    Plan,
    Project,
    Requirement,
)
from pm_agent.planning import check_plan, missing_hours

T = TypeVar("T", bound=BaseModel)


class ToolError(Exception):
    """A tool rejects its input. `content` goes back to the model, which corrects the input."""

    def __init__(self, content: str) -> None:
        super().__init__(content)
        self.content = content


@dataclass(frozen=True)
class Tool:
    """A function the model can call: its name, what it does and the shape of its input."""

    run: Callable[..., str]
    name: str
    description: str
    input_schema: type[BaseModel]

    def call(self, data: dict[str, Any]) -> str:
        return self.run(**data)

    def definition(self) -> dict[str, Any]:
        """The tool as the OpenAI Responses API takes it. Not "strict": that mode allows no
        optional fields, and each tool validates its input itself."""
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema.model_json_schema(),
        }


# The schedule stays out: it is long, and the warnings already name late tasks.
REPORTED = {"errors", "warnings", "end_date", "critical_path", "load"}


def with_absences(team: list[Member], absences: list[MemberAbsence]) -> list[Member]:
    """The team with the absences added to their members (one they have stays once)."""
    changed = []
    for member in team:
        days = list(member.absences)
        for a in absences:
            away = Absence(first=a.first, last=a.last)
            if a.member == member.name and away not in days:
                days.append(away)
        changed.append(member.model_copy(update={"absences": days}))
    return changed


class PlanningTools:
    """The tools of one planning run. `plan` is set when submit_plan accepts a plan.
    `absences`: the run changes a plan on a wish, and the agent may set the absences the wish
    names (set_absence); every check after that counts them."""

    def __init__(
        self,
        project: Project,
        team: list[Member],
        requirements: list[Requirement] | None = None,
        covered: frozenset[str] = frozenset(),
        absences: bool = False,
    ) -> None:
        self.project = project
        self.team = team
        self.absences: list[MemberAbsence] = []
        self.set_absence = (
            Tool(
                self._set_absence,
                name="set_absence",
                description=(
                    "Trägt eine Abwesenheit ein, die der Wunsch der Projektleitung nennt: Person "
                    "aus dem Team, erster und letzter Tag (beide eingeschlossen). check_plan und "
                    "submit_plan rechnen danach mit ihr. Die Projektleitung sieht sie und "
                    "übernimmt sie mit dem Plan ins Team oder verwirft beides."
                ),
                input_schema=MemberAbsence,
            )
            if absences
            else None
        )
        # The approved requirements: with them the check traces each task (check_plan).
        self.requirements = requirements
        self.covered = covered
        self.plan: Plan | None = None
        self.check_plan = Tool(
            self._check,
            name="check_plan",
            description=(
                "Prüft einen Planentwurf deterministisch und rechnet dabei mit den "
                "Abwesenheiten des Teams. Liefert Fehler, Warnungen, Enddatum, kritischen Pfad "
                "und die Auslastung je Person bis zur Deadline."
            ),
            input_schema=Plan,
        )
        self.submit_plan = Tool(
            self._submit,
            name="submit_plan",
            description=(
                "Reicht den fertigen Plan bei der Projektleitung ein. Lehnt einen Plan mit "
                "Fehlern ab und nennt die Gründe, ebenso einen Plan, den eine mit set_absence "
                "eingetragene Abwesenheit hinter die Deadline schiebt, solange das Team bis dahin "
                "die Stunden dafür hat. Warnungen hindern die "
                "Einreichung nicht."
            ),
            input_schema=Plan,
        )

    def _set_absence(self, /, **data: Any) -> str:
        try:
            absence = MemberAbsence.model_validate(data)
        except ValidationError as err:
            raise ToolError("\n".join(invalid_input(err))) from None
        names = [m.name for m in self.team]
        if absence.member not in names:
            raise ToolError(f"Unbekannte Person '{absence.member}'. Im Team: {', '.join(names)}")
        if absence.last < self.project.start_date or absence.first > self.project.deadline:
            raise ToolError(
                "Die Abwesenheit liegt außerhalb des Projekts "
                f"({self.project.start_date:%d.%m.%Y} bis {self.project.deadline:%d.%m.%Y})."
            )
        if absence not in self.absences:
            self.absences.append(absence)
        return (
            f"Eingetragen: {absence.member} ist vom {absence.first:%d.%m.%Y} bis zum "
            f"{absence.last:%d.%m.%Y} abwesend."
        )

    def _check(self, /, **plan: Any) -> str:
        return self._review(plan)[1].model_dump_json(include=REPORTED)

    def _submit(self, /, **plan: Any) -> str:
        parsed, result = self._review(plan)
        errors = (too_long(parsed) if parsed else []) + result.errors
        if parsed and not errors:
            errors = self._late_by_absence(parsed, result)
        if errors:
            raise ToolError(
                "Plan abgelehnt. Behebe diese Fehler und reiche ihn erneut ein:\n"
                + "\n".join(f"- {error}" for error in errors)
            )
        self.plan = parsed
        return "Plan angenommen."

    def _late_by_absence(self, plan: Plan, result: CheckResult) -> list[str]:
        """An absence this run set must not push the plan past the deadline: then the agent
        has to move work to others (decision of the project lead, 23.11.2026). A plan that is
        late without the absences too stays a warning, as every late plan. So does one the
        team lacks the hours for: no redistribution can help, the project lead decides (D1,
        25.11.2026)."""
        deadline = self.project.deadline
        if not self.absences or result.end_date is None or result.end_date <= deadline:
            return []
        if missing_hours(plan, result.load):
            return []
        without = check_plan(
            plan, self.team, self.project, requirements=self.requirements, covered=self.covered
        )
        if without.end_date is None or without.end_date > deadline:
            return []
        return [
            f"Mit den Abwesenheiten endet der Plan am {result.end_date:%d.%m.%Y}, nach der "
            f"Deadline ({deadline:%d.%m.%Y}); ohne sie am {without.end_date:%d.%m.%Y}. Gib "
            "Aufgaben der abwesenden Person an andere im Team mit freien Stunden, möglichst "
            "mit passenden Fähigkeiten"
        ]

    def _review(self, data: dict[str, Any]) -> tuple[Plan | None, CheckResult]:
        try:
            plan = Plan.model_validate(data)
        except ValidationError as err:
            return None, CheckResult(errors=invalid_input(err))
        team = with_absences(self.team, self.absences)
        return plan, check_plan(
            plan, team, self.project, requirements=self.requirements, covered=self.covered
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


# The longest a free text of the agent may be, in characters: about one sentence, the
# summary three. The project lead reads every one of them. Only what the agent submits is
# held to this (`too_long`); the models take longer texts, so files saved before still load.
LIMITS = {
    "reason": 160,
    "purpose": 160,
    "action": 160,
    "effect": 160,
    "observation": 200,
    "advice": 200,
    "description": 240,
    "summary": 400,
}


def too_long(value: Any, where: str = "") -> list[str]:
    """Every text in `value` (a model, list or text) longer than its limit in LIMITS."""
    if isinstance(value, BaseModel):
        return [
            message
            for name in type(value).model_fields
            for message in too_long(getattr(value, name), f"{where}.{name}" if where else name)
        ]
    if isinstance(value, list):
        return [m for i, item in enumerate(value) for m in too_long(item, f"{where}.{i}")]
    limit = LIMITS.get(where.rsplit(".", 1)[-1])
    if isinstance(value, str) and limit is not None and len(value) > limit:
        return [f"Zu lang bei {where}: {len(value)} Zeichen, höchstens {limit} Zeichen. Kürze."]
    return []


class Submission(Generic[T]):
    """One submit tool. It accepts a result only if it parses and `check` finds no error;
    otherwise the agent gets the reasons and corrects the result. `result` is set on acceptance."""

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
        self.tool = Tool(self._submit, name=name, description=description, input_schema=schema)

    def _submit(self, /, **data: Any) -> str:
        try:
            parsed = self.schema.model_validate(data)
            errors = too_long(parsed) + self.check(parsed)
        except ValidationError as err:
            errors = invalid_input(err)
        if errors:
            raise ToolError(
                f"{self.noun} abgelehnt. Behebe diese Fehler und reiche ihn erneut ein:\n"
                + "\n".join(f"- {error}" for error in errors)
            )
        self.result = parsed
        return f"{self.noun} angenommen."
