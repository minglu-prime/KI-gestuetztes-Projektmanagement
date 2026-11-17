from datetime import date

import pytest
from test_lifecycle import need, requirements
from test_testplan import ACCEPT, CONFLICT, INTEGRATE, cases
from test_tools import PROJECT, TEAM, plan_input

from pm_agent import closing
from pm_agent.models import Plan
from pm_agent.tracking import (
    CaseResult,
    Defect,
    Signoff,
    adopt,
    record_defect,
    record_result,
)
from pm_agent.workbench import InputError

DAY = date(2026, 12, 10)


@pytest.fixture
def project(tmp_path):
    """R1 (Muss, criterion R1.1, tested by T1) and R2 (Soll, R2.1, no test case)."""
    needs = requirements(need("R1"), need("R2", "Soll", ["K2"])).items
    return adopt(
        PROJECT,
        TEAM,
        Plan.model_validate(plan_input()),
        path=tmp_path / "p.json",
        requirements=needs,
    )


def passed(tracking, *ids):
    for cid in ids:
        tracking = record_result(tracking, CaseResult(case_id=cid, result="bestanden", on=DAY))
    return tracking


def test_python_suggests_what_can_be_accepted(project):
    the_cases = cases(ACCEPT, INTEGRATE, CONFLICT)
    assert closing.suggestions(project, the_cases) == {
        "R1": "Testfall T1 ohne Ergebnis",
        "R2": "kein Testfall",
    }
    failed = record_result(project, CaseResult(case_id="T1", result="fehlgeschlagen", on=DAY))
    assert closing.suggestions(failed, the_cases)["R1"] == "Testfall T1 nicht bestanden"
    with_defect = record_defect(
        passed(project, "T1"), Defect(case_id="T1", severity="leicht", cause="x")
    )
    assert closing.suggestions(with_defect, the_cases)["R1"] == "Fehler F1 offen"
    assert closing.suggestions(passed(project, "T1"), the_cases)["R1"] == "abnehmbar"


def test_a_signoff_names_a_known_requirement_and_a_deferral_a_reason(project):
    with pytest.raises(InputError, match="unbekannte Anforderung 'R9'"):
        closing.record_signoff(project, Signoff(requirement_id="R9", decision="abgenommen"))
    with pytest.raises(InputError, match="braucht einen Grund"):
        closing.record_signoff(project, Signoff(requirement_id="R2", decision="zurückgestellt"))
    done = closing.record_signoff(project, Signoff(requirement_id="R1", decision="abgenommen"))
    again = closing.record_signoff(done, Signoff(requirement_id="R1", decision="abgenommen"))
    assert len(again.signoffs) == 1


def test_closing_needs_every_muss_decided_and_no_open_severe_defect(project):
    the_cases = cases(ACCEPT)
    severe = record_defect(project, Defect(case_id="T1", severity="schwer", cause="x", task_id="A"))
    result = closing.check_closing(severe, the_cases)
    assert result.errors == [
        "Fehler F1 (schwer) ist noch offen",
        "Muss-Anforderung 'R1' (Anforderung R1) ist weder abgenommen noch begründet zurückgestellt",
    ]
    assert result.warnings == ["Soll-Anforderung 'R2' (Anforderung R2) ist noch nicht entschieden"]

    signed = closing.record_signoff(project, Signoff(requirement_id="R1", decision="abgenommen"))
    signed = closing.record_signoff(
        signed, Signoff(requirement_id="R2", decision="zurückgestellt", reason="keine Zeit")
    )
    result = closing.check_closing(signed, the_cases)
    assert result.errors == []
    # Accepted although its test has no result: allowed, but said.
    assert result.warnings == ["Anforderung 'R1' ist abgenommen, obwohl: Testfall T1 ohne Ergebnis"]


def test_without_requirements_there_is_nothing_to_accept(tmp_path):
    plain = adopt(PROJECT, TEAM, Plan.model_validate(plan_input()), path=tmp_path / "q.json")
    assert closing.check_closing(plain, None).warnings == [
        "Der Plan wurde ohne Anforderungen übernommen: Es gibt nichts abzunehmen"
    ]
