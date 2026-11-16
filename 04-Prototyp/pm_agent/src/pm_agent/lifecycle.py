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
from pm_agent.models import Charter, Criterion, Project, Requirement, Requirements
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


def requirement_rows(requirements: Requirements) -> list[dict[str, Any]]:
    """The requirements as rows of the table editor. Acceptance criteria are separated by
    semicolons, success criteria by commas."""
    return [
        {
            "ID": r.id,
            "Titel": r.title,
            "User Story": r.story,
            "Priorität": r.priority,
            "Akzeptanzkriterien": "; ".join(r.criteria),
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
                    criteria=_split(row.get("Akzeptanzkriterien"), ";"),
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
        + "\n".join(f"- {_md(r.id)}.{n} {_md(text)}" for n, text in enumerate(r.criteria, 1))
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
