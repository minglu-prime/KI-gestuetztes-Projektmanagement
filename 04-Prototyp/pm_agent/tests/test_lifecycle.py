import json
import re
from datetime import date, datetime

import pytest
from test_tools import PROJECT

from pm_agent import lifecycle
from pm_agent.lifecycle import (
    Approval,
    Lifecycle,
    approve_charter,
    approve_design,
    approve_requirements,
    approved_design,
    approved_requirements,
    charter_state,
    check_charter,
    check_design,
    check_requirements,
    criteria_lines,
    design_rows,
    design_state,
    lines_to_criteria,
    requirement_rows,
    requirements_state,
    rows_to_design,
    rows_to_requirements,
    text_to_fields,
)
from pm_agent.models import Charter, Design, Requirements
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
    assert rows[1]["Akzeptanzkriterien"] == "R2.1: a; R2.2: b"
    assert rows[1]["Erfolgskriterien"] == "K1, K2"
    assert rows_to_requirements(rows) == items
    # Deleting R2.1 and adding a criterion: R2.2 keeps its ID, the new one is R2.3.
    rows[1]["Akzeptanzkriterien"] = "R2.2: b; c"
    assert [c.id for c in rows_to_requirements(rows).items[1].criteria] == ["R2.2", "R2.3"]


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


def call(name, data, call_id):
    return {"type": "tool_use", "id": call_id, "name": name, "input": data}


def test_a_rejected_charter_goes_back_to_claude(api, tmp_path):
    from test_agent_loop import read_log, reply

    replies, requests = api
    twice = charter(success_criteria=[{"id": "K1", "text": "a"}, {"id": "K1", "text": "b"}])
    replies += [
        reply([call("submit_auftrag", twice.model_dump(mode="json"), "c1")]),
        reply([call("submit_auftrag", charter().model_dump(mode="json"), "c2")]),
    ]
    result = lifecycle.run_charter(PROJECT, log_dir=tmp_path)
    assert result == charter()
    assert PROJECT.idea in json.dumps(requests[0]["input"], ensure_ascii=False)
    rejection = requests[1]["input"][-1]["output"]
    assert "'K1' ist mehrfach vergeben" in json.dumps(rejection, ensure_ascii=False)
    log = read_log(tmp_path, "auftrag")
    assert log["outcome"] == "projektauftrag" and log["result"] == charter().model_dump(mode="json")


def test_requirements_that_miss_a_criterion_are_rejected(api, tmp_path):
    from test_agent_loop import read_log, reply

    replies, requests = api
    replies += [
        reply(
            [call("submit_anforderungen", requirements(need("R1")).model_dump(mode="json"), "c1")]
        ),
        reply([call("submit_anforderungen", requirements().model_dump(mode="json"), "c2")]),
    ]
    result = lifecycle.run_requirements(PROJECT, charter(), log_dir=tmp_path)
    assert result == requirements()
    # Claude works from the charter, and learns which success criterion is not covered.
    assert "Doppelbuchungen sind ausgeschlossen" in json.dumps(requests[0], ensure_ascii=False)
    assert "'K2'" in json.dumps(requests[1]["input"][-1], ensure_ascii=False)
    assert read_log(tmp_path, "anforderungen")["outcome"] == "anforderungskatalog"


def test_runs_of_the_new_agents_are_counted(api, tmp_path):
    from test_agent_loop import reply

    from pm_agent.tracking import agent_runs

    replies, _ = api
    replies += [reply([call("submit_auftrag", charter().model_dump(mode="json"), "c1")])]
    lifecycle.run_charter(PROJECT, log_dir=tmp_path)
    assert [(r["Agent"], r["Ergebnis"]) for r in agent_runs(tmp_path)] == [
        ("Projektauftrag", "Projektauftrag")
    ]


def test_the_charter_document_says_whether_it_is_approved():
    life = Lifecycle(project=PROJECT, charter=charter())
    draft = lifecycle.charter_document(life)
    assert draft.startswith("# Projektauftrag")
    assert "**Stand:** Entwurf, nicht freigegeben" in draft
    assert "- K2: Doppelbuchungen sind ausgeschlossen" in draft
    assert "- Raumverwaltung" in draft and "## Nicht im Umfang\n\n- Bezahlung" in draft
    approved = lifecycle.charter_document(approve_charter(life, NOW))
    assert "**Stand:** Freigegeben am 16.11.2026 10:00" in approved
    changed = approve_charter(life, NOW).model_copy(update={"charter": charter(goal="Mehr")})
    assert "**Stand:** Seit der Freigabe am 16.11.2026 10:00 geändert" in (
        lifecycle.charter_document(changed)
    )


def test_the_requirements_document_traces_to_criteria():
    items = requirements(need("R1", title="Buchen | Stornieren"), need("R2", "Soll", ["K2"]))
    text = lifecycle.requirements_document(
        Lifecycle(project=PROJECT, charter=charter(), requirements=items)
    )
    assert r"| R1 | Buchen \| Stornieren | Muss | K1 |" in text
    assert "- R1.1 Die Buchung steht in der Liste" in text
    assert "- K1 (Eine Buchung dauert unter einer Minute): R1" in text
    assert "- K2 (Doppelbuchungen sind ausgeschlossen): R2" in text


def test_a_file_in_another_encoding_is_damaged_not_a_crash(tmp_path):
    path = tmp_path / "vorhaben.json"
    path.write_bytes('{"project": "Lernräume"}'.encode("cp1252"))
    with pytest.raises(InputError, match="vorhaben.json"):
        lifecycle.load(path)


def test_an_acceptance_criterion_has_no_semicolon():
    # The table separates acceptance criteria by semicolons: one inside would split it.
    from pydantic import ValidationError

    from pm_agent.models import Requirement
    from pm_agent.tools import invalid_input

    with pytest.raises(ValidationError) as err:
        Requirement.model_validate(
            {**need("R1"), "criteria": ["Antwort unter 2 s; bei 50 Nutzern"]}
        )
    assert invalid_input(err.value) == [
        "Ungültige Eingabe bei criteria.0.text: darf kein Semikolon enthalten"
    ]


def design(**changes):
    """Studierende use the web front end, which calls the server to book a room."""
    data = {
        "components": [
            {"id": "B1", "name": "Studierende", "kind": "Rolle"},
            {"id": "B2", "name": "Web", "kind": "Komponente", "purpose": "Oberfläche"},
            {"id": "B3", "name": "Server", "kind": "Komponente"},
        ],
        "interfaces": [
            {
                "id": "S1",
                "name": "Buchung anlegen",
                "provider": "B3",
                "consumers": ["B2"],
                "input": [{"name": "raum", "type": "Text"}, {"name": "datum", "type": "Datum"}],
                "output": [{"name": "buchung_id", "type": "Ganzzahl"}],
                "errors": [{"code": "409", "meaning": "Raum belegt"}],
            }
        ],
        "flows": [
            {
                "id": "A1",
                "title": "Raum buchen",
                "requirement_ids": ["R1"],
                "steps": [
                    {"sender": "B1", "receiver": "B2", "text": "wählt Raum und Datum"},
                    {"sender": "B2", "receiver": "B3", "interface": "S1"},
                    {"sender": "B3", "receiver": "B2", "kind": "Antwort", "interface": "S1"},
                ],
            }
        ],
    }
    return Design.model_validate({**data, **changes})


def test_an_old_file_without_a_design_still_loads(tmp_path):
    path = tmp_path / "vorhaben.json"
    old = Lifecycle(project=PROJECT).model_dump_json(exclude={"design", "design_ok"})
    path.write_text(old, encoding="utf-8")
    assert lifecycle.load(path).design is None


def test_the_design_approval_holds_until_anything_upstream_changes():
    life = Lifecycle(project=PROJECT, charter=charter(), requirements=requirements())
    assert design_state(life) == "offen"
    life = life.model_copy(update={"design": design()})
    assert design_state(life) == "entwurf" and approved_design(life) is None
    life = life.model_copy(
        update={"design_ok": Approval(at=NOW, digest=lifecycle._design_digest(life))}
    )
    assert design_state(life) == "freigegeben" and approved_design(life) == design()
    for upstream in [
        {"requirements": requirements(need("R1"), need("R2", sources=["K2"], title="Neu"))},
        {"charter": charter(goal="Mehr")},
        {"project": PROJECT.model_copy(update={"deadline": date(2027, 1, 29)})},
        {"design": design(interfaces=[])},
    ]:
        changed = life.model_copy(update=upstream)
        assert design_state(changed) == "geändert" and approved_design(changed) is None


ONE = requirements(need("R1"))


def steps(*items):
    return [{"id": "A1", "title": "Raum buchen", "requirement_ids": ["R1"], "steps": list(items)}]


CALL = {"sender": "B2", "receiver": "B3", "interface": "S1"}
REPLY = {"sender": "B3", "receiver": "B2", "kind": "Antwort", "interface": "S1"}


def test_a_sound_design_passes_the_check():
    assert check_design(design(), ONE) == ([], [])


def test_ids_fields_and_error_codes_are_unique():
    s1 = design().interfaces[0].model_dump()
    twice = {
        **s1,
        "input": s1["input"] + [{"name": "raum", "type": "Zahl"}],
        "output": s1["output"] * 2,
        "errors": s1["errors"] * 2,
    }
    components = design().model_dump()["components"]
    result = check_design(
        design(components=components + [components[0]], interfaces=[twice, twice]), ONE
    )
    assert result.errors == [
        "Die Baustein-ID 'B1' ist mehrfach vergeben",
        "Die Schnittstellen-ID 'S1' ist mehrfach vergeben",
        "Schnittstelle 'S1': das Eingabefeld 'raum' ist mehrfach vergeben",
        "Schnittstelle 'S1': das Ausgabefeld 'buchung_id' ist mehrfach vergeben",
        "Schnittstelle 'S1': der Fehlercode '409' ist mehrfach vergeben",
    ]


def test_providers_and_consumers_are_known_parts_and_no_role_provides():
    s1 = design().interfaces[0].model_dump()
    result = check_design(
        design(interfaces=[{**s1, "provider": "B1", "consumers": ["B2", "B9"]}]), ONE
    )
    assert result.errors[:2] == [
        "Schnittstelle 'S1': der Anbieter 'B1' ist eine Rolle; eine Rolle bietet keine "
        "Schnittstelle an",
        "Schnittstelle 'S1': der Nutzer 'B9' ist kein bekannter Baustein",
    ]


def test_steps_name_known_parts_and_interfaces_and_follow_the_contract():
    result = check_design(
        design(
            flows=steps(
                {"sender": "B1", "receiver": "B9"},
                {"sender": "B2", "receiver": "B3", "interface": "S9"},
                {"sender": "B3", "receiver": "B2", "interface": "S1"},
                {"sender": "B2", "receiver": "B3", "kind": "Antwort", "interface": "S1"},
            )
        ),
        ONE,
    )
    assert result.errors == [
        "Ablauf 'A1', Schritt 1: der Empfänger 'B9' ist kein bekannter Baustein",
        "Ablauf 'A1', Schritt 2: die Schnittstelle 'S9' ist unbekannt",
        "Ablauf 'A1', Schritt 3: ein Aufruf von 'S1' geht von B2 an B3, nicht von B3 an B2",
        "Ablauf 'A1', Schritt 4: eine Antwort von 'S1' geht von B3 an B2, nicht von B2 an B3",
    ]


def test_a_step_to_itself_without_interface_is_fine():
    flows = steps(
        {"sender": "B1", "receiver": "B2"}, CALL, {"sender": "B3", "receiver": "B3"}, REPLY
    )
    assert check_design(design(flows=flows), ONE) == ([], [])


def test_a_removed_provider_is_an_error_not_a_crash():
    components = [c for c in design().model_dump()["components"] if c["id"] != "B3"]
    errors = check_design(design(components=components), ONE).errors
    assert errors == [
        "Schnittstelle 'S1': der Anbieter 'B3' ist kein bekannter Baustein",
        "Ablauf 'A1', Schritt 2: der Empfänger 'B3' ist kein bekannter Baustein",
        "Ablauf 'A1', Schritt 3: der Absender 'B3' ist kein bekannter Baustein",
    ]


def test_every_interface_is_used_and_every_muss_requirement_has_a_flow():
    s2 = {**design().interfaces[0].model_dump(), "id": "S2", "name": "Buchung löschen"}
    flows = [{**steps(CALL)[0], "requirement_ids": ["R1", "R9"]}]
    reqs = requirements(need("R1"), need("R2", title="Stornieren"), need("R3", "Kann"))
    result = check_design(
        design(interfaces=[*design().model_dump()["interfaces"], s2], flows=flows), reqs
    )
    assert result.errors == [
        "Die Schnittstelle 'S2' (Buchung löschen) kommt in keinem Ablauf vor",
        "Ablauf 'A1' dient der unbekannten Anforderung 'R9'",
        "Muss-Anforderung 'R2' (Stornieren) hat keinen Ablauf",
    ]
    assert result.warnings == [
        "Kann-Anforderung 'R3' (Anforderung R3) hat keinen Ablauf",
        "Der Baustein 'B1' (Studierende) kommt in keinem Ablauf vor",
    ]


def test_loose_ends_are_warnings():
    flows = [{**steps({"sender": "B2", "receiver": "B3"}, CALL, REPLY)[0], "requirement_ids": []}]
    result = check_design(design(flows=flows), ONE)
    assert result.errors == ["Muss-Anforderung 'R1' (Anforderung R1) hat keinen Ablauf"]
    assert result.warnings == [
        "Ablauf 'A1' dient keiner Anforderung",
        "Ablauf 'A1', Schritt 1: B2 und B3 reden ohne Schnittstelle miteinander",
        "Der Baustein 'B1' (Studierende) kommt in keinem Ablauf vor",
    ]


def test_without_requirements_the_trace_is_a_warning():
    flows = [{**steps(CALL, REPLY)[0], "requirement_ids": ["R9"]}]
    result = check_design(design(flows=flows), None)
    assert result.errors == []
    assert result.warnings[0] == "Ohne Anforderungen lässt sich der Entwurf nicht gegen sie prüfen"


def test_a_design_with_errors_cannot_be_approved_but_needs_no_approved_requirements():
    life = Lifecycle(project=PROJECT, requirements=ONE, design=design())
    assert design_state(approve_design(life, NOW)) == "freigegeben"
    with pytest.raises(InputError, match="kein bekannter Baustein"):
        approve_design(
            life.model_copy(update={"design": design(components=[design().components[0]])}), NOW
        )
    with pytest.raises(InputError, match="Noch kein Entwurf"):
        approve_design(Lifecycle(project=PROJECT), NOW)


def test_design_rows_round_trip():
    rows = design_rows(design())
    assert rows["interfaces"][0] == {
        "ID": "S1",
        "Name": "Buchung anlegen",
        "Anbieter": "B3",
        "Nutzer": "B2",
        "Eingabe": "raum: Text, datum: Datum",
        "Ausgabe": "buchung_id: Ganzzahl",
        "Fehler": "409 Raum belegt",
    }
    assert rows["steps"][2] == {
        "Ablauf": "A1",
        "Von": "B3",
        "An": "B2",
        "Art": "Antwort",
        "Schnittstelle": "S1",
        "Text": "",
    }
    assert rows_to_design(rows) == design()


def test_a_field_marked_with_a_question_mark_is_optional():
    assert [(f.name, f.required) for f in text_to_fields("raum: Text, notiz?: Text")] == [
        ("raum", True),
        ("notiz", False),
    ]
    with pytest.raises(InputError, match="'raum' braucht die Form 'name: Typ'"):
        text_to_fields("raum")


def test_unreadable_design_rows_say_which_table_and_row():
    rows = design_rows(design())
    rows["interfaces"][0]["Eingabe"] = "raum"
    rows["steps"].append({"Ablauf": None, "Von": None})  # an empty row the editor adds
    rows["steps"].insert(0, {**rows["steps"][0], "Ablauf": "A9"})
    with pytest.raises(InputError) as err:
        rows_to_design(rows)
    assert str(err.value).splitlines() == [
        "Schnittstellen, Zeile 1 (S1): 'raum' braucht die Form 'name: Typ'",
        "Schritte, Zeile 1: unbekannter Ablauf 'A9'",
    ]


def test_a_flow_without_steps_and_an_empty_design_are_reported():
    rows = design_rows(design())
    rows["steps"] = []
    with pytest.raises(InputError, match=r"Zeile 1 \(A1\): Ablauf 'A1' hat keine Schritte"):
        rows_to_design(rows)
    with pytest.raises(InputError, match="Noch kein Entwurf"):
        rows_to_design({"components": [], "interfaces": [], "flows": [], "steps": []})


def test_a_design_that_misses_a_muss_requirement_goes_back_to_claude(api, tmp_path):
    from test_agent_loop import read_log, reply

    from pm_agent.tracking import agent_runs

    replies, requests = api
    two = requirements(need("R1"), need("R2", title="Stornieren", sources=["K2"]))
    second = {**design().flows[0].model_dump(), "id": "A2", "requirement_ids": ["R2"]}
    whole = design(flows=[*design().model_dump()["flows"], second])
    replies += [
        reply([call("submit_entwurf", design().model_dump(mode="json"), "c1")]),
        reply([call("submit_entwurf", whole.model_dump(mode="json"), "c2")]),
    ]
    result = lifecycle.run_design(PROJECT, charter(), two, log_dir=tmp_path)
    assert result == whole
    sent = json.dumps(requests[0], ensure_ascii=False)
    assert "Stornieren" in sent and "hours_per_week" not in sent  # no team data
    assert "'R2' (Stornieren) hat keinen Ablauf" in json.dumps(
        requests[1]["input"][-1], ensure_ascii=False
    )
    assert read_log(tmp_path, "entwurf")["outcome"] == "entwurf"
    assert [(r["Agent"], r["Ergebnis"]) for r in agent_runs(tmp_path)] == [("Entwurf", "Entwurf")]


def test_the_design_document_lists_parts_contracts_and_draws_each_flow():
    life = Lifecycle(project=PROJECT, charter=charter(), requirements=ONE, design=design())
    text = lifecycle.design_document(life)
    assert text.startswith("# Entwurf")
    assert "**Stand:** Entwurf, nicht freigegeben" in text
    assert "| B1 | Studierende | Rolle | – |" in text
    assert (
        "| S1 | Buchung anlegen | B3 | B2 | raum: Text, datum: Datum | buchung_id: Ganzzahl "
        "| 409 Raum belegt |" in text
    )
    assert "### A1 · Raum buchen\n\nDient: R1\n\n```mermaid\nsequenceDiagram" in text
    approved = lifecycle.design_document(approve_design(life, NOW))
    assert "**Stand:** Freigegeben am 16.11.2026 10:00" in approved
    with pytest.raises(InputError, match="kein Dokument"):
        lifecycle.design_document(Lifecycle(project=PROJECT))


def test_a_renamed_flow_whose_steps_still_name_the_old_id_says_so():
    rows = design_rows(design())
    rows["flows"][0]["ID"] = "A2"
    with pytest.raises(InputError) as err:
        rows_to_design(rows)
    lines = str(err.value).splitlines()
    assert lines[0] == "Schritte, Zeile 1: unbekannter Ablauf 'A1'"
    assert lines[-1] == "Abläufe, Zeile 1 (A2): Ablauf 'A2' hat keine Schritte"


def test_an_acceptance_criterion_id_is_used_once():
    twice = need("R1")
    twice["criteria"] = [{"id": "R1.1", "text": "a"}, {"id": "R1.1", "text": "b"}]
    assert check_requirements(
        requirements(twice, need("R2", sources=["K2"])), charter()
    ).errors == ["Anforderung 'R1': das Akzeptanzkriterium 'R1.1' ist mehrfach vergeben"]


@pytest.mark.parametrize(
    "run",
    [
        lambda: lifecycle.run_charter(PROJECT, log_dir=None),
        lambda: lifecycle.run_requirements(PROJECT, charter(), log_dir=None),
        lambda: lifecycle.run_design(PROJECT, charter(), requirements(need("R1")), log_dir=None),
        lambda: lifecycle.run_cases(PROJECT, requirements(need("R1")), None, log_dir=None),
    ],
)
def test_the_agents_before_the_plan_get_dates_the_german_way(run, monkeypatch):
    # The Testplan agent wrote "2026-12-10 10:00" into its steps: it took the dates of the
    # project as it got them.
    sent = []

    def capture(name, submission, data, log_dir, on_round):
        sent.append(data)
        raise lifecycle.InputError("nur die Eingabe geprüft")

    monkeypatch.setattr(lifecycle, "run_submission", capture)
    with pytest.raises(lifecycle.InputError):
        run()
    assert "09.11.2026" in sent[0]
    assert not re.findall(r"\d{4}-\d{2}-\d{2}", sent[0])
