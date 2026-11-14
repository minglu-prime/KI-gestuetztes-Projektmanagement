"""Data model: team and project (entered by the project lead), plan (proposed by the agent),
the result of checking a plan, and what the agents for Durchführung and Kontrolle propose.

Field-level rules live here. Rules that need several objects at once (unknown dependency,
member not in team, cycles) live in `planning.check_plan`, so a broken plan is reported,
not rejected on parse.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonEmpty = Annotated[str, Field(min_length=1)]
SkillLevel = Annotated[int, Field(ge=1, le=5)]


class _Model(BaseModel):
    # extra="forbid": a misspelled field from the LLM fails loudly instead of being dropped.
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class Member(_Model):
    name: NonEmpty
    skills: dict[NonEmpty, SkillLevel] = Field(default_factory=dict)
    # A week has 168 hours. Below 1 h a member cannot be planned, and tiny values
    # underflow to 0 h per workday.
    hours_per_week: float = Field(ge=1, le=7 * 24)
    note: str = ""


class Project(_Model):
    idea: NonEmpty
    start_date: date
    deadline: date

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


class Assignment(_Model):
    task_id: NonEmpty
    member: NonEmpty
    # Required: the project lead decides, so every proposal has to say why.
    reason: NonEmpty


class Plan(_Model):
    tasks: list[Task] = Field(min_length=1)
    assignments: list[Assignment]
    risks: list[NonEmpty] = Field(default_factory=list)


class ScheduledTask(_Model):
    task_id: str
    member: str
    start: date
    end: date


class MemberLoad(_Model):
    member: str
    assigned_hours: float
    capacity_hours: float  # available between start date and deadline
    utilization: float  # assigned / capacity; above 1.0 means overloaded


class CheckResult(_Model):
    errors: list[str] = Field(default_factory=list)  # plan cannot be scheduled until fixed
    warnings: list[str] = Field(default_factory=list)  # schedulable, project lead must decide
    schedule: list[ScheduledTask] = Field(default_factory=list)
    end_date: date | None = None
    critical_path: list[str] = Field(default_factory=list)
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
    effect: NonEmpty  # what the measure is expected to change


class ControlReport(_Model):
    """What the Kontrolle agent proposes: where the project stands and what to do about it."""

    assessment: Literal["im Plan", "gefährdet", "kritisch"]
    findings: list[Finding] = Field(min_length=1)
    measures: list[Measure] = Field(default_factory=list)
