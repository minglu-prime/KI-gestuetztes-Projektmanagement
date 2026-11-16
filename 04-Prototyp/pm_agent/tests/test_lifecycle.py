from datetime import date, datetime

import pytest
from test_tools import PROJECT

from pm_agent import lifecycle
from pm_agent.lifecycle import (
    Lifecycle,
    approve_charter,
    approve_requirements,
    approved_requirements,
    charter_state,
    check_charter,
    check_requirements,
    criteria_lines,
    lines_to_criteria,
    requirement_rows,
    requirements_state,
    rows_to_requirements,
)
from pm_agent.models import Charter, Requirements
from pm_agent.workbench import InputError

NOW = datetime(2026, 11, 16, 10, 0)


def charter(**changes):
    data = {
        "goal": "Lerngruppen buchen Räume online",
        "benefit": "Kein Weg mehr zum Infoschalter",
        "in_scope": ["Buchen", "Stornieren"],
        "out_of_scope": ["Bezahlung"],
        "stakeholders": ["Studierende", "Raumverwaltung"],
        "success_criteria": [
            {"id": "K1", "text": "Eine Buchung dauert unter einer Minute"},
            {"id": "K2", "text": "Doppelbuchungen sind ausgeschlossen"},
        ],
        "constraints": ["Hochschul-Login"],
    }
    return Charter.model_validate({**data, **changes})


def need(rid, priority="Muss", sources=("K1",), title=None):
    return {
        "id": rid,
        "title": title or f"Anforderung {rid}",
        "story": "Als Studentin will ich buchen, damit die Gruppe arbeiten kann.",
        "priority": priority,
        "criteria": ["Die Buchung steht in der Liste"],
        "sources": list(sources),
    }


def requirements(*items):
    return Requirements.model_validate(
        {"items": list(items) or [need("R1"), need("R2", sources=["K2"])]}
    )


def test_file_round_trip_missing_and_damaged(tmp_path):
    path = tmp_path / "vorhaben.json"
    assert lifecycle.load(path) is None
    life = Lifecycle(project=PROJECT, charter=charter())
    lifecycle.save(life, path)
    assert lifecycle.load(path) == life
    path.write_text("{kaputt", encoding="utf-8")
    with pytest.raises(InputError, match="vorhaben.json ist beschädigt"):
        lifecycle.load(path)


def test_the_file_is_read_where_the_module_says_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, "FILE", tmp_path / "vorhaben.json")
    lifecycle.save(Lifecycle(project=PROJECT))
    assert lifecycle.load().project == PROJECT


def test_an_approval_holds_until_artefact_or_upstream_changes():
    life = Lifecycle(project=PROJECT)
    assert charter_state(life) == "offen" and requirements_state(life) == "offen"
    life = life.model_copy(update={"charter": charter(), "requirements": requirements()})
    assert charter_state(life) == "entwurf" and requirements_state(life) == "entwurf"

    life = approve_requirements(approve_charter(life, NOW), NOW)
    assert charter_state(life) == "freigegeben" and requirements_state(life) == "freigegeben"
    assert approved_requirements(life) == requirements().items

    # The charter changes: both approvals are stale, the requirements built on it too.
    life = life.model_copy(update={"charter": charter(goal="Räume und Geräte buchen")})
    assert charter_state(life) == "geändert" and requirements_state(life) == "geändert"
    assert approved_requirements(life) is None
    # The dates change: the charter was approved for other dates.
    other = Lifecycle(project=PROJECT, charter=charter())
    other = approve_charter(other, NOW)
    later = PROJECT.model_copy(update={"deadline": date(2027, 1, 29)})
    assert charter_state(other.model_copy(update={"project": later})) == "geändert"


def test_what_has_errors_cannot_be_approved():
    broken = Lifecycle(
        project=PROJECT, charter=charter(), requirements=requirements(need("R1", "Soll"))
    )
    with pytest.raises(InputError, match="mindestens eine Muss-Anforderung"):
        approve_requirements(broken, NOW)
    with pytest.raises(InputError, match="Noch kein Projektauftrag"):
        approve_charter(Lifecycle(project=PROJECT), NOW)


def test_a_charter_needs_unique_criterion_ids():
    twice = charter(
        success_criteria=[{"id": "K1", "text": "schnell"}, {"id": "K1", "text": "sicher"}]
    )
    assert check_charter(twice).errors == ["Das Erfolgskriterium 'K1' ist mehrfach vergeben"]
    assert check_charter(charter()).errors == []


def test_requirements_cover_every_success_criterion_and_name_only_known_ones():
    result = check_requirements(requirements(need("R1"), need("R2", sources=["K9"])), charter())
    assert result.errors == [
        "Anforderung 'R2' nennt das unbekannte Erfolgskriterium 'K9'",
        "Das Erfolgskriterium 'K2' (Doppelbuchungen sind ausgeschlossen) deckt keine "
        "Anforderung ab",
    ]
    assert check_requirements(requirements(), charter()).errors == []


def test_requirements_need_a_muss_and_unique_ids():
    result = check_requirements(
        requirements(need("R1", "Soll"), need("R1", "Kann", sources=["K2"])), charter()
    )
    assert result.errors == [
        "Die Anforderungs-ID 'R1' ist mehrfach vergeben",
        "Es gibt keine Muss-Anforderung: mindestens eine Muss-Anforderung ist nötig",
    ]


def test_without_a_charter_the_trace_is_a_warning():
    result = check_requirements(requirements(need("R1", sources=[])), None)
    assert result.errors == []
    assert result.warnings == [
        "Ohne Projektauftrag lässt sich nicht prüfen, ob die Anforderungen seine "
        "Erfolgskriterien abdecken"
    ]
    with_charter = check_requirements(
        requirements(need("R1", sources=["K1", "K2"]), need("R2", "Soll", sources=[])), charter()
    )
    assert with_charter.warnings == ["Anforderung 'R2' nennt kein Erfolgskriterium"]


def test_requirement_rows_round_trip():
    items = requirements(need("R1"), {**need("R2", "Kann", ["K1", "K2"]), "criteria": ["a", "b"]})
    rows = requirement_rows(items)
    assert rows[1]["Akzeptanzkriterien"] == "a; b" and rows[1]["Erfolgskriterien"] == "K1, K2"
    assert rows_to_requirements(rows) == items


def test_unreadable_requirement_rows_say_which_row():
    rows = requirement_rows(requirements())
    rows[1]["Priorität"] = "Wichtig"
    rows.append({"ID": None, "Titel": None})  # an empty row the editor adds
    with pytest.raises(InputError, match="Zeile 2 \\(R2\\): priority"):
        rows_to_requirements(rows)
    with pytest.raises(InputError, match="Noch keine Anforderung"):
        rows_to_requirements([{"ID": None}])


def test_criteria_lines_round_trip():
    criteria = charter().success_criteria
    text = criteria_lines(criteria)
    assert (
        text
        == "K1: Eine Buchung dauert unter einer Minute\nK2: Doppelbuchungen sind ausgeschlossen"
    )
    assert lines_to_criteria(text + "\n\n") == criteria
    with pytest.raises(InputError, match="Zeile 1: 'schnell' braucht die Form"):
        lines_to_criteria("schnell")
