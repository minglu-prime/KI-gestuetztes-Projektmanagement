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


def lessons(*items):
    from pm_agent.models import Lessons

    return Lessons.model_validate({"items": list(items)})


def test_lessons_cover_every_severe_defect_and_missed_demo(project):
    from pm_agent.tracking import Retro, record_retro

    tracking = record_defect(
        project, Defect(case_id="T1", severity="schwer", cause="x", task_id="A")
    )
    tracking = record_retro(
        tracking, Retro(monday=date(2026, 11, 16), shown="nein", measure="früher testen")
    )
    loose = lessons({"observation": "Zu spät getestet", "advice": "Früher testen", "refs": ["F9"]})
    assert closing.check_lessons(loose, tracking) == [
        "Lehre 1 nennt den unbekannten Bezug 'F9'",
        "Der schwere Fehler F1 kommt in keiner Lehre vor",
        "Die ausgefallene Demo der Woche ab 16.11.2026 kommt in keiner Lehre vor",
    ]
    full = lessons(
        {"observation": "Schema zu spät", "advice": "Schema zuerst", "refs": ["F1", "2026-11-16"]}
    )
    assert closing.check_lessons(full, tracking) == []


def test_a_lesson_draft_that_misses_a_defect_goes_back_to_claude(api, project, tmp_path):
    import json

    from test_agent_loop import read_log, reply
    from test_lifecycle import call

    tracking = record_defect(
        project, Defect(case_id="T1", severity="schwer", cause="Schema", task_id="A")
    )
    replies, requests = api
    loose = lessons({"observation": "a", "advice": "b", "refs": []})
    full = lessons({"observation": "a", "advice": "b", "refs": ["F1"]})
    replies += [
        reply([call("submit_lessons", loose.model_dump(mode="json"), "c1")]),
        reply([call("submit_lessons", full.model_dump(mode="json"), "c2")]),
    ]
    assert closing.run_lessons(tracking, DAY, log_dir=tmp_path) == full
    sent = json.dumps(requests[0], ensure_ascii=False)
    assert "Schema" in sent and "hours_per_week" not in sent and "Anna" not in sent
    assert "F1" in json.dumps(requests[1]["messages"][-1], ensure_ascii=False)
    assert read_log(tmp_path, "lessons")["outcome"] == "lessons learned"


def test_the_closing_report_has_signoffs_defects_and_lessons(project):
    from pm_agent.tracking import evaluate

    tracking = closing.record_signoff(
        passed(project, "T1"), Signoff(requirement_id="R1", decision="abgenommen")
    )
    tracking = record_defect(
        tracking, Defect(case_id="T1", severity="leicht", cause="Tippfehler", status="behoben")
    )
    tracking = tracking.model_copy(
        update={"lessons": lessons({"observation": "a | b", "advice": "c", "refs": ["F1"]}).items}
    )
    text = closing.closing_document(tracking, cases(ACCEPT), evaluate(tracking, DAY))
    assert text.startswith("# Abschlussbericht")
    assert "| R1 | Anforderung R1 | Muss | abnehmbar | abgenommen | – |" in text
    assert "| R2 | Anforderung R2 | Soll | kein Testfall | offen | – |" in text
    assert "- F1 (leicht, behoben): Tippfehler" in text
    assert r"- a \| b: c (Bezug: F1)" in text
    assert "Soll-Anforderung 'R2' (Anforderung R2) ist noch nicht entschieden" in text


def test_lesson_rows_round_trip(project):
    full = lessons({"observation": "a", "advice": "b", "refs": ["F1", "2026-11-16"]})
    rows = closing.lesson_rows(full.items)
    assert rows == [{"Beobachtung": "a", "Empfehlung": "b", "Bezug": "F1, 2026-11-16"}]
    assert closing.rows_to_lessons(rows) == full.items
    rows.append({"Beobachtung": None, "Empfehlung": None, "Bezug": None})  # an empty editor row
    assert closing.rows_to_lessons(rows) == full.items
    with pytest.raises(InputError, match="Zeile 1"):
        closing.rows_to_lessons([{"Beobachtung": "a", "Empfehlung": "", "Bezug": ""}])


def test_signoff_rows_show_suggestion_and_decision(project):
    signed = closing.record_signoff(
        project, Signoff(requirement_id="R2", decision="zurückgestellt", reason="keine Zeit")
    )
    assert closing.signoff_rows(signed, cases(ACCEPT)) == [
        {
            "ID": "R1",
            "Anforderung": "Anforderung R1",
            "Priorität": "Muss",
            "Vorschlag": "Testfall T1 ohne Ergebnis",
            "Entscheidung": "offen",
            "Grund": "",
        },
        {
            "ID": "R2",
            "Anforderung": "Anforderung R2",
            "Priorität": "Soll",
            "Vorschlag": "kein Testfall",
            "Entscheidung": "zurückgestellt",
            "Grund": "keine Zeit",
        },
    ]


def test_every_component_has_an_owner_and_monitoring(project):
    from test_lifecycle import design

    from pm_agent.tracking import Operation

    rows = closing.operation_rows(design(), [])
    # Roles and systems outside the project need no handbook; components do.
    assert [r["Baustein"] for r in rows] == ["B2", "B3"]
    rows[0].update({"Verantwortlich": "Frontend-Team", "Überwachung": "Fehlerseite zählen"})
    operations = closing.rows_to_operations(rows)
    assert operations[0] == Operation(
        component_id="B2", owner="Frontend-Team", monitoring="Fehlerseite zählen"
    )
    assert closing.check_operations(design(), operations).errors == [
        "Baustein 'B3' (Server) hat keine Verantwortlichen",
        "Baustein 'B3' (Server) hat keine Überwachung",
    ]
    assert closing.check_operations(None, []).warnings == [
        "Ohne Entwurf gibt es keine Bausteine für das Betriebshandbuch"
    ]


def test_an_incident_names_a_known_component_and_gets_a_number(project):
    from test_lifecycle import design

    from pm_agent.tracking import Incident

    incident = Incident(on=DAY, component_id="B3", impact="Buchen geht nicht")
    tracking = closing.record_incident(project, incident, design())
    assert tracking.incidents[0].id == "S1"
    with pytest.raises(InputError, match="unbekannten Baustein 'B9'"):
        closing.record_incident(
            project, incident.model_copy(update={"component_id": "B9"}), design()
        )
