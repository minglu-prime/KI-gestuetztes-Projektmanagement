from xml.etree import ElementTree

from test_lifecycle import design

from pm_agent.diagram import sequence_mermaid, sequence_svg

NS = {"s": "http://www.w3.org/2000/svg"}


def svg_of(d):
    return ElementTree.fromstring(sequence_svg(d.flows[0], d))


def test_the_svg_has_a_column_per_part_and_an_arrow_per_step():
    root = svg_of(design())
    names = [t.text for t in root.findall(".//s:g[@class='participant']/s:text", NS)]
    assert names == ["Studierende", "Web", "Server"]  # in the order they first appear
    arrows = [g[0] for g in root.findall(".//s:g[@class='step']", NS)]
    assert [a.get("class") for a in arrows] == ["call", "call", "reply"]
    labels = [t.text for t in root.findall(".//s:g[@class='step']/s:text", NS)]
    assert labels == ["wählt Raum und Datum", "S1 Buchung anlegen(raum, datum)", "buchung_id"]
    assert root.get("aria-label") == "Sequenzdiagramm A1: Raum buchen"


def test_a_step_to_itself_is_a_loop():
    flows = design().model_dump()["flows"]
    flows[0]["steps"].append({"sender": "B3", "receiver": "B3", "text": "prüft Belegung"})
    root = svg_of(design(flows=flows))
    assert root.findall(".//s:g[@class='step']", NS)[-1][0].get("class") == "self"


def test_names_with_markup_characters_stay_well_formed():
    components = design().model_dump()["components"]
    components[1]["name"] = 'A<B & "C"'
    root = svg_of(design(components=components))
    assert 'A<B & "C"' in [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]


def test_the_mermaid_text_uses_safe_aliases_and_the_contract():
    lines = sequence_mermaid(design().flows[0], design()).splitlines()
    assert lines == [
        "sequenceDiagram",
        "  actor p1 as Studierende",
        "  participant p2 as Web",
        "  participant p3 as Server",
        "  p1->>p2: wählt Raum und Datum",
        "  p2->>p3: S1 Buchung anlegen(raum, datum)",
        "  p3-->>p2: buchung_id",
    ]


def test_mermaid_special_characters_are_entities():
    flows = design().model_dump()["flows"]
    flows[0]["steps"][0]["text"] = "Raum #3; dann\nweiter"
    text = sequence_mermaid(design(flows=flows).flows[0], design(flows=flows))
    assert "  p1->>p2: Raum #35;3#59; dann weiter" in text.splitlines()
