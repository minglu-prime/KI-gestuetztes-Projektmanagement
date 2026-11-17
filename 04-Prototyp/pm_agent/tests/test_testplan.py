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


def test_case_rows_round_trip_and_say_which_row():
    from pm_agent.lifecycle import case_rows, rows_to_cases

    rows = case_rows(cases())
    assert rows[2] == {
        "ID": "T3",
        "Titel": "Raum belegt",
        "Art": "Integration",
        "Kriterien": "",
        "Schnittstelle": "S1",
        "Fehlercode": "409",
        "Schritte": "POST mit raum und datum",
        "Erwartet": "buchung_id kommt zurück",
    }
    assert rows_to_cases(rows) == cases()
    rows[0]["Art"] = "Unit"
    rows.append({"ID": None, "Titel": None})  # an empty row the editor adds
    with pytest.raises(InputError, match=r"Zeile 1 \(T1\): kind"):
        rows_to_cases(rows)
    with pytest.raises(InputError, match="Noch kein Testfall"):
        rows_to_cases([{"ID": None}])


def test_a_test_plan_that_misses_a_muss_criterion_goes_back_to_claude(api, tmp_path):
    import json

    from test_agent_loop import read_log, reply
    from test_lifecycle import call

    from pm_agent.tracking import agent_runs

    replies, requests = api
    replies += [
        reply([call("submit_testplan", cases(INTEGRATE, CONFLICT).model_dump(mode="json"), "c1")]),
        reply([call("submit_testplan", cases().model_dump(mode="json"), "c2")]),
    ]
    result = lifecycle.run_cases(PROJECT, ONE, design(), log_dir=tmp_path)
    assert result == cases()
    sent = json.dumps(requests[0], ensure_ascii=False)
    assert "Buchung anlegen" in sent and "hours_per_week" not in sent
    assert "'R1.1'" in json.dumps(requests[1]["messages"][-1], ensure_ascii=False)
    assert read_log(tmp_path, "testplan")["outcome"] == "testplan"
    assert [(r["Agent"], r["Ergebnis"]) for r in agent_runs(tmp_path)] == [("Testplan", "Testplan")]


def test_the_test_plan_document_lists_cases_and_coverage():
    life = Lifecycle(project=PROJECT, requirements=ONE, design=design(), cases=cases())
    text = lifecycle.cases_document(life)
    assert text.startswith("# Testplan")
    assert "| T3 | Raum belegt | Integration | – | S1 | 409 |" in text
    assert "- R1.1 (Die Buchung steht in der Liste): T1" in text
    assert "- S1 (Buchung anlegen): T2, T3" in text
