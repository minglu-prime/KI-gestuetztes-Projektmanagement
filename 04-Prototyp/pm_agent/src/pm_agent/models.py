"""Data model: team and project (entered by the project lead), plan (proposed by the agent),
the result of checking a plan, and what the agents for Durchführung and Kontrolle propose.

Field-level rules live here. Rules that need several objects at once (unknown dependency,
member not in team, cycles) live in `planning.check_plan`, so a broken plan is reported,
not rejected on parse.
"""

import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

NonEmpty = Annotated[str, Field(min_length=1)]
SkillLevel = Annotated[int, Field(ge=1, le=5)]
# The ID of a success criterion or a requirement. No comma and no space: the plan table
# lists several of them in one cell, separated by commas.
Ref = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]+$")]


class _Model(BaseModel):
    # extra="forbid": a misspelled field from the LLM fails loudly instead of being dropped.
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class Absence(_Model):
    """Days on which a member, or the whole project, does not work, both ends included."""

    first: date
    last: date

    @model_validator(mode="after")
    def _not_backwards(self) -> "Absence":
        if self.last < self.first:
            raise ValueError("Das Ende der Abwesenheit liegt vor ihrem Beginn")
        return self


class Member(_Model):
    name: NonEmpty
    skills: dict[NonEmpty, SkillLevel] = Field(default_factory=dict)
    # The plan spreads the weekly hours over the five workdays: more than 5 x 24 h would
    # make a workday longer than a day. Below 1 h a member cannot be planned, and tiny
    # values underflow to 0 h per workday.
    hours_per_week: float = Field(ge=1, le=5 * 24)
    absences: list[Absence] = Field(default_factory=list)
    note: str = ""


class Project(_Model):
    idea: NonEmpty
    start_date: date
    deadline: date
    # Days on which nobody works: public holidays, a break. Mon-Fri days only count.
    free_days: list[Absence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _deadline_not_before_start(self) -> "Project":
        if self.deadline < self.start_date:
            raise ValueError("Die Deadline liegt vor dem Startdatum")
        return self


class Task(_Model):
    id: NonEmpty
    title: NonEmpty
    description: str = ""
    required_skills: list[NonEmpty] = Field(default_factory=list)
    estimate_hours: float = Field(gt=0, allow_inf_nan=False)
    depends_on: list[NonEmpty] = Field(default_factory=list)
    # The requirements this task serves. Empty in plans made before requirements existed.
    requirement_ids: list[Ref] = Field(default_factory=list)


class Assignment(_Model):
    task_id: NonEmpty
    member: NonEmpty
    # Required: the project lead decides, so every proposal has to say why.
    reason: NonEmpty


class Demo(_Model):
    """What the team shows at the end of a project week, and the tasks it needs."""

    week: int = Field(ge=1)  # week 1 is the week of the first workday of the project
    title: NonEmpty
    task_ids: list[NonEmpty] = Field(min_length=1)


class Plan(_Model):
    tasks: list[Task] = Field(min_length=1)
    assignments: list[Assignment]
    risks: list[NonEmpty] = Field(default_factory=list)
    # One demo per project week. Empty in plans made before demos existed.
    demos: list[Demo] = Field(default_factory=list)


class Criterion(_Model):
    """A success criterion of the project: how to tell at the end that it worked."""

    id: Ref
    text: NonEmpty


class Charter(_Model):
    """Projektauftrag: why the project exists, what belongs to it and when it has succeeded.
    Claude drafts it from the idea; the project lead changes and approves it."""

    goal: NonEmpty
    benefit: NonEmpty
    in_scope: list[NonEmpty] = Field(min_length=1)
    out_of_scope: list[NonEmpty] = Field(default_factory=list)
    stakeholders: list[NonEmpty] = Field(default_factory=list)  # roles, not names
    success_criteria: list[Criterion] = Field(min_length=1)
    constraints: list[NonEmpty] = Field(default_factory=list)


def _no_semicolon(text: str) -> str:
    if ";" in text:
        raise ValueError("darf kein Semikolon enthalten")
    return text


class Acceptance(_Model):
    """An acceptance criterion: its ID ("R1.1") stays when others are deleted, so a test
    case keeps pointing at the same criterion."""

    id: Ref
    text: Annotated[NonEmpty, AfterValidator(_no_semicolon)]


def _number_criteria(data: Any) -> Any:
    """Plain texts become criteria with the next free number of their requirement: R1.1,
    R1.2 … A deleted number is not given again."""
    if not isinstance(data, dict) or not isinstance(data.get("criteria"), list):
        return data
    rid = str(data.get("id", "")).strip()
    # An invalid requirement ID is reported on its own; the criteria then get a neutral
    # prefix instead of a second message about the same mistake.
    prefix = f"{rid}." if re.fullmatch(r"[A-Za-z0-9._-]+", rid) else "R."
    used = [
        c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
        for c in data["criteria"]
        if not isinstance(c, str)
    ]
    numbers = [
        int(i[len(prefix) :])
        for i in used
        if isinstance(i, str) and i.startswith(prefix) and i[len(prefix) :].isdigit()
    ]
    following = max(numbers, default=0)
    criteria = []
    for item in data["criteria"]:
        if isinstance(item, str):
            following += 1
            item = {"id": f"{prefix}{following}", "text": item}
        criteria.append(item)
    return {**data, "criteria": criteria}


class Requirement(_Model):
    """One requirement of the PRD, with the criteria for accepting it."""

    _numbered = model_validator(mode="before")(_number_criteria)

    id: Ref
    title: NonEmpty
    story: NonEmpty  # who wants what, and why
    priority: Literal["Muss", "Soll", "Kann"]
    # Acceptance criteria. Plain texts get IDs (_number_criteria).
    criteria: list[Acceptance] = Field(min_length=1)
    sources: list[Ref] = Field(default_factory=list)  # success criteria of the charter


class Requirements(_Model):
    items: list[Requirement] = Field(min_length=1)


# A field of an interface: written "name: Typ" in the table, several separated by commas.
FieldName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
TypeName = Annotated[str, Field(min_length=1, pattern=r"^[^,;:]+$")]


class DataField(_Model):
    name: FieldName
    type: TypeName
    required: bool = True


class ErrorCase(_Model):
    """An error an interface answers with: "409 Raum belegt" in the table."""

    code: Ref
    meaning: Annotated[NonEmpty, AfterValidator(_no_semicolon)]


class Component(_Model):
    """A part of the system, a role that uses it, or a system outside the project."""

    id: Ref
    name: NonEmpty
    kind: Literal["Rolle", "Komponente", "Fremdsystem"]
    purpose: str = ""


class Interface(_Model):
    """The contract between a provider and its consumers."""

    id: Ref
    name: NonEmpty
    provider: Ref
    consumers: list[Ref] = Field(min_length=1)
    input: list[DataField] = Field(default_factory=list)
    output: list[DataField] = Field(default_factory=list)
    errors: list[ErrorCase] = Field(default_factory=list)


class Step(_Model):
    """One arrow of a sequence diagram. A call goes to the provider of `interface`, an
    answer comes back from it; a step without interface is, say, a role using the UI."""

    sender: Ref
    receiver: Ref
    kind: Literal["Aufruf", "Antwort"] = "Aufruf"
    interface: Ref | None = None
    text: str = ""


class Flow(_Model):
    id: Ref
    title: NonEmpty
    requirement_ids: list[Ref] = Field(default_factory=list)
    steps: list[Step] = Field(min_length=1)


class Design(_Model):
    """Entwurf: the parts of the system, their contracts and the flows between them.
    Python draws the sequence diagrams from it; Claude never writes diagram code."""

    components: list[Component] = Field(min_length=1)
    interfaces: list[Interface] = Field(default_factory=list)
    flows: list[Flow] = Field(min_length=1)


class Case(_Model):
    """A test case: an acceptance test for criteria of the requirements, or an integration
    test of an interface of the design (with `error_code`: the case that provokes it)."""

    id: Ref
    title: NonEmpty
    kind: Literal["Akzeptanz", "Integration"]
    criteria: list[Ref] = Field(default_factory=list)  # R1.1 …
    interface: Ref | None = None  # S1
    error_code: Ref | None = None  # 409
    # No semicolon: it separates the steps in the table.
    steps: list[Annotated[NonEmpty, AfterValidator(_no_semicolon)]] = Field(min_length=1)
    expected: NonEmpty


class Cases(_Model):
    """The test plan. Not "TestPlan": pytest would take a class named Test… for tests."""

    cases: list[Case] = Field(min_length=1)


class Lesson(_Model):
    """What the team does differently next time, and what it rests on."""

    observation: NonEmpty
    advice: NonEmpty
    refs: list[NonEmpty] = Field(default_factory=list)  # defect IDs, Mondays of weeks


class Lessons(_Model):
    items: list[Lesson] = Field(min_length=1)


class ScheduledTask(_Model):
    task_id: str
    member: str
    start: date
    end: date


class MemberLoad(_Model):
    member: str
    assigned_hours: float
    capacity_hours: float  # available between start date and deadline
    # assigned / capacity; above 1.0 means overloaded. None: away until the deadline.
    utilization: float | None


class CheckResult(_Model):
    errors: list[str] = Field(default_factory=list)  # plan cannot be scheduled until fixed
    warnings: list[str] = Field(default_factory=list)  # schedulable, project lead must decide
    # One entry per warning, in the same order: what it is about, without the numbers in
    # its text: ("late",), ("buffer",), ("overload", "Anna"), ("away", "Anna"),
    # ("skill", "T1", "SQL"). Two checks of a changed plan are compared by these, so a
    # warning whose numbers moved is not taken for a new one. Tuples, not joined strings:
    # an ID or a skill can contain any separator.
    warning_kinds: list[tuple[str, ...]] = Field(default_factory=list)
    schedule: list[ScheduledTask] = Field(default_factory=list)  # in the order of the plan
    # Task IDs in the order they were scheduled: whatever could start earliest, next.
    order: list[str] = Field(default_factory=list)
    end_date: date | None = None
    critical_path: list[str] = Field(default_factory=list)
    # Task ID -> whole workdays the task can start later without moving the end of the plan.
    slack: dict[str, int] = Field(default_factory=dict)
    load: list[MemberLoad] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class NextStep(_Model):
    task_id: NonEmpty
    action: NonEmpty


class StatusSummary(_Model):
    """What the Durchführung agent proposes for the status report."""

    summary: NonEmpty
    next_steps: list[NextStep] = Field(default_factory=list)


class Finding(_Model):
    task_ids: list[NonEmpty] = Field(default_factory=list)  # empty: about the whole project
    observation: NonEmpty


class Measure(_Model):
    task_ids: list[NonEmpty] = Field(min_length=1)
    action: NonEmpty
    effect: NonEmpty  # what the measure is expected to change, in Claude's words
    # Set if the measure gives its tasks to this team member. Python then computes what that
    # does to the forecast, so the effect is not only claimed.
    reassign_to: NonEmpty | None = None


class ControlReport(_Model):
    """What the Kontrolle agent proposes: where the project stands and what to do about it."""

    assessment: Literal["im Plan", "gefährdet", "kritisch"]
    findings: list[Finding] = Field(min_length=1)
    measures: list[Measure] = Field(default_factory=list)
