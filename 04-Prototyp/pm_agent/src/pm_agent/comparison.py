"""Structured choice-based efficiency comparison (with vs. without agent) across the four
core execution phases: Planung, Durchführung, Kontrolle and Abschluss.

Pure Python (no Streamlit), reusing `workbench`'s append-only CSV engine
(`logs/agent_vergleich.csv`, git-ignored). Subjective workflow ratings complement the controlled
blinded KI-Lab study and are paired automatically with objective metrics from the latest valid
agent run log of that phase.
"""

import csv
import io
import json
import math
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from pm_agent import agent as agents
from pm_agent import workbench

# Read at call time so tests and scripts can redirect logs without touching real files.
COMPARISON_CSV = agents.LOG_DIR / "agent_vergleich.csv"

SCHEMA_VERSION = "1"
MAX_NOTE_LENGTH = 400
MANUAL_MODE = "Ohne Agent (manuell)"
NOT_APPLICABLE = "Nicht anwendbar (ohne Agent)"
DASH = "–"

PhaseId = Literal["planung", "durchfuehrung", "kontrolle", "abschluss"]
PHASE_ORDER: tuple[PhaseId, ...] = ("planung", "durchfuehrung", "kontrolle", "abschluss")


@dataclass(frozen=True)
class Question:
    """One closed-choice question of the efficiency comparison."""

    id: str
    short_label: str
    label: str
    options: tuple[str, ...]


COMMON_QUESTIONS: tuple[Question, ...] = (
    Question(
        id="mode",
        short_label="Arbeitsweise",
        label="Wie hast du diese Phase bearbeitet?",
        options=(
            "Mit Agent (Vorschlag weitgehend genutzt)",
            "Mit Agent (Vorschlag deutlich angepasst)",
            "Mit Agent (Vorschlag verworfen)",
            MANUAL_MODE,
        ),
    ),
    Question(
        id="time_comparison",
        short_label="Zeitvergleich",
        label="Wie war der Zeitaufwand im Vergleich zur Arbeit ohne Agent?",
        options=(
            "Deutlich schneller (> 50 % gespart)",
            "Etwas schneller (20–50 %)",
            "Etwa gleich",
            "Etwas langsamer (mehr Prüfaufwand)",
            "Deutlich langsamer",
            NOT_APPLICABLE,
        ),
    ),
    Question(
        id="manual_estimate",
        short_label="Manuelle Zeitschätzung",
        label="Wie lange hätte diese Aufgabe ohne Agent schätzungsweise gedauert?",
        options=(
            "< 10 min",
            "10–20 min",
            "20–40 min",
            "40–60 min",
            "> 60 min",
        ),
    ),
    Question(
        id="quality_comparison",
        short_label="Qualitätsvergleich",
        label="Wie bewertest du die Ergebnisqualität im Vergleich zur Arbeit ohne Agent?",
        options=(
            "Deutlich besser",
            "Etwas besser",
            "Gleichwertig",
            "Etwas schlechter",
            "Deutlich schlechter",
            NOT_APPLICABLE,
        ),
    ),
    Question(
        id="workload_change",
        short_label="Arbeitsbelastung",
        label="Wie hat sich deine Arbeitsbelastung (inkl. Prüfen und Nachbessern) verändert?",
        options=(
            "Deutlich geringer",
            "Etwas geringer",
            "Unverändert",
            "Etwas höher",
            "Deutlich höher",
            NOT_APPLICABLE,
        ),
    ),
)

_COMMON_OPTIONS: dict[str, tuple[str, ...]] = {q.id: q.options for q in COMMON_QUESTIONS}


@dataclass(frozen=True)
class PhaseSpec:
    """Configuration for one core phase: display name, log prefix and phase-specific choices."""

    id: PhaseId
    label: str
    log_prefix: str
    questions: tuple[Question, Question]


PHASES: dict[PhaseId, PhaseSpec] = {
    "planung": PhaseSpec(
        id="planung",
        label="Planung",
        log_prefix="run",
        questions=(
            Question(
                id="phase_q1",
                short_label="Größter Nutzen (Planung)",
                label="Wo hat der Planungs-Agent am meisten geholfen?",
                options=(
                    "Aufgaben zerlegen",
                    "Aufwand schätzen",
                    "Zuweisung nach Skills & Kapazität",
                    "Risiken & Wochen-Demos",
                    "Umplanen bei Änderungen",
                    "Kaum hilfreich",
                    "Ohne Agent gearbeitet",
                ),
            ),
            Question(
                id="phase_q2",
                short_label="Nutzen der Python-Prüfung",
                label=(
                    "Hat die Python-Prüfung Probleme gefunden, die manuell leicht übersehen "
                    "worden wären?"
                ),
                options=("Ja, mehrere", "Ja, vereinzelt", "Nein", "Nicht genutzt"),
            ),
        ),
    ),
    "durchfuehrung": PhaseSpec(
        id="durchfuehrung",
        label="Durchführung",
        log_prefix="durchfuehrung",
        questions=(
            Question(
                id="phase_q1",
                short_label="Brauchbarkeit Statusentwurf",
                label="Wie brauchbar war der Entwurf für Statusbericht und nächste Schritte?",
                options=(
                    "Sofort nutzbar",
                    "Guter Startpunkt",
                    "Zu allgemein",
                    "Unzutreffend",
                    "Ohne Agent gearbeitet",
                ),
            ),
            Question(
                id="phase_q2",
                short_label="Hervorhebung von Verzug",
                label="Hat der Agent überfällige Aufgaben klarer hervorgehoben als die Tabelle?",
                options=(
                    "Ja, deutlich",
                    "Etwas",
                    "Nein, Tabelle reichte",
                    "Ohne Agent gearbeitet",
                ),
            ),
        ),
    ),
    "kontrolle": PhaseSpec(
        id="kontrolle",
        label="Kontrolle",
        log_prefix="kontrolle",
        questions=(
            Question(
                id="phase_q1",
                short_label="Nutzen der Gegenmaßnahmen",
                label="Wie hilfreich waren Bewertung und Gegenmaßnahmen des Kontroll-Agenten?",
                options=(
                    "Neue umsetzbare Maßnahme",
                    "Bekannte Lage gut gebündelt",
                    "Zu pauschal",
                    "Unzutreffend",
                    "Ohne Agent gearbeitet",
                ),
            ),
            Question(
                id="phase_q2",
                short_label="Python-Nachrechnung",
                label="Wie nützlich war die Python-Nachrechnung der Umverteilungswirkung?",
                options=(
                    "Sehr nützlich",
                    "Hilfreich",
                    "Kaum genutzt",
                    "Keine Umverteilung vorgeschlagen",
                ),
            ),
        ),
    ),
    "abschluss": PhaseSpec(
        id="abschluss",
        label="Abschluss",
        log_prefix="lessons",
        questions=(
            Question(
                id="phase_q1",
                short_label="Qualität der Lessons Learned",
                label=(
                    "Wie gut hat der Agent aus Rückblicken und Fehlern Lessons Learned abgeleitet?"
                ),
                options=(
                    "Neue Zusammenhänge erkannt",
                    "Gute Strukturierung",
                    "Nur Offensichtliches",
                    "Unzutreffend",
                    "Ohne Agent gearbeitet",
                ),
            ),
            Question(
                id="phase_q2",
                short_label="Nutzen der Pflichtbezüge",
                label=(
                    "Waren die verpflichtenden Bezüge (Fehler-ID / Woche) hilfreich für die "
                    "Nachvollziehbarkeit?"
                ),
                options=("Ja, sehr", "Etwas", "Nein", "Ohne Agent gearbeitet"),
            ),
        ),
    ),
}

COLUMNS = [
    "schema_version",
    "entry_id",
    "erfasst",
    "phase",
    "phase_name",
    "arbeitsweise",
    "zeitvergleich",
    "manuell_geschaetzt",
    "qualitaetsvergleich",
    "belastung",
    "phase_frage_1",
    "phase_frage_2",
    "notiz",
    "lauf_datei",
    "agent_sekunden",
    "runden",
    "eingabe_token",
    "ausgabe_token",
    "modell",
    "pruefung_sekunden",
    "angepasst",
]

_FLOAT_COLUMNS = {"agent_sekunden", "pruefung_sekunden"}
_INPUT_TOKEN_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def questions_for(phase: PhaseId) -> tuple[Question, ...]:
    """All required choice questions for `phase`: common cross-phase items followed by its two
    phase-specific items."""
    if phase not in PHASES:
        raise ValueError(f"Unbekannte Phase: '{phase}'")
    return COMMON_QUESTIONS + PHASES[phase].questions


def _reject_bool(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("muss eine Zahl sein")
    return value


class RunMetrics(BaseModel):
    """Objective telemetry from one valid logged agent run."""

    model_config = ConfigDict(extra="forbid")

    log_file: str = Field(min_length=1)
    outcome: str = ""
    seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    rounds: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    model: str = ""

    @field_validator("seconds", "rounds", "input_tokens", "output_tokens", mode="before")
    @classmethod
    def _no_bool_numbers(cls, value: Any) -> Any:
        return _reject_bool(value)


class RunLookup(NamedTuple):
    """Latest valid run of a phase, plus newer corrupt log filenames that had to be skipped."""

    metrics: RunMetrics | None
    skipped_corrupt: list[str]


def _non_negative_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Tokenzahl ungültig")
    return value


def _parse_run_log(path: Path) -> RunMetrics:
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError("kein JSON-Objekt")
    rounds_raw = record.get("rounds", [])
    if not isinstance(rounds_raw, list) or not all(isinstance(r, dict) for r in rounds_raw):
        raise ValueError("rounds ist keine Liste aus Objekten")
    raw_seconds = record.get("seconds")
    seconds: float | None
    if raw_seconds is None:
        seconds = None
    elif (
        isinstance(raw_seconds, bool)
        or not isinstance(raw_seconds, int | float)
        or not math.isfinite(raw_seconds)
        or raw_seconds < 0
    ):
        raise ValueError("seconds ungültig")
    else:
        seconds = round(float(raw_seconds), 1)

    input_tokens = 0
    output_tokens = 0
    returned_model = ""
    for item in rounds_raw:
        usage = item.get("usage")
        if usage is not None:
            if not isinstance(usage, dict):
                raise ValueError("usage ist kein Objekt")
            for key in _INPUT_TOKEN_KEYS:
                input_tokens += _non_negative_int(usage.get(key))
            output_tokens += _non_negative_int(usage.get("output_tokens"))
        round_model = item.get("model")
        if isinstance(round_model, str) and round_model.strip():
            returned_model = round_model.strip()

    requested_model = record.get("requested_model")
    model = returned_model or (requested_model.strip() if isinstance(requested_model, str) else "")
    outcome = record.get("outcome")
    return RunMetrics(
        log_file=path.name,
        outcome=outcome.strip() if isinstance(outcome, str) else "",
        seconds=seconds,
        rounds=len(rounds_raw),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )


def latest_run_metrics(phase: PhaseId, log_dir: Path | None = None) -> RunLookup:
    """Metrics of the newest valid agent log for `phase`. Newer unreadable or malformed logs are
    skipped and explicitly reported in `skipped_corrupt` rather than hidden silently."""
    if phase not in PHASES:
        raise ValueError(f"Unbekannte Phase: '{phase}'")
    folder = log_dir if log_dir is not None else agents.LOG_DIR
    if not folder.is_dir():
        return RunLookup(None, [])
    prefix = PHASES[phase].log_prefix
    candidates = sorted(
        folder.glob(f"{prefix}-*.json"),
        key=lambda p: p.name.removeprefix(f"{prefix}-"),
        reverse=True,
    )
    skipped: list[str] = []
    for path in candidates:
        try:
            metrics = _parse_run_log(path)
        except (OSError, ValueError, TypeError, ValidationError):
            skipped.append(path.name)
            continue
        return RunLookup(metrics, skipped)
    return RunLookup(None, skipped)


class ComparisonEntry(BaseModel):
    """One submitted subjective efficiency rating, optionally paired with objective run data."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    entry_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    submitted_at: datetime = Field(
        default_factory=lambda: datetime.now().astimezone().replace(microsecond=0)
    )
    phase: PhaseId
    mode: str
    time_comparison: str
    manual_estimate: str
    quality_comparison: str
    workload_change: str
    phase_q1: str
    phase_q2: str
    note: str = Field(default="", max_length=MAX_NOTE_LENGTH)

    log_file: str = ""
    agent_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    agent_rounds: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    model: str = ""
    review_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    edited: bool | None = None

    @field_validator(
        "agent_seconds",
        "agent_rounds",
        "input_tokens",
        "output_tokens",
        "review_seconds",
        mode="before",
    )
    @classmethod
    def _no_bool_numbers(cls, value: Any) -> Any:
        return _reject_bool(value)

    @field_validator("submitted_at")
    @classmethod
    def _aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Zeitstempel braucht eine Zeitzone")
        return value

    @model_validator(mode="after")
    def _valid_choices(self) -> "ComparisonEntry":
        for field_name, allowed in _COMMON_OPTIONS.items():
            chosen = getattr(self, field_name)
            if chosen not in allowed:
                raise ValueError(f"Ungültige Auswahl für {field_name}: '{chosen}'")
        q1, q2 = PHASES[self.phase].questions
        if self.phase_q1 not in q1.options:
            raise ValueError(f"Ungültige Auswahl für {q1.id}: '{self.phase_q1}'")
        if self.phase_q2 not in q2.options:
            raise ValueError(f"Ungültige Auswahl für {q2.id}: '{self.phase_q2}'")
        return self


def entry_to_row(entry: ComparisonEntry) -> dict[str, Any]:
    """Serialize one validated entry into the fixed CSV column order."""
    return {
        "schema_version": entry.schema_version,
        "entry_id": entry.entry_id,
        "erfasst": entry.submitted_at.isoformat(timespec="seconds"),
        "phase": entry.phase,
        "phase_name": PHASES[entry.phase].label,
        "arbeitsweise": entry.mode,
        "zeitvergleich": entry.time_comparison,
        "manuell_geschaetzt": entry.manual_estimate,
        "qualitaetsvergleich": entry.quality_comparison,
        "belastung": entry.workload_change,
        "phase_frage_1": entry.phase_q1,
        "phase_frage_2": entry.phase_q2,
        "notiz": entry.note,
        "lauf_datei": entry.log_file,
        "agent_sekunden": "" if entry.agent_seconds is None else entry.agent_seconds,
        "runden": "" if entry.agent_rounds is None else entry.agent_rounds,
        "eingabe_token": "" if entry.input_tokens is None else entry.input_tokens,
        "ausgabe_token": "" if entry.output_tokens is None else entry.output_tokens,
        "modell": entry.model,
        "pruefung_sekunden": "" if entry.review_seconds is None else entry.review_seconds,
        "angepasst": "" if entry.edited is None else entry.edited,
    }


def record_comparison(entry: ComparisonEntry, path: Path | None = None) -> dict[str, Any]:
    """Append one comparison entry to `agent_vergleich.csv` using `workbench.append_run`.
    Thread-safe within one server process; does not coordinate multiple server processes."""
    target = path if path is not None else COMPARISON_CSV
    row = entry_to_row(entry)
    workbench.append_run(row, target)
    return row


def read_comparisons(path: Path | None = None) -> list[dict[str, str]]:
    """Read `agent_vergleich.csv` with the same strict record check used for `runs.csv`."""
    target = path if path is not None else COMPARISON_CSV
    return workbench.read_runs(target)


def put_aside_comparisons(path: Path | None = None) -> list[str]:
    """Archived incompatible comparison files put aside next to `agent_vergleich.csv`."""
    target = path if path is not None else COMPARISON_CSV
    return workbench.put_aside(target)


def _parse_float(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _german_number(value: float | None, unit: str = "") -> str:
    if value is None:
        return DASH
    formatted = f"{round(value, 1):g}".replace(".", ",")
    return f"{formatted} {unit}".strip()


def _timestamp_key(index: int, row: dict[str, str]) -> tuple[int, float, int]:
    """Sort key picking the newest valid ISO timestamp; ties keep the later CSV row."""
    raw = (row.get("erfasst") or "").strip()
    if raw:
        try:
            return (1, datetime.fromisoformat(raw).timestamp(), index)
        except ValueError:
            pass
    return (0, 0.0, index)


def summarize_comparisons(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Aggregate comparison rows across the four core phases.

    Keeps full history in the CSV while reporting each phase's latest valid submission alongside
    counts and medians of objective agent metrics, so repeated entries in one phase do not skew
    cross-phase comparisons. Bucket answers are never converted into invented saved hours.
    """
    grouped: dict[PhaseId, list[tuple[int, dict[str, str]]]] = {phase: [] for phase in PHASE_ORDER}
    for index, row in enumerate(rows):
        phase = (row.get("phase") or "").strip()
        if phase in grouped:
            grouped[phase].append((index, row))
    if not any(grouped.values()):
        return []

    summary: list[dict[str, Any]] = []
    for phase in PHASE_ORDER:
        entries = grouped[phase]
        spec = PHASES[phase]
        if not entries:
            summary.append(
                {
                    "Phase": spec.label,
                    "Einträge": 0,
                    "Mit Agent": 0,
                    "Ohne Agent": 0,
                    "Letzte Arbeitsweise": DASH,
                    "Letzter Zeitvergleich": DASH,
                    "Letzte Qualität": DASH,
                    "Letzte manuelle Schätzung": DASH,
                    "Median Agent (s)": DASH,
                    "Median Runden": DASH,
                }
            )
            continue
        _, latest = max(entries, key=lambda pair: _timestamp_key(pair[0], pair[1]))
        manual = sum((row.get("arbeitsweise") or "").strip() == MANUAL_MODE for _, row in entries)
        with_agent = len(entries) - manual
        seconds = [
            value
            for _, row in entries
            if (value := _parse_float(row.get("agent_sekunden"))) is not None
        ]
        rounds = [
            value for _, row in entries if (value := _parse_float(row.get("runden"))) is not None
        ]
        summary.append(
            {
                "Phase": spec.label,
                "Einträge": len(entries),
                "Mit Agent": with_agent,
                "Ohne Agent": manual,
                "Letzte Arbeitsweise": (latest.get("arbeitsweise") or "").strip() or DASH,
                "Letzter Zeitvergleich": (latest.get("zeitvergleich") or "").strip() or DASH,
                "Letzte Qualität": (latest.get("qualitaetsvergleich") or "").strip() or DASH,
                "Letzte manuelle Schätzung": (latest.get("manuell_geschaetzt") or "").strip()
                or DASH,
                "Median Agent (s)": _german_number(statistics.median(seconds) if seconds else None),
                "Median Runden": _german_number(statistics.median(rounds) if rounds else None),
            }
        )
    return summary


def to_comparison_csv(rows: list[dict[str, str]]) -> str:
    """Export comparison rows for German Excel: UTF-8 BOM, semicolon delimiter, decimal commas
    for floats and formula-prefix protection on every text cell via `workbench.csv_cell`."""
    out = io.StringIO()
    out.write("\ufeff")
    writer = csv.writer(out, delimiter=";")
    writer.writerow(COLUMNS)
    for row in rows:
        cells = []
        for column in COLUMNS:
            raw = row.get(column, "")
            if column in _FLOAT_COLUMNS:
                parsed = _parse_float(raw)
                cells.append(workbench.csv_cell(parsed) if parsed is not None else "")
            else:
                cells.append(workbench.csv_cell(raw))
        writer.writerow(cells)
    return out.getvalue()
