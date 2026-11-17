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


@pytest.fixture
def adopted(tmp_path):
    from test_tools import TEAM, plan_input

    from pm_agent.models import Plan
    from pm_agent.tracking import adopt

    return adopt(PROJECT, TEAM, Plan.model_validate(plan_input()), path=tmp_path / "p.json")


def test_results_and_defects_are_checked_against_the_cases(adopted):
    from datetime import date

    from pm_agent.tracking import CaseResult, Defect, check_results, record_defect, record_result

    day = date(2026, 11, 20)
    tracking = record_result(adopted, CaseResult(case_id="T2", result="fehlgeschlagen", on=day))
    result = check_results(tracking, cases())
    assert result.errors == ["Testfall 'T2' ist fehlgeschlagen, aber es gibt keinen Fehlereintrag"]
    assert result.warnings == ["2 Testfälle ohne Ergebnis: T1, T3"]

    tracking = record_defect(
        tracking, Defect(case_id="T2", severity="schwer", cause="Schema", task_id="B")
    )
    assert tracking.defects[0].id == "F1" and check_results(tracking, cases()).errors == []
    # A later result replaces the earlier one of the same case.
    again = record_result(tracking, CaseResult(case_id="T2", result="bestanden", on=day))
    assert [(r.case_id, r.result) for r in again.results] == [("T2", "bestanden")]


def test_a_defect_needs_a_known_task_and_a_severe_one_needs_one_at_all(adopted):
    from pm_agent.tracking import Defect, record_defect

    with pytest.raises(InputError, match="unbekannte Aufgabe 'Z'"):
        record_defect(adopted, Defect(case_id="T2", severity="mittel", cause="x", task_id="Z"))
    with pytest.raises(InputError, match="Ein schwerer Fehler braucht eine Aufgabe"):
        record_defect(adopted, Defect(case_id="T2", severity="schwer", cause="x"))


def test_a_defect_reopens_its_task_and_an_open_defect_on_a_finished_task_is_a_warning(adopted):
    from pm_agent.tracking import Defect, check_results, record_defect, reopen

    done = adopted.model_copy(
        update={
            "progress": {
                **adopted.progress,
                "B": adopted.progress["B"].model_copy(update={"status": "fertig"}),
            }
        }
    )
    tracking = record_defect(done, Defect(case_id="T2", severity="mittel", cause="x", task_id="B"))
    assert (
        "Fehler F1 ist offen, seine Aufgabe 'B' ist aber fertig"
        in check_results(tracking, cases()).warnings
    )
    reopened = reopen(tracking, "F1")
    assert reopened.progress["B"].status == "in Arbeit"
    with pytest.raises(InputError, match="keine Aufgabe"):
        reopen(record_defect(adopted, Defect(case_id="T1", severity="leicht", cause="y")), "F1")


def test_results_and_defects_survive_adopting_the_rest_again(adopted, tmp_path):
    from datetime import date

    from pm_agent.tracking import CaseResult, adopt, record_result

    tracking = record_result(
        adopted, CaseResult(case_id="T1", result="bestanden", on=date(2026, 11, 20))
    )
    again = adopt(
        tracking.project, tracking.team, tracking.plan, path=tmp_path / "q.json", keep=tracking
    )
    assert again.results == tracking.results


def test_the_test_summary_counts_results_and_open_defects(adopted):
    from datetime import date

    from pm_agent.tracking import CaseResult, Defect, quality_summary, record_defect, record_result

    day = date(2026, 11, 20)
    tracking = record_result(adopted, CaseResult(case_id="T1", result="bestanden", on=day))
    tracking = record_result(tracking, CaseResult(case_id="T2", result="fehlgeschlagen", on=day))
    tracking = record_defect(
        tracking, Defect(case_id="T2", severity="schwer", cause="x", task_id="B")
    )
    tracking = record_defect(
        tracking, Defect(case_id="T2", severity="leicht", cause="y", status="behoben")
    )
    assert quality_summary(tracking, cases()) == {
        "Mit Ergebnis": "2 von 3",
        "Bestanden": "1",
        "Offene Fehler": "1 (schwer: 1)",
    }


def test_approvals_made_before_criteria_had_ids_still_hold():
    import hashlib
    import json

    life = Lifecycle(project=PROJECT, charter=charter(), requirements=ONE, design=design())

    def old_digest(*parts):
        # How the approval was stamped when criteria were plain texts.
        data = []
        for part in parts:
            dumped = part.model_dump(mode="json")
            if "items" in dumped:
                for item in dumped["items"]:
                    item["criteria"] = [c["text"] for c in item["criteria"]]
            data.append(dumped)
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    stamp = lifecycle.Approval(
        at=NOW, digest=old_digest(life.project, life.charter, life.requirements)
    )
    design_stamp = lifecycle.Approval(
        at=NOW, digest=old_digest(life.project, life.charter, life.requirements, life.design)
    )
    old = life.model_copy(update={"requirements_ok": stamp, "design_ok": design_stamp})
    assert lifecycle.requirements_state(old) == "freigegeben"
    assert lifecycle.design_state(old) == "freigegeben"


def test_a_number_in_use_elsewhere_is_not_given_again():
    from pm_agent.lifecycle import requirement_rows, rows_to_requirements

    two = need("R1")
    two["criteria"] = ["a", "b"]
    rows = requirement_rows(requirements(two))
    rows[0]["Akzeptanzkriterien"] = "R1.1: a; c"  # R1.2 deleted, c added
    # R1.2 was saved before, and a test case still points at it.
    again = rows_to_requirements(rows, taken={"R1.1", "R1.2"})
    assert [(c.id, c.text) for c in again.items[0].criteria] == [("R1.1", "a"), ("R1.3", "c")]


def test_criteria_move_with_a_renamed_requirement():
    from pm_agent.lifecycle import requirement_rows, rows_to_requirements

    rows = requirement_rows(requirements(need("R1")))
    rows[0]["ID"] = "R2"
    moved = rows_to_requirements(rows).items[0].criteria
    assert [(c.id, c.text) for c in moved] == [("R2.1", "Die Buchung steht in der Liste")]


def test_a_criterion_id_names_its_requirement():
    from pm_agent.lifecycle import check_requirements

    odd = need("R1")
    odd["criteria"] = [{"id": "AK1", "text": "a"}]
    assert check_requirements(requirements(odd, need("R2", sources=["K2"])), charter()).errors == [
        "Anforderung 'R1': das Akzeptanzkriterium 'AK1' muss 'R1.<Nummer>' heißen"
    ]


def test_a_defect_whose_task_left_the_plan_can_still_be_closed(adopted):
    from pm_agent.tracking import Defect, record_defect, reopen

    tracking = record_defect(
        adopted, Defect(case_id="T2", severity="schwer", cause="x", task_id="B")
    )
    gone = tracking.model_copy(update={"progress": {"A": tracking.progress["A"]}})
    closed = record_defect(gone, gone.defects[0].model_copy(update={"status": "behoben"}))
    assert closed.defects[0].status == "behoben"
    with pytest.raises(InputError, match="nicht mehr im Plan"):
        reopen(gone, "F1")


def test_a_case_that_fails_again_after_its_fix_needs_a_new_defect(adopted):
    from datetime import date

    from pm_agent.tracking import CaseResult, Defect, check_results, record_defect, record_result

    failed = CaseResult(case_id="T1", result="fehlgeschlagen", on=date(2026, 11, 20))
    tracking = record_result(adopted, failed)
    tracking = record_defect(
        tracking, Defect(case_id="T1", severity="leicht", cause="x", status="behoben")
    )
    assert "Testfall 'T1' ist fehlgeschlagen, aber es gibt keinen Fehlereintrag" in (
        check_results(tracking, cases()).errors
    )


def test_open_defects_come_next_when_all_tasks_are_done(adopted):
    from datetime import date

    from pm_agent.tracking import Defect, apply_rows, next_step, record_defect

    done = apply_rows(adopted, [{"ID": "A", "Status": "fertig"}, {"ID": "B", "Status": "fertig"}])
    tracking = record_defect(done, Defect(case_id="T2", severity="schwer", cause="x", task_id="B"))
    advice, page = next_step(tracking, date(2026, 11, 20))
    assert page == "testlauf" and "1 Fehler ist offen" in advice
