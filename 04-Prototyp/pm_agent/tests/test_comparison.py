"""Unit, file-robustness and isolated widget tests for the agent efficiency comparison."""

import csv
import io
import json
import math
import threading
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from pm_agent import agent, comparison, tracking, workbench
from pm_agent.comparison import (
    COLUMNS,
    COMMON_QUESTIONS,
    MANUAL_MODE,
    MAX_NOTE_LENGTH,
    NOT_APPLICABLE,
    PHASE_ORDER,
    PHASES,
    ComparisonEntry,
    latest_run_metrics,
    put_aside_comparisons,
    questions_for,
    read_comparisons,
    record_comparison,
    summarize_comparisons,
    to_comparison_csv,
)
from pm_agent.workbench import InputError


def sample_answers(phase: str = "planung", *, manual: bool = False) -> dict[str, str]:
    q1, q2 = PHASES[phase].questions
    return {
        "mode": MANUAL_MODE if manual else COMMON_QUESTIONS[0].options[0],
        "time_comparison": NOT_APPLICABLE if manual else COMMON_QUESTIONS[1].options[0],
        "manual_estimate": COMMON_QUESTIONS[2].options[2],
        "quality_comparison": NOT_APPLICABLE if manual else COMMON_QUESTIONS[3].options[1],
        "workload_change": NOT_APPLICABLE if manual else COMMON_QUESTIONS[4].options[0],
        "phase_q1": q1.options[-1] if manual else q1.options[0],
        "phase_q2": q2.options[-1] if manual else q2.options[0],
    }


def make_entry(phase: str = "planung", *, manual: bool = False, **overrides) -> ComparisonEntry:
    data = {"phase": phase, **sample_answers(phase, manual=manual), **overrides}
    return ComparisonEntry(**data)


@pytest.mark.parametrize("phase", PHASE_ORDER)
def test_every_phase_entry_validates_and_matches_tracking_prefix(phase):
    entry = make_entry(phase, note="  Spart Zeit beim ersten Entwurf  ")
    assert entry.schema_version == "1"
    assert len(entry.entry_id) == 12
    assert entry.submitted_at.tzinfo is not None
    assert entry.note == "Spart Zeit beim ersten Entwurf"
    assert PHASES[phase].log_prefix in tracking.AGENTS
    assert len(questions_for(phase)) == 7


def test_entry_rejects_unknown_phase_invalid_choices_extra_fields_and_long_note():
    with pytest.raises(ValidationError):
        ComparisonEntry(phase="entwurf", **sample_answers("planung"))
    with pytest.raises(ValidationError):
        make_entry("planung", time_comparison="Unbekannte Option")
    with pytest.raises(ValidationError):
        # A Durchführung choice is not valid for Planung.
        make_entry("planung", phase_q1=PHASES["durchfuehrung"].questions[0].options[0])
    with pytest.raises(ValidationError):
        make_entry("planung", unexpected_field="x")
    assert make_entry("planung", note="   ").note == ""
    assert len(make_entry("planung", note="a" * MAX_NOTE_LENGTH).note) == MAX_NOTE_LENGTH
    with pytest.raises(ValidationError):
        make_entry("planung", note="a" * (MAX_NOTE_LENGTH + 1))
    with pytest.raises(ValidationError):
        make_entry("planung", submitted_at=datetime(2026, 11, 27, 12, 0))


@pytest.mark.parametrize("field", ["agent_seconds", "review_seconds"])
@pytest.mark.parametrize("bad", [-0.1, math.nan, math.inf, -math.inf, True, False])
def test_entry_rejects_invalid_float_metrics(field, bad):
    with pytest.raises(ValidationError):
        make_entry("planung", **{field: bad})


@pytest.mark.parametrize("field", ["agent_rounds", "input_tokens", "output_tokens"])
@pytest.mark.parametrize("bad", [-1, True, False])
def test_entry_rejects_invalid_int_metrics(field, bad):
    with pytest.raises(ValidationError):
        make_entry("planung", **{field: bad})


@pytest.mark.parametrize(
    ("phase", "prefix"),
    [
        ("planung", "run"),
        ("durchfuehrung", "durchfuehrung"),
        ("kontrolle", "kontrolle"),
        ("abschluss", "lessons"),
    ],
)
def test_latest_run_metrics_reads_matching_prefix_and_sums_tokens(tmp_path, phase, prefix):
    assert latest_run_metrics(phase, tmp_path / "missing") == (None, [])
    assert latest_run_metrics(phase, tmp_path) == (None, [])

    older = {
        "requested_model": "gpt-old",
        "seconds": 5.0,
        "outcome": "plan",
        "rounds": [{"model": "gpt-old-1", "usage": {"input_tokens": 10, "output_tokens": 5}}],
    }
    newer = {
        "requested_model": "gpt-req",
        "seconds": 14.26,
        "outcome": "plan",
        "rounds": [
            {
                "model": "gpt-a",
                "usage": {
                    "input_tokens": 100,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 30,
                    "output_tokens": 40,
                },
            },
            {
                "model": "gpt-b",
                "usage": {"input_tokens": 50, "output_tokens": 25},
            },
        ],
    }
    (tmp_path / f"{prefix}-20261120-100000.json").write_text(json.dumps(older), encoding="utf-8")
    (tmp_path / f"{prefix}-20261121-100000.json").write_text(json.dumps(newer), encoding="utf-8")
    (tmp_path / "other-20261129-100000.json").write_text(json.dumps(older), encoding="utf-8")

    lookup = latest_run_metrics(phase, tmp_path)
    assert lookup.skipped_corrupt == []
    assert lookup.metrics is not None
    assert lookup.metrics.log_file == f"{prefix}-20261121-100000.json"
    assert lookup.metrics.seconds == 14.3
    assert lookup.metrics.rounds == 2
    assert lookup.metrics.input_tokens == 200
    assert lookup.metrics.output_tokens == 65
    assert lookup.metrics.model == "gpt-b"


def test_latest_run_metrics_skips_corrupt_logs_explicitly_and_handles_zero_rounds(tmp_path):
    valid = {"requested_model": "gpt-zero", "rounds": []}
    (tmp_path / "run-20261120-090000.json").write_text(json.dumps(valid), encoding="utf-8")
    (tmp_path / "run-20261121-090000.json").write_text("{kaputt", encoding="utf-8")
    (tmp_path / "run-20261122-090000.json").write_text(
        json.dumps({"seconds": -3, "rounds": []}), encoding="utf-8"
    )

    lookup = latest_run_metrics("planung", tmp_path)
    assert lookup.skipped_corrupt == ["run-20261122-090000.json", "run-20261121-090000.json"]
    assert lookup.metrics is not None
    assert lookup.metrics.log_file == "run-20261120-090000.json"
    assert lookup.metrics.seconds is None
    assert lookup.metrics.rounds == 0
    assert lookup.metrics.model == "gpt-zero"

    (tmp_path / "run-20261120-090000.json").unlink()
    only_bad = latest_run_metrics("planung", tmp_path)
    assert only_bad.metrics is None
    assert len(only_bad.skipped_corrupt) == 2


def test_comparison_csv_uses_runtime_path_and_handles_drift_corruption_and_threads(
    tmp_path, monkeypatch
):
    target = tmp_path / "logs" / "agent_vergleich.csv"
    monkeypatch.setattr(comparison, "COMPARISON_CSV", target)
    assert read_comparisons() == []
    assert put_aside_comparisons() == []

    # BOM-only file is treated as empty without putting anything aside.
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xef\xbb\xbf\r\n")
    assert read_comparisons() == []

    record_comparison(make_entry("planung", agent_seconds=12.5, agent_rounds=3))
    rows = read_comparisons()
    assert len(rows) == 1
    assert list(rows[0].keys()) == COLUMNS
    assert put_aside_comparisons() == []

    # Header drift / older schema moves the old file aside and starts cleanly.
    target.write_bytes(b"alt_spalte\r\n1\r\n")
    record_comparison(make_entry("kontrolle"))
    assert len(put_aside_comparisons()) == 1
    assert len(read_comparisons()) == 1

    # Corrupt CSV fails loudly on read, and a failed write (lone surrogate) keeps the file as is.
    target.write_bytes(b"phase,notiz\r\nplanung,a,b\r\n")
    with pytest.raises(InputError, match="kein sauberes Protokoll"):
        read_comparisons()
    before_aside = put_aside_comparisons()
    bad_entry = make_entry("abschluss").model_copy(update={"note": "bad\udc80text"})
    with pytest.raises(UnicodeEncodeError):
        record_comparison(bad_entry)
    assert put_aside_comparisons() == before_aside
    assert target.read_bytes() == b"phase,notiz\r\nplanung,a,b\r\n"

    # Multi-threaded appends in one process keep every row.
    concurrent = tmp_path / "concurrent.csv"

    def worker(idx: int) -> None:
        for step in range(15):
            record_comparison(make_entry("durchfuehrung", note=f"w{idx}-{step}"), concurrent)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(read_comparisons(concurrent)) == 90


def test_comparison_csv_same_second_put_aside_never_overwrites(tmp_path, monkeypatch):
    class Noon(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 27, 12, 0, 0)

    monkeypatch.setattr(workbench, "datetime", Noon)
    target = tmp_path / "agent_vergleich.csv"
    (tmp_path / "agent_vergleich-bis-20261127-120000.csv").write_bytes(b"existiert")
    target.write_bytes(b"alt\r\n1\r\n")
    record_comparison(make_entry("planung"), target)
    assert put_aside_comparisons(target) == [
        "agent_vergleich-bis-20261127-120000.csv",
        "agent_vergleich-bis-20261127-120000-2.csv",
    ]
    assert (tmp_path / "agent_vergleich-bis-20261127-120000.csv").read_bytes() == b"existiert"


def test_summarize_comparisons_handles_empty_duplicates_missing_and_zeros():
    assert summarize_comparisons([]) == []
    assert summarize_comparisons([{"phase": "unbekannt"}]) == []

    t1 = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 11, 27, 11, 0, tzinfo=UTC)
    rows = [
        {
            "erfasst": t1.isoformat(),
            "phase": "planung",
            "arbeitsweise": COMMON_QUESTIONS[0].options[0],
            "zeitvergleich": COMMON_QUESTIONS[1].options[0],
            "manuell_geschaetzt": "20–40 min",
            "qualitaetsvergleich": "Deutlich besser",
            "agent_sekunden": "0",
            "runden": "0",
        },
        {
            "erfasst": t2.isoformat(),
            "phase": "planung",
            "arbeitsweise": MANUAL_MODE,
            "zeitvergleich": NOT_APPLICABLE,
            "manuell_geschaetzt": "40–60 min",
            "qualitaetsvergleich": NOT_APPLICABLE,
            "agent_sekunden": "",
            "runden": "",
        },
        {
            "erfasst": t1.isoformat(),
            "phase": "abschluss",
            "arbeitsweise": COMMON_QUESTIONS[0].options[1],
            "zeitvergleich": COMMON_QUESTIONS[1].options[1],
            "manuell_geschaetzt": "10–20 min",
            "qualitaetsvergleich": "Etwas besser",
            "agent_sekunden": "",
            "runden": "",
        },
    ]
    summary = summarize_comparisons(rows)
    assert [row["Phase"] for row in summary] == [
        "Planung",
        "Durchführung",
        "Kontrolle",
        "Abschluss",
    ]
    planung = summary[0]
    assert planung["Einträge"] == 2
    assert planung["Mit Agent"] == 1
    assert planung["Ohne Agent"] == 1
    assert planung["Letzte Arbeitsweise"] == MANUAL_MODE
    assert planung["Letzte manuelle Schätzung"] == "40–60 min"
    assert planung["Median Agent (s)"] == "0"
    assert planung["Median Runden"] == "0"

    durchf = summary[1]
    assert durchf["Einträge"] == 0
    assert durchf["Letzter Zeitvergleich"] == "–"

    abschluss = summary[3]
    assert abschluss["Einträge"] == 1
    assert abschluss["Median Agent (s)"] == "–"
    assert abschluss["Median Runden"] == "–"


@pytest.mark.parametrize("payload", ['=HYPERLINK("http://x")', "+1", "-2+3", "@SUMME(A1)", "\t=1"])
def test_to_comparison_csv_uses_bom_semicolon_decimal_comma_and_formula_protection(payload):
    entry = make_entry(
        "kontrolle",
        note=payload if not payload.startswith("\t") else "ok",
        agent_seconds=12.5,
        review_seconds=3.5,
    )
    row = {**comparison.entry_to_row(entry), "notiz": payload}
    text = to_comparison_csv([{k: str(v) for k, v in row.items()}])
    assert text.startswith("\ufeff")
    parsed = list(csv.reader(io.StringIO(text.removeprefix("\ufeff")), delimiter=";"))
    assert parsed[0] == COLUMNS
    values = dict(zip(parsed[0], parsed[1], strict=True))
    assert values["agent_sekunden"] == "12,5"
    assert values["pruefung_sekunden"] == "3,5"
    assert values["notiz"] == "'" + payload


def _card_page(phase: str, review_seconds: float | None, edited: bool | None) -> None:
    from pm_agent.ui import comparison_card

    comparison_card(phase, review_seconds=review_seconds, edited=edited)


def _render_card(phase: str, review_seconds: float | None = None, edited: bool | None = None):
    return AppTest.from_function(
        _card_page, args=(phase, review_seconds, edited), default_timeout=30
    ).run()


def test_comparison_card_widget_flow_validation_logging_and_write_error(tmp_path, monkeypatch):
    csv_path = tmp_path / "agent_vergleich.csv"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(comparison, "COMPARISON_CSV", csv_path)
    monkeypatch.setattr(agent, "LOG_DIR", log_dir)

    # Newer corrupt log + older valid log -> warning shown explicitly, valid metrics attached.
    (log_dir / "run-20261121-100000.json").write_text(
        json.dumps(
            {
                "requested_model": "gpt-test",
                "seconds": 9.5,
                "outcome": "plan",
                "rounds": [
                    {"model": "gpt-test", "usage": {"input_tokens": 80, "output_tokens": 20}}
                ],
            }
        ),
        encoding="utf-8",
    )
    (log_dir / "run-20261122-100000.json").write_text("{kaputt", encoding="utf-8")

    at = _render_card("planung", review_seconds=15.0, edited=True)
    assert not at.exception and not at.error
    for q in questions_for("planung"):
        assert at.radio(key=f"cmp_planung_{q.id}").value is None

    # Incomplete submit is rejected without writing a row.
    at.radio(key="cmp_planung_mode").set_value(COMMON_QUESTIONS[0].options[0])
    at.button(key="cmp_planung_submit").click().run()
    assert not at.exception
    assert any("Bitte wähle eine Option für:" in e.value for e in at.error)
    assert read_comparisons(csv_path) == []
    assert at.radio(key="cmp_planung_mode").value == COMMON_QUESTIONS[0].options[0]

    # Complete submit writes exactly one row, warns about skipped corrupt log, and resets draft.
    answers = sample_answers("planung")
    for qid, val in answers.items():
        at.radio(key=f"cmp_planung_{qid}").set_value(val)
    at.text_input(key="cmp_planung_note").input("Hilfreicher erster Entwurf")
    at.button(key="cmp_planung_submit").click().run()
    assert not at.exception and not at.error
    assert any("Bewertung gespeichert" in s.value for s in at.success)
    assert any("run-20261122-100000.json" in w.value for w in at.warning)
    saved = read_comparisons(csv_path)
    assert len(saved) == 1
    assert saved[0]["lauf_datei"] == "run-20261121-100000.json"
    assert saved[0]["agent_sekunden"] == "9.5"
    assert saved[0]["pruefung_sekunden"] == "15.0"
    assert saved[0]["angepasst"] == "True"
    for q in questions_for("planung"):
        assert at.radio(key=f"cmp_planung_{q.id}").value is None
    assert at.text_input(key="cmp_planung_note").value == ""

    # Write failure reports error safely, shows no success, and keeps draft.
    def fail_write(_entry, _path=None):
        raise OSError("[boom](http://bad)")

    monkeypatch.setattr(comparison, "record_comparison", fail_write)
    manual = sample_answers("planung", manual=True)
    for qid, val in manual.items():
        at.radio(key=f"cmp_planung_{qid}").set_value(val)
    at.button(key="cmp_planung_submit").click().run()
    assert not at.exception
    assert not at.success
    assert any(r"\[boom\]" in e.value for e in at.error)
    assert at.radio(key="cmp_planung_mode").value == MANUAL_MODE
