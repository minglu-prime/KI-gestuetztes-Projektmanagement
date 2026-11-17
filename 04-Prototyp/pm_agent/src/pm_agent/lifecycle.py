"""Before the plan: the Projektauftrag (charter) and the requirements (PRD).

Every phase works the same way: Claude drafts the artefact, Python checks it against the
artefact before it (traceability), the project lead changes and approves it. An approval
holds the digest of the artefact together with everything upstream of it; when any of that
changes, the approval is stale ("geändert") and downstream phases no longer count on it.

No Streamlit in here. The file lives in data/ like the adopted project and is git-ignored.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, ValidationError

from pm_agent.agent import LOG_DIR, run_submission
from pm_agent.diagram import sequence_mermaid
from pm_agent.models import (
    Cases,
    Charter,
    Component,
    Criterion,
    DataField,
    Design,
    ErrorCase,
    Flow,
    Interface,
    Project,
    Requirement,
    Requirements,
    Step,
)
from pm_agent.tools import Submission
from pm_agent.tracking import _fill
from pm_agent.workbench import DATA_DIR, InputError, _cell, _date, _md, _reason

FILE = DATA_DIR / "vorhaben.json"

State = Literal["offen", "entwurf", "geändert", "freigegeben"]
REQUIREMENT_COLUMNS = [
    "ID",
    "Titel",
    "User Story",
    "Priorität",
    "Akzeptanzkriterien",
    "Erfolgskriterien",
]


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: datetime
    digest: str  # of the artefact and everything upstream of it, when it was approved


class Lifecycle(BaseModel):
    """The phases before the plan. `project` holds what the project lead enters (idea,
    start, deadline): Claude never fills in dates."""

    model_config = ConfigDict(extra="forbid")

    project: Project | None = None
    charter: Charter | None = None
    charter_ok: Approval | None = None
    requirements: Requirements | None = None
    requirements_ok: Approval | None = None
    design: Design | None = None
    design_ok: Approval | None = None
    cases: Cases | None = None
    cases_ok: Approval | None = None


class Check(NamedTuple):
    errors: list[str]
    warnings: list[str]


def load(path: Path | None = None) -> Lifecycle | None:
    """None if nothing was started. A damaged file is an error, not an empty start."""
    path = path or FILE  # read at call time: tests point it to a temporary folder
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:  # saved by an editor in another encoding
        raise InputError(f"{path.name} ist beschädigt: kein UTF-8 ({err.reason})") from err
    except OSError as err:
        raise InputError(f"{path.name} konnte nicht gelesen werden: {err}") from err
    try:
        return Lifecycle.model_validate(json.loads(text))
    except (ValueError, ValidationError) as err:
        raise InputError(f"{path.name} ist beschädigt: {_reason(err)}") from err


def save(life: Lifecycle, path: Path | None = None) -> None:
    path = path or FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(life.model_dump_json(indent=2), encoding="utf-8")


def _digest(*parts: BaseModel | None) -> str:
    data = [part.model_dump(mode="json") if part is not None else None for part in parts]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _charter_digest(life: Lifecycle) -> str:
    return _digest(life.project, life.charter)


def _requirements_digest(life: Lifecycle) -> str:
    return _digest(life.project, life.charter, life.requirements)


def _design_digest(life: Lifecycle) -> str:
    return _digest(life.project, life.charter, life.requirements, life.design)


def _cases_digest(life: Lifecycle) -> str:
    return _digest(life.project, life.charter, life.requirements, life.design, life.cases)


def _state(artefact: Any, approval: Approval | None, digest: str) -> State:
    if artefact is None:
        return "offen"
    if approval is None:
        return "entwurf"
    return "freigegeben" if approval.digest == digest else "geändert"


def charter_state(life: Lifecycle | None) -> State:
    if life is None:
        return "offen"
    return _state(life.charter, life.charter_ok, _charter_digest(life))


def requirements_state(life: Lifecycle | None) -> State:
    if life is None:
        return "offen"
    return _state(life.requirements, life.requirements_ok, _requirements_digest(life))


def design_state(life: Lifecycle | None) -> State:
    if life is None:
        return "offen"
    return _state(life.design, life.design_ok, _design_digest(life))


def approved_design(life: Lifecycle | None) -> Design | None:
    """The design as approved, or None. It does not need approved requirements: the gates
    are soft."""
    if life is None or design_state(life) != "freigegeben":
        return None
    return life.design


def cases_state(life: Lifecycle | None) -> State:
    if life is None:
        return "offen"
    return _state(life.cases, life.cases_ok, _cases_digest(life))


def approved_cases(life: Lifecycle | None) -> Cases | None:
    if life is None or cases_state(life) != "freigegeben":
        return None
    return life.cases


def approve_cases(life: Lifecycle, now: datetime) -> Lifecycle:
    """The project lead approves the test plan. Raises InputError while it has errors."""
    if life.cases is None:
        raise InputError("Noch keine Testfälle zum Freigeben.")
    errors = check_cases(life.cases, life.requirements, life.design).errors
    if errors:
        raise InputError("\n".join(errors))
    return life.model_copy(update={"cases_ok": Approval(at=now, digest=_cases_digest(life))})


def check_cases(cases: Cases, requirements: Requirements | None, design: Design | None) -> Check:
    """Errors: duplicate IDs, unknown criteria, interfaces and error codes, a case without
    what it tests, a Muss criterion without a case. Warnings: other criteria, interfaces and
    error codes without a case."""
    items = cases.cases
    errors = _twice([c.id for c in items], "Die Testfall-ID '{}' ist mehrfach vergeben")
    criteria = (
        {c.id: (r, c) for r in requirements.items for c in r.criteria} if requirements else None
    )
    contracts = {i.id: i for i in design.interfaces} if design else None
    for case in items:
        if criteria is not None:
            errors += [
                f"Testfall '{case.id}' nennt das unbekannte Akzeptanzkriterium '{cid}'"
                for cid in case.criteria
                if cid not in criteria
            ]
        if case.interface and contracts is not None:
            contract = contracts.get(case.interface)
            if contract is None:
                errors.append(
                    f"Testfall '{case.id}' nennt die unbekannte Schnittstelle '{case.interface}'"
                )
            elif case.error_code and case.error_code not in {e.code for e in contract.errors}:
                errors.append(
                    f"Testfall '{case.id}': die Schnittstelle '{contract.id}' kennt den "
                    f"Fehlercode '{case.error_code}' nicht"
                )
        if case.kind == "Akzeptanz" and not case.criteria:
            errors.append(f"Akzeptanztest '{case.id}' nennt kein Akzeptanzkriterium")
        if case.kind == "Integration" and not case.interface:
            errors.append(f"Integrationstest '{case.id}' nennt keine Schnittstelle")
    warnings = []
    if criteria is None:
        warnings.append(
            "Ohne Anforderungen lässt sich nicht prüfen, ob jedes Akzeptanzkriterium einen "
            "Testfall hat"
        )
    else:
        tested = {cid for case in items for cid in case.criteria}
        for cid, (need, criterion) in criteria.items():
            if cid not in tested:
                text = (
                    f"{need.priority}-Anforderung '{need.id}': das Akzeptanzkriterium '{cid}' "
                    f"({criterion.text}) hat keinen Testfall"
                )
                (errors if need.priority == "Muss" else warnings).append(text)
    if contracts is None:
        warnings.append(
            "Ohne Entwurf lässt sich nicht prüfen, ob jede Schnittstelle einen Integrationstest hat"
        )
    else:
        integrated = {c.interface for c in items if c.kind == "Integration"}
        provoked = {(c.interface, c.error_code) for c in items if c.error_code}
        warnings += [
            f"Die Schnittstelle '{i.id}' ({i.name}) hat keinen Integrationstest"
            for i in contracts.values()
            if i.id not in integrated
        ]
        warnings += [
            f"Der Fehlercode '{e.code}' der Schnittstelle '{i.id}' hat keinen Testfall"
            for i in contracts.values()
            for e in i.errors
            if (i.id, e.code) not in provoked
        ]
    return Check(list(dict.fromkeys(errors)), list(dict.fromkeys(warnings)))


def approved_requirements(life: Lifecycle | None) -> list[Requirement] | None:
    """The requirements the plan is traced to, or None while they are not approved as
    they stand."""
    if life is None or life.requirements is None or requirements_state(life) != "freigegeben":
        return None
    return life.requirements.items


def approve_charter(life: Lifecycle, now: datetime) -> Lifecycle:
    """The project lead approves the charter. Raises InputError while it has errors."""
    if life.charter is None:
        raise InputError("Noch kein Projektauftrag zum Freigeben.")
    errors = check_charter(life.charter).errors
    if errors:
        raise InputError("\n".join(errors))
    return life.model_copy(update={"charter_ok": Approval(at=now, digest=_charter_digest(life))})


def approve_requirements(life: Lifecycle, now: datetime) -> Lifecycle:
    """The project lead approves the requirements. Raises InputError while they have
    errors."""
    if life.requirements is None:
        raise InputError("Noch keine Anforderungen zum Freigeben.")
    errors = check_requirements(life.requirements, life.charter).errors
    if errors:
        raise InputError("\n".join(errors))
    return life.model_copy(
        update={"requirements_ok": Approval(at=now, digest=_requirements_digest(life))}
    )


def check_charter(charter: Charter) -> Check:
    ids = [c.id for c in charter.success_criteria]
    errors = [
        f"Das Erfolgskriterium '{cid}' ist mehrfach vergeben"
        for cid in dict.fromkeys(ids)
        if ids.count(cid) > 1
    ]
    return Check(errors, [])


def check_requirements(requirements: Requirements, charter: Charter | None) -> Check:
    """Errors: duplicate IDs, no Muss requirement, and, with a charter, sources that are
    not its success criteria and success criteria no requirement serves."""
    items = requirements.items
    ids = [r.id for r in items]
    errors = [
        f"Die Anforderungs-ID '{rid}' ist mehrfach vergeben"
        for rid in dict.fromkeys(ids)
        if ids.count(rid) > 1
    ]
    for r in items:
        errors += [
            f"Anforderung '{r.id}': das Akzeptanzkriterium '{cid}' ist mehrfach vergeben"
            for cid in dict.fromkeys(c.id for c in r.criteria)
            if [c.id for c in r.criteria].count(cid) > 1
        ]
    if not any(r.priority == "Muss" for r in items):
        errors.append("Es gibt keine Muss-Anforderung: mindestens eine Muss-Anforderung ist nötig")
    if charter is None:
        warning = (
            "Ohne Projektauftrag lässt sich nicht prüfen, ob die Anforderungen seine "
            "Erfolgskriterien abdecken"
        )
        return Check(errors, [warning])
    known = {c.id for c in charter.success_criteria}
    errors += [
        f"Anforderung '{r.id}' nennt das unbekannte Erfolgskriterium '{source}'"
        for r in items
        for source in r.sources
        if source not in known
    ]
    served = {source for r in items for source in r.sources}
    errors += [
        f"Das Erfolgskriterium '{c.id}' ({c.text}) deckt keine Anforderung ab"
        for c in charter.success_criteria
        if c.id not in served
    ]
    warnings = [f"Anforderung '{r.id}' nennt kein Erfolgskriterium" for r in items if not r.sources]
    return Check(errors, warnings)


def _twice(ids: list[str], text: str) -> list[str]:
    """One message per ID that occurs more than once; `text` has a {} for the ID."""
    return [text.format(i) for i in dict.fromkeys(ids) if ids.count(i) > 1]


def check_design(design: Design, requirements: Requirements | None) -> Check:
    """Errors: duplicates, parts and interfaces that do not exist, steps against the
    contract, unused interfaces, and, with requirements, flows for unknown ones and Muss
    requirements without a flow. Checked against the requirements as they stand."""
    parts = {c.id: c for c in design.components}
    contracts = {i.id: i for i in design.interfaces}
    errors = _twice([c.id for c in design.components], "Die Baustein-ID '{}' ist mehrfach vergeben")
    errors += _twice(
        [i.id for i in design.interfaces], "Die Schnittstellen-ID '{}' ist mehrfach vergeben"
    )
    errors += _twice([f.id for f in design.flows], "Die Ablauf-ID '{}' ist mehrfach vergeben")
    for i in design.interfaces:
        where = f"Schnittstelle '{i.id}': "
        errors += _twice(
            [f.name for f in i.input], where + "das Eingabefeld '{}' ist mehrfach vergeben"
        )
        errors += _twice(
            [f.name for f in i.output], where + "das Ausgabefeld '{}' ist mehrfach vergeben"
        )
        errors += _twice(
            [e.code for e in i.errors], where + "der Fehlercode '{}' ist mehrfach vergeben"
        )
        if i.provider not in parts:
            errors.append(f"{where}der Anbieter '{i.provider}' ist kein bekannter Baustein")
        elif parts[i.provider].kind == "Rolle":
            errors.append(
                f"{where}der Anbieter '{i.provider}' ist eine Rolle; eine Rolle bietet keine "
                "Schnittstelle an"
            )
        errors += [
            f"{where}der Nutzer '{c}' ist kein bekannter Baustein"
            for c in i.consumers
            if c not in parts
        ]
    loose = []
    for flow in design.flows:
        for number, step in enumerate(flow.steps, start=1):
            where = f"Ablauf '{flow.id}', Schritt {number}: "
            unknown = [
                f"{where}der {role} '{part}' ist kein bekannter Baustein"
                for role, part in [("Absender", step.sender), ("Empfänger", step.receiver)]
                if part not in parts
            ]
            errors += unknown
            if step.interface is None:
                if (
                    not unknown
                    and step.sender != step.receiver
                    and "Rolle" not in (parts[step.sender].kind, parts[step.receiver].kind)
                ):
                    loose.append(
                        f"{where}{step.sender} und {step.receiver} reden ohne Schnittstelle "
                        "miteinander"
                    )
                continue
            contract = contracts.get(step.interface)
            if contract is None:
                errors.append(f"{where}die Schnittstelle '{step.interface}' ist unbekannt")
                continue
            if unknown:
                continue
            users = ", ".join(contract.consumers)
            if step.kind == "Aufruf":
                ok = step.receiver == contract.provider and step.sender in contract.consumers
                rule = f"ein Aufruf von '{contract.id}' geht von {users} an {contract.provider}"
            else:
                ok = step.sender == contract.provider and step.receiver in contract.consumers
                rule = f"eine Antwort von '{contract.id}' geht von {contract.provider} an {users}"
            if not ok:
                errors.append(f"{where}{rule}, nicht von {step.sender} an {step.receiver}")
    used = {step.interface for flow in design.flows for step in flow.steps}
    errors += [
        f"Die Schnittstelle '{i.id}' ({i.name}) kommt in keinem Ablauf vor"
        for i in design.interfaces
        if i.id not in used
    ]
    warnings = []
    if requirements is None:
        warnings.append("Ohne Anforderungen lässt sich der Entwurf nicht gegen sie prüfen")
    else:
        known = {r.id for r in requirements.items}
        errors += [
            f"Ablauf '{flow.id}' dient der unbekannten Anforderung '{rid}'"
            for flow in design.flows
            for rid in flow.requirement_ids
            if rid not in known
        ]
        served = {rid for flow in design.flows for rid in flow.requirement_ids}
        for r in requirements.items:
            if r.id not in served:
                text = f"{r.priority}-Anforderung '{r.id}' ({r.title}) hat keinen Ablauf"
                (errors if r.priority == "Muss" else warnings).append(text)
    warnings += [
        f"Ablauf '{f.id}' dient keiner Anforderung" for f in design.flows if not f.requirement_ids
    ]
    warnings += loose
    present = {part for flow in design.flows for s in flow.steps for part in (s.sender, s.receiver)}
    warnings += [
        f"Der Baustein '{c.id}' ({c.name}) kommt in keinem Ablauf vor"
        for c in design.components
        if c.id not in present
    ]
    # Two interfaces with the same ID give the same messages twice.
    return Check(list(dict.fromkeys(errors)), list(dict.fromkeys(warnings)))


def approve_design(life: Lifecycle, now: datetime) -> Lifecycle:
    """The project lead approves the design. Raises InputError while it has errors. The
    requirements need not be approved: the gates are soft."""
    if life.design is None:
        raise InputError("Noch kein Entwurf zum Freigeben.")
    errors = check_design(life.design, life.requirements).errors
    if errors:
        raise InputError("\n".join(errors))
    return life.model_copy(update={"design_ok": Approval(at=now, digest=_design_digest(life))})


def requirement_rows(requirements: Requirements) -> list[dict[str, Any]]:
    """The requirements as rows of the table editor. Acceptance criteria are separated by
    semicolons, success criteria by commas."""
    return [
        {
            "ID": r.id,
            "Titel": r.title,
            "User Story": r.story,
            "Priorität": r.priority,
            "Akzeptanzkriterien": "; ".join(f"{c.id}: {c.text}" for c in r.criteria),
            "Erfolgskriterien": ", ".join(r.sources),
        }
        for r in requirements.items
    ]


def rows_to_requirements(rows: list[dict[str, Any]]) -> Requirements:
    """The edited table as requirements. Raises InputError naming each unreadable row."""
    items, errors = [], []
    for number, row in enumerate(rows, start=1):
        rid = _cell(row.get("ID"))
        if not rid and not _cell(row.get("Titel")):
            continue  # an empty row the editor adds
        try:
            items.append(
                Requirement(
                    id=rid,
                    title=_cell(row.get("Titel")),
                    story=_cell(row.get("User Story")),
                    priority=_cell(row.get("Priorität")),
                    criteria=_criteria(rid, row.get("Akzeptanzkriterien")),
                    sources=_split(row.get("Erfolgskriterien"), ","),
                )
            )
        except ValidationError as err:
            errors.append(f"Zeile {number} ({rid or 'ohne ID'}): {_reason(err)}")
    if errors:
        raise InputError("\n".join(errors))
    if not items:
        raise InputError("Noch keine Anforderung: Trag mindestens eine Zeile ein.")
    return Requirements(items=items)


COMPONENT_COLUMNS = ["ID", "Name", "Art", "Aufgabe"]
INTERFACE_COLUMNS = ["ID", "Name", "Anbieter", "Nutzer", "Eingabe", "Ausgabe", "Fehler"]
FLOW_COLUMNS = ["ID", "Titel", "Anforderungen"]
STEP_COLUMNS = ["Ablauf", "Von", "An", "Art", "Schnittstelle", "Text"]
# The four tables of the design, by key, with the name a message gives each.
DESIGN_TABLES = {
    "components": "Bausteine",
    "interfaces": "Schnittstellen",
    "flows": "Abläufe",
    "steps": "Schritte",
}


def fields_text(fields: list[DataField]) -> str:
    """Fields as "raum: Text, notiz?: Text"; the question mark marks an optional field."""
    return ", ".join(f"{f.name}{'' if f.required else '?'}: {f.type}" for f in fields)


def text_to_fields(text: str) -> list[DataField]:
    fields, errors = [], []
    for part in _split(text, ","):
        name, colon, kind = part.partition(":")
        name = name.strip()
        try:
            if not colon:
                raise ValueError
            fields.append(
                DataField(
                    name=name.removesuffix("?"), type=kind.strip(), required=not name.endswith("?")
                )
            )
        except (ValueError, ValidationError):
            errors.append(f"'{part}' braucht die Form 'name: Typ'")
    if errors:
        raise InputError("; ".join(errors))
    return fields


def errors_text(errors: list[ErrorCase]) -> str:
    return "; ".join(f"{e.code} {e.meaning}" for e in errors)


def text_to_errors(text: str) -> list[ErrorCase]:
    cases, errors = [], []
    for part in _split(text, ";"):
        code, _, meaning = part.partition(" ")
        try:
            cases.append(ErrorCase(code=code, meaning=meaning.strip()))
        except ValidationError:
            errors.append(f"'{part}' braucht die Form 'Code Bedeutung'")
    if errors:
        raise InputError("; ".join(errors))
    return cases


def design_rows(design: Design) -> dict[str, list[dict[str, Any]]]:
    """The design as the rows of its four tables. Steps carry the ID of their flow; their
    order in the table is their order in the flow."""
    return {
        "components": [
            {"ID": c.id, "Name": c.name, "Art": c.kind, "Aufgabe": c.purpose}
            for c in design.components
        ],
        "interfaces": [
            {
                "ID": i.id,
                "Name": i.name,
                "Anbieter": i.provider,
                "Nutzer": ", ".join(i.consumers),
                "Eingabe": fields_text(i.input),
                "Ausgabe": fields_text(i.output),
                "Fehler": errors_text(i.errors),
            }
            for i in design.interfaces
        ],
        "flows": [
            {"ID": f.id, "Titel": f.title, "Anforderungen": ", ".join(f.requirement_ids)}
            for f in design.flows
        ],
        "steps": [
            {
                "Ablauf": f.id,
                "Von": s.sender,
                "An": s.receiver,
                "Art": s.kind,
                "Schnittstelle": s.interface or "",
                "Text": s.text,
            }
            for f in design.flows
            for s in f.steps
        ],
    }


def rows_to_design(rows: dict[str, list[dict[str, Any]]]) -> Design:
    """The four edited tables as a design. Raises InputError naming table and row of each
    problem. Empty rows the editor adds are skipped."""
    errors: list[str] = []

    def read(table: str, key: str, make: Callable[[dict[str, Any]], Any]) -> list[Any]:
        made = []
        for number, row in enumerate(rows.get(table, []), start=1):
            rid = _cell(row.get(key))
            if not any(_cell(value) for value in row.values()):
                continue
            where = f"{DESIGN_TABLES[table]}, Zeile {number}" + (
                f" ({rid})" if rid and key == "ID" else ""
            )
            try:
                made.append(make(row))
            except InputError as err:
                errors.append(f"{where}: {err}")
            except ValidationError as err:
                errors.append(f"{where}: {_reason(err)}")
        return made

    components = read(
        "components",
        "ID",
        lambda r: Component(
            id=_cell(r.get("ID")),
            name=_cell(r.get("Name")),
            kind=_cell(r.get("Art")),
            purpose=_cell(r.get("Aufgabe")),
        ),
    )
    interfaces = read(
        "interfaces",
        "ID",
        lambda r: Interface(
            id=_cell(r.get("ID")),
            name=_cell(r.get("Name")),
            provider=_cell(r.get("Anbieter")),
            consumers=_split(r.get("Nutzer"), ","),
            input=text_to_fields(_cell(r.get("Eingabe"))),
            output=text_to_fields(_cell(r.get("Ausgabe"))),
            errors=text_to_errors(_cell(r.get("Fehler"))),
        ),
    )
    flow_ids = {_cell(r.get("ID")) for r in rows.get("flows", [])} - {""}
    steps: dict[str, list[Step]] = {}

    def step(row: dict[str, Any]) -> None:
        flow = _cell(row.get("Ablauf"))
        if flow not in flow_ids:
            raise InputError(f"unbekannter Ablauf '{flow}'")
        steps.setdefault(flow, []).append(
            Step(
                sender=_cell(row.get("Von")),
                receiver=_cell(row.get("An")),
                kind=_cell(row.get("Art")) or "Aufruf",
                interface=_cell(row.get("Schnittstelle")) or None,
                text=_cell(row.get("Text")),
            )
        )

    read("steps", "Ablauf", step)

    def flow(row: dict[str, Any]) -> Flow:
        fid = _cell(row.get("ID"))
        if fid and fid not in steps:  # say it in words, not as the model's "at least 1 item"
            raise InputError(f"Ablauf '{fid}' hat keine Schritte")
        return Flow(
            id=fid,
            title=_cell(row.get("Titel")),
            requirement_ids=_split(row.get("Anforderungen"), ","),
            steps=steps.get(fid, []),
        )

    flows = read("flows", "ID", flow)
    if errors:
        raise InputError("\n".join(errors))
    if not components and not flows:
        raise InputError("Noch kein Entwurf: Trag mindestens einen Baustein und einen Ablauf ein.")
    try:
        return Design(components=components, interfaces=interfaces, flows=flows)
    except ValidationError as err:
        raise InputError(f"Entwurf: {_reason(err)}") from err


def _criteria(rid: str, cell: Any) -> list[Any]:
    """The acceptance criteria of a table cell: "R1.1: text" keeps its ID, a plain text
    gets the next number. Only "<requirement ID>.<n>:" reads as an ID; any other colon is
    part of the text."""
    criteria = []
    for part in _split(cell, ";"):
        cid, colon, text = part.partition(":")
        cid = cid.strip()
        number = cid.removeprefix(f"{rid}.")
        if colon and cid.startswith(f"{rid}.") and number.isdigit():
            criteria.append({"id": cid, "text": text.strip()})
        else:
            criteria.append(part)
    return criteria


def criteria_lines(criteria: list[Criterion]) -> str:
    """Success criteria as text, one "K1: text" per line, for a text area."""
    return "\n".join(f"{c.id}: {c.text}" for c in criteria)


def lines_to_criteria(text: str) -> list[Criterion]:
    criteria, errors = [], []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        cid, colon, rest = line.partition(":")
        try:
            if not colon:
                raise ValueError
            criteria.append(Criterion(id=cid.strip(), text=rest.strip()))
        except (ValueError, ValidationError):
            errors.append(
                f"Zeile {number}: '{line.strip()}' braucht die Form 'K1: Text' "
                "(ID ohne Leerzeichen und Komma)"
            )
    if errors:
        raise InputError("\n".join(errors))
    return criteria


def lines(text: str) -> list[str]:
    """One item per non-empty line of a text area."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _split(value: Any, separator: str) -> list[str]:
    return [part.strip() for part in _cell(value).split(separator) if part.strip()]


def run_charter(
    project: Project,
    log_dir: Path | None = LOG_DIR,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> Charter:
    """Claude drafts the Projektauftrag from idea and dates. Only these go to the API, no
    team data. Raises AgentError."""
    submission = Submission(
        name="submit_auftrag",
        noun="Projektauftrag",
        description=(
            "Reicht den Projektauftrag ein. Lehnt ihn ab, wenn eine ID eines "
            "Erfolgskriteriums doppelt vorkommt, und nennt die Gründe."
        ),
        schema=Charter,
        check=lambda charter: check_charter(charter).errors,
    )
    data = json.dumps({"projekt": project.model_dump(mode="json")}, ensure_ascii=False, indent=2)
    return run_submission("auftrag", submission, data, log_dir, on_round)


def run_requirements(
    project: Project,
    charter: Charter | None,
    log_dir: Path | None = LOG_DIR,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> Requirements:
    """Claude drafts the requirements from the charter (or from the idea alone, without
    one). Python rejects them until every success criterion is served. Raises AgentError."""
    submission = Submission(
        name="submit_anforderungen",
        noun="Anforderungskatalog",
        description=(
            "Reicht die Anforderungen ein. Lehnt sie ab, wenn ein Erfolgskriterium des "
            "Projektauftrags von keiner Anforderung abgedeckt ist, eine Anforderung ein "
            "unbekanntes Erfolgskriterium nennt, eine ID doppelt vorkommt oder es keine "
            "Muss-Anforderung gibt, und nennt die Gründe."
        ),
        schema=Requirements,
        check=lambda requirements: check_requirements(requirements, charter).errors,
    )
    data = json.dumps(
        {
            "projekt": project.model_dump(mode="json"),
            "projektauftrag": charter.model_dump(mode="json") if charter else None,
        },
        ensure_ascii=False,
        indent=2,
    )
    return run_submission("anforderungen", submission, data, log_dir, on_round)


def run_design(
    project: Project,
    charter: Charter | None,
    requirements: Requirements | None,
    log_dir: Path | None = LOG_DIR,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> Design:
    """Claude drafts the design from charter and requirements; Python rejects it until it
    passes `check_design`. No team data goes to the API. Raises AgentError."""
    submission = Submission(
        name="submit_entwurf",
        noun="Entwurf",
        description=(
            "Reicht den Entwurf ein. Lehnt ihn ab, wenn ein Ablauf unbekannte Bausteine oder "
            "Schnittstellen nennt, einem Vertrag widerspricht, eine Schnittstelle in keinem "
            "Ablauf vorkommt, eine Muss-Anforderung keinen Ablauf hat oder eine ID doppelt "
            "vorkommt, und nennt die Gründe."
        ),
        schema=Design,
        check=lambda design: check_design(design, requirements).errors,
    )
    data = json.dumps(
        {
            "projekt": project.model_dump(mode="json"),
            "projektauftrag": charter.model_dump(mode="json") if charter else None,
            "anforderungen": requirements.model_dump(mode="json") if requirements else None,
        },
        ensure_ascii=False,
        indent=2,
    )
    return run_submission("entwurf", submission, data, log_dir, on_round)


def design_document(life: Lifecycle) -> str:
    """The design as Markdown: parts, contracts, and each flow with its Mermaid diagram."""
    design, project = life.design, life.project
    if design is None or project is None:
        raise InputError("Ohne Projektdaten und Entwurf gibt es kein Dokument.")
    parts = "\n".join(
        f"| {_md(c.id)} | {_md(c.name)} | {c.kind} | {_md(c.purpose) or '–'} |"
        for c in design.components
    )
    contracts = "\n".join(
        "| "
        + " | ".join(
            _md(cell) or "–"
            for cell in [
                i.id,
                i.name,
                i.provider,
                ", ".join(i.consumers),
                fields_text(i.input),
                fields_text(i.output),
                errors_text(i.errors),
            ]
        )
        + " |"
        for i in design.interfaces
    )
    flows = "\n\n".join(
        f"### {_md(f.id)} · {_md(f.title)}\n\n"
        f"Dient: {_md(', '.join(f.requirement_ids)) or 'keiner Anforderung'}\n\n"
        f"```mermaid\n{sequence_mermaid(f, design)}\n```"
        for f in design.flows
    )
    return _fill(
        "entwurf.md",
        projekt=_md(project.idea),
        start=_date(project.start_date),
        deadline=_date(project.deadline),
        stand=_stand(design_state(life), life.design_ok),
        bausteine=parts,
        schnittstellen=contracts or "| – | | | | | | |",
        ablaeufe=flows,
    )


def charter_document(life: Lifecycle) -> str:
    """The Projektauftrag as Markdown, with whether it is approved."""
    charter, project = life.charter, life.project
    if charter is None or project is None:
        raise InputError("Ohne Projektdaten und Projektauftrag gibt es kein Dokument.")
    return _fill(
        "projektauftrag.md",
        projekt=_md(project.idea),
        start=_date(project.start_date),
        deadline=_date(project.deadline),
        stand=_stand(charter_state(life), life.charter_ok),
        ziel=_md(charter.goal),
        nutzen=_md(charter.benefit),
        umfang=_items(charter.in_scope),
        nicht=_items(charter.out_of_scope),
        beteiligte=_items(charter.stakeholders),
        kriterien=_items(f"{c.id}: {c.text}" for c in charter.success_criteria),
        rahmen=_items(charter.constraints),
    )


def requirements_document(life: Lifecycle) -> str:
    """The requirements as Markdown: an overview, each one with its acceptance criteria
    (numbered R1.1, R1.2 …), and which requirements serve each success criterion."""
    requirements, project = life.requirements, life.project
    if requirements is None or project is None:
        raise InputError("Ohne Projektdaten und Anforderungen gibt es kein Dokument.")
    items = requirements.items
    overview = "\n".join(
        f"| {_md(r.id)} | {_md(r.title)} | {r.priority} | {_md(', '.join(r.sources)) or '–'} |"
        for r in items
    )
    single = "\n\n".join(
        f"### {_md(r.id)} · {_md(r.title)}\n\n*{_md(r.story)}* ({r.priority})\n\n"
        + "\n".join(f"- {_md(c.id)} {_md(c.text)}" for c in r.criteria)
        for r in items
    )
    if life.charter is None:
        trace = "Kein Projektauftrag: Die Anforderungen lassen sich nicht zurückverfolgen."
    else:
        trace = _items(
            f"{c.id} ({c.text}): "
            + (", ".join(r.id for r in items if c.id in r.sources) or "keine Anforderung")
            for c in life.charter.success_criteria
        )
    return _fill(
        "anforderungen.md",
        projekt=_md(project.idea),
        start=_date(project.start_date),
        deadline=_date(project.deadline),
        stand=_stand(requirements_state(life), life.requirements_ok),
        ueberblick=overview,
        einzeln=single,
        rueckverfolgung=trace,
    )


def _stand(state: State, approval: Approval | None) -> str:
    if state == "freigegeben" and approval is not None:
        return f"Freigegeben am {approval.at:%d.%m.%Y %H:%M}"
    if state == "geändert" and approval is not None:
        return (
            f"Seit der Freigabe am {approval.at:%d.%m.%Y %H:%M} geändert, nicht erneut freigegeben"
        )
    return "Entwurf, nicht freigegeben"


def _items(texts: Any) -> str:
    lines_ = [f"- {_md(text)}" for text in texts]
    return "\n".join(lines_) or "–"
