from datetime import datetime

import pytest
from test_lifecycle import ONE, charter, design, need, requirements
from test_tools import PROJECT

from pm_agent import lifecycle
from pm_agent.lifecycle import Lifecycle, check_cases
from pm_agent.models import Cases
from pm_agent.workbench import InputError

NOW = datetime(2026, 11, 17, 10, 0)

ACCEPT = {
    "id": "T1",
    "title": "Buchung erscheint",
    "kind": "Akzeptanz",
    "criteria": ["R1.1"],
    "steps": ["Raum wählen", "Buchen"],
    "expected": "Die Buchung steht in der Liste",
}
INTEGRATE = {
    "id": "T2",
    "title": "Server legt Buchung an",
    "kind": "Integration",
    "interface": "S1",
    "steps": ["POST mit raum und datum"],
    "expected": "buchung_id kommt zurück",
}
CONFLICT = {**INTEGRATE, "id": "T3", "title": "Raum belegt", "error_code": "409"}


def cases(*items):
    return Cases.model_validate({"cases": list(items) or [ACCEPT, INTEGRATE, CONFLICT]})


def test_complete_cases_pass():
    assert check_cases(cases(), ONE, design()) == ([], [])


def test_cases_name_known_criteria_interfaces_and_error_codes():
    result = check_cases(
        cases(
            {**ACCEPT, "criteria": ["R9.1"]},
            {**INTEGRATE, "interface": "S9"},
            {**CONFLICT, "error_code": "500"},
            {**ACCEPT, "id": "T4", "criteria": []},
            {**INTEGRATE, "id": "T5", "interface": None},
            {**ACCEPT, "id": "T1"},
        ),
        ONE,
        design(),
    )
    assert result.errors == [
        "Die Testfall-ID 'T1' ist mehrfach vergeben",
        "Testfall 'T1' nennt das unbekannte Akzeptanzkriterium 'R9.1'",
        "Testfall 'T2' nennt die unbekannte Schnittstelle 'S9'",
        "Testfall 'T3': die Schnittstelle 'S1' kennt den Fehlercode '500' nicht",
        "Akzeptanztest 'T4' nennt kein Akzeptanzkriterium",
        "Integrationstest 'T5' nennt keine Schnittstelle",
    ]


def test_every_muss_criterion_needs_a_case_and_the_rest_is_a_warning():
    two = need("R1")
    two["criteria"] = ["Liste zeigt sie", "Storno geht"]
    reqs = requirements(two, need("R2", "Soll", ["K2"]))
    result = check_cases(cases(ACCEPT), reqs, design())
    assert result.errors == [
        "Muss-Anforderung 'R1': das Akzeptanzkriterium 'R1.2' (Storno geht) hat keinen Testfall"
    ]
    assert result.warnings == [
        "Soll-Anforderung 'R2': das Akzeptanzkriterium 'R2.1' (Die Buchung steht in der "
        "Liste) hat keinen Testfall",
        "Die Schnittstelle 'S1' (Buchung anlegen) hat keinen Integrationstest",
        "Der Fehlercode '409' der Schnittstelle 'S1' hat keinen Testfall",
    ]


def test_without_requirements_and_design_only_the_cases_themselves_are_checked():
    result = check_cases(cases(), None, None)
    assert result.errors == []
    assert result.warnings == [
        "Ohne Anforderungen lässt sich nicht prüfen, ob jedes Akzeptanzkriterium einen "
        "Testfall hat",
        "Ohne Entwurf lässt sich nicht prüfen, ob jede Schnittstelle einen Integrationstest hat",
    ]


def test_the_test_plan_approval_holds_until_anything_upstream_changes():
    life = Lifecycle(project=PROJECT, charter=charter(), requirements=ONE, design=design())
    assert lifecycle.cases_state(life) == "offen"
    life = life.model_copy(update={"cases": cases()})
    assert lifecycle.cases_state(life) == "entwurf"
    life = lifecycle.approve_cases(life, NOW)
    assert lifecycle.approved_cases(life) == cases()
    changed = life.model_copy(update={"design": design(interfaces=[])})
    assert lifecycle.cases_state(changed) == "geändert"
    with pytest.raises(InputError, match="mehrfach vergeben"):
        lifecycle.approve_cases(life.model_copy(update={"cases": cases(ACCEPT, ACCEPT)}), NOW)
