# Entwurf Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 3 "Entwurf": Claude drafts components, typed interface contracts and flows from the requirements, Python checks them and draws the sequence diagrams, the project lead edits and approves.

**Architecture:** Same pattern as the phases Projektauftrag and Anforderungen in `src/pm_agent/lifecycle.py`: pydantic models in `models.py`, check + approval + table rows + agent + document in `lifecycle.py`, drawing in a new `diagram.py`, one page `views/entwurf.py`. The approved design reaches the planning agent as context only.

**Tech Stack:** Python 3.11, pydantic v2, Streamlit 1.67, pytest (+ `streamlit.testing.v1.AppTest`), ruff, uv. No new dependency.

**Spec:** `04-Prototyp/pm_agent/docs/entwurf-design.md` (approved 16.11.2026, typed fields).

All paths below are relative to `04-Prototyp/pm_agent`. Run commands there.

## Global Constraints

- No new dependency, no script from a CDN; the SVG is built in Python.
- Claude never writes diagram code; diagrams come from `Flow` steps and `Interface` contracts.
- UI text, check messages, prompts, templates: German. Code, comments, commits: English.
- Messages follow Batch 1 form, e.g. `Ablauf 'A1', Schritt 3: …`, `Die Schnittstellen-ID 'S1' ist mehrfach vergeben`.
- Field name pattern `^[A-Za-z_][A-Za-z0-9_]*$`; type: non-empty, no `,` `;` `:`; error meaning: no `;`.
- Every user/Claude text shown with `st.markdown`/`st.caption`/`st.error` goes through `ui.as_text`; in documents through `workbench._md`.
- No live API calls in tests (use the `api` fixture). Tests must not touch `data/` or `logs/` (use the `local` fixture).
- Old `vorhaben.json` without `design`/`design_ok` must still load.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.

## Review Focus

1. A step that sends to itself (sender == receiver) must draw as a loop and pass the checks (no contract violation when it names no interface). Test in Task 4 and Task 2.
2. A flow step naming an interface whose provider was deleted from the components must give an error, not a `KeyError`. Test in Task 2.
3. Text with `<`, `&`, `"` in titles or field types must yield well-formed SVG (parse with `xml.etree`). Test in Task 4.
4. Steps table rows pointing at a flow ID that is not in the flows table: one error naming the row, not silently dropped. Test in Task 3.
5. Requirements changed after the design was approved: design state `geändert`, planning gets no design. Test in Task 1 and Task 7.

---

### Task 1: Models and approval state

**Files:**
- Modify: `src/pm_agent/models.py`, `src/pm_agent/lifecycle.py`
- Test: `tests/test_models.py`, `tests/test_lifecycle.py`

**Interfaces:**
- Produces in `models.py`: `FieldName`, `TypeName`, `DataField(name, type, required=True)`, `ErrorCase(code: Ref, meaning)`, `Component(id, name, kind: Literal["Rolle","Komponente","Fremdsystem"], purpose="")`, `Interface(id, name, provider: Ref, consumers: list[Ref] (min 1), input=[], output=[], errors=[])`, `Step(sender: Ref, receiver: Ref, kind: Literal["Aufruf","Antwort"]="Aufruf", interface: Ref | None = None, text="")`, `Flow(id, title, requirement_ids: list[Ref]=[], steps (min 1))`, `Design(components (min 1), interfaces=[], flows (min 1))`.
- Produces in `lifecycle.py`: `Lifecycle.design: Design | None = None`, `Lifecycle.design_ok: Approval | None = None`, `design_state(life) -> State`, `approved_design(life) -> Design | None`. (`approve_design` comes in Task 2, with the check it needs.)

- [ ] **Step 1: Write failing tests**
  - `test_models.py::test_a_design_rejects_bad_field_names_and_types`: `DataField(name="1x", type="Text")`, `DataField(name="a", type="dict[str, int]")` and `ErrorCase(code="409", meaning="a; b")` raise `ValidationError`; `DataField(name="raum_id", type="Liste[Termin]")` is valid.
  - `test_lifecycle.py::test_an_old_file_without_design_still_loads`: write the JSON of `Lifecycle(project=PROJECT)` without the two keys, `load` returns `design is None`.
  - `test_lifecycle.py::test_the_design_approval_holds_until_anything_upstream_changes`: `design_state` goes `offen` → `entwurf` → `freigegeben` after setting `design_ok=Approval(at=NOW, digest=lifecycle._design_digest(life))`; changing `requirements` (or charter, or project) makes it `geändert` and `approved_design` returns `None`. Approval does **not** require approved requirements (soft gate): approving a design on unapproved requirements works.
- [ ] **Step 2:** `uv run pytest tests/test_models.py tests/test_lifecycle.py -q` → FAIL (import errors).
- [ ] **Step 3: Implement.** Digest: `_digest(life.project, life.charter, life.requirements, life.design)`. `meaning` uses the existing `_no_semicolon` validator.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5: Commit** `feat(models): components, typed interfaces and flows of the design`.

### Task 2: `check_design`

**Files:** Modify `src/pm_agent/lifecycle.py`; Test `tests/test_lifecycle.py`

**Interfaces:**
- Consumes: Task 1 models, `Check`.
- Produces: `check_design(design: Design, requirements: Requirements | None) -> Check`; `approve_design(life, now) -> Lifecycle` (raises `InputError` "Noch kein Entwurf zum Freigeben." or the joined errors of `check_design(life.design, life.requirements)`, like `approve_requirements`). Test: approving on unapproved requirements works (soft gate); a design with errors raises.

- [ ] **Step 1: Write failing tests**, one per rule of the spec section "Prüfung", each asserting the exact message list. Fixture `design(**changes)` builds: Rolle `B1` Studierende, Komponente `B2` Web, Komponente `B3` Server; interface `S1` "Buchung anlegen", provider `B3`, consumers `[B2]`, input `raum: Text, datum: Datum`, output `buchung_id: Ganzzahl`, errors `409 Raum belegt`; flow `A1` for `R1` with steps B1→B2 (no interface), B2→B3 Aufruf S1, B3→B2 Antwort S1. Tests:
  - errors 1–6 (duplicates incl. field names and error codes; unknown/Rolle provider; unknown sender/receiver/interface; direction against the contract; unused interface; unknown requirement, Muss without flow),
  - warnings (Soll/Kann without flow; flow without requirement; step between two non-roles without interface; component in no flow; `requirements=None` → `["Ohne Anforderungen lässt sich der Entwurf nicht gegen sie prüfen"]` and no rule-6 errors),
  - Review Focus 1: a step B3→B3 without interface gives no error;
  - Review Focus 2: a step naming `S1` after `B3` is removed gives the unknown-provider and unknown-receiver errors, no exception.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement (direction rule: `Aufruf` needs `receiver == provider and sender in consumers`; `Antwort` the reverse; skip the direction check when the interface or a component is unknown). **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat(lifecycle): check the design against the requirements`.

### Task 3: Table rows

**Files:** Modify `src/pm_agent/lifecycle.py`; Test `tests/test_lifecycle.py`

**Interfaces:**
- Produces: `COMPONENT_COLUMNS = ["ID","Name","Art","Aufgabe"]`, `INTERFACE_COLUMNS = ["ID","Name","Anbieter","Nutzer","Eingabe","Ausgabe","Fehler"]`, `FLOW_COLUMNS = ["ID","Titel","Anforderungen"]`, `STEP_COLUMNS = ["Ablauf","Von","An","Art","Schnittstelle","Text"]`; `design_rows(design) -> dict[str, list[dict]]` with keys `"components","interfaces","flows","steps"`; `rows_to_design(rows: dict[str, list[dict]]) -> Design` (raises `InputError`, one line per bad row: `Schnittstellen, Zeile 2 (S2): …`); `fields_text(fields) -> str` (`raum: Text, notiz?: Text`), `text_to_fields(text) -> list[DataField]`, `errors_text`/`text_to_errors` (`409 Raum belegt; 404 Raum unbekannt`).

- [ ] **Step 1: Failing tests:** round trip `rows_to_design(design_rows(d)) == d` for the Task 2 fixture; `notiz?: Text` → `required=False`; a field without `:` → InputError naming the row; Review Focus 4: a step row with `Ablauf = "A9"` → `InputError` matching `Schritte, Zeile 1: unbekannter Ablauf 'A9'`; empty editor rows skipped like `rows_to_requirements`.
- [ ] **Steps 2–4:** run FAIL → implement (reuse `_cell`, `_split`, `_reason`) → PASS.
- [ ] **Step 5: Commit** `feat(lifecycle): the design as four editable tables`.

### Task 4: Diagrams

**Files:** Create `src/pm_agent/diagram.py`; Test `tests/test_diagram.py`

**Interfaces:**
- Consumes: `Design`, `Flow`.
- Produces: `sequence_svg(flow: Flow, design: Design) -> str`, `sequence_mermaid(flow: Flow, design: Design) -> str`.

- [ ] **Step 1: Failing tests:**
  - SVG parses with `xml.etree.ElementTree.fromstring`; participants in order of first appearance (`B1, B2, B3` → three header `<text>` with the component names); one `<line>`/`<path>` arrow per step with class `call` or `reply`; the call label is `S1 Buchung anlegen(raum, datum)`, the reply label `buchung_id`; a step without interface is labelled with its `text`.
  - Review Focus 1: a self step draws a `<path class="self">`.
  - Review Focus 3: a component named `A<B & "C"` still parses.
  - Mermaid: starts with `sequenceDiagram`, has `actor B1 as Studierende` for a Rolle, `participant B2 as Web`, `B2->>B3: S1 Buchung anlegen(raum, datum)`, `B3-->>B2: buchung_id`; `;` and `#` in labels become `#59;` and `#35;`.
- [ ] **Steps 2–4:** FAIL → implement (`html.escape`, `stroke="currentColor"`, column width 170, row height 44; sizes are the builder's call) → PASS.
- [ ] **Step 5: Commit** `feat(diagram): sequence diagrams drawn from flows and contracts`.

### Task 5: Agent, prompt, document

**Files:** Modify `src/pm_agent/lifecycle.py`, `src/pm_agent/tracking.py` (`AGENTS["entwurf"] = "Entwurf"`); Create `src/pm_agent/prompts/entwurf.md`, `src/pm_agent/templates/entwurf.md`; Test `tests/test_lifecycle.py`

**Interfaces:**
- Produces: `run_design(project, charter, requirements, log_dir=LOG_DIR, on_round=None) -> Design` (tool `submit_entwurf`, noun `Entwurf`, check `check_design(d, requirements).errors`); `design_document(life) -> str` (raises `InputError` without project or design).

- [ ] **Step 1: Failing tests** with the `api` fixture, like `test_requirements_that_miss_a_criterion_are_rejected`: first reply has a Muss requirement without flow → rejection names it; second accepted; requests contain the requirement titles and no team data; log prefix `entwurf`, outcome `entwurf`; `agent_runs` lists `("Entwurf","Entwurf")`. Document test: has `## Bausteine`, an interface table row `| S1 | Buchung anlegen | B3 | B2 | raum: Text, datum: Datum | buchung_id: Ganzzahl | 409 Raum belegt |`, a ```` ```mermaid ```` block per flow, and the `Stand` line like the other documents.
- [ ] **Step 2:** FAIL. **Step 3:** prompt content per spec section "Agent" (roles from the charter's stakeholders, IDs `B1`/`S1`/`A1`, the type list, at most about 8 flows; German). **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat(lifecycle): Claude drafts the design; the design as a document`.

### Task 6: Page Entwurf and the project path

**Files:** Create `views/entwurf.py`; Modify `app.py` (Vorbereiten: `st.Page("views/entwurf.py", title="Entwurf", icon=":material/account_tree:")` after Anforderungen), `src/pm_agent/ui.py` (`JOURNEY` gets `("entwurf", "Entwurf", "Python zeichnet die Abläufe")` after anforderungen, `PAGES["entwurf"] = ("views/entwurf.py", "Zum Entwurf")`, `FIELD_PREFIXES` adds `"design_"`, journey uses `design_state`); Test `tests/test_app.py`

**Interfaces:**
- Consumes: Tasks 1–5; `ui.saved_lifecycle`, `store`, `heading`, `phase_chip`, `run_with_progress`, `as_text`.
- Session keys: `design_replace`, `design_version`, editors `design_{table}_{version}`.

- [ ] **Step 1: Failing AppTests** (use `local`, `with_charter`, `approve_needs`, `edit_table`, `steps`):
  - without requirements: info pointing to Anforderungen; draft button disabled without project;
  - draft with a monkeypatched `lifecycle.run_design` returning the Task 2 fixture → four tables filled, diagram panel shows one `st.html` containing `<svg`;
  - editing the steps table to break the direction → error shown, approve disabled; fixing it → approve → chip `Entwurf` `freigegeben`;
  - `steps(at)` on any phase page has 6 entries with `Entwurf` third.
- [ ] **Steps 2–4:** FAIL → build the page after `views/anforderungen.py` (panels Grundlage, Entwurf vom Agenten, Bausteine in `st.tabs(["Bausteine","Schnittstellen","Abläufe","Schritte"])` with one save button, Diagramme with `st.selectbox` over flows, Freigabe, Dokument) → PASS.
- [ ] **Step 5: Commit** `feat(site): page Entwurf`.

### Task 7: Planning gets the approved design

**Files:** Modify `src/pm_agent/agent.py`, `views/planung.py`, `src/pm_agent/prompts/planning.md`, `src/pm_agent/prompts/replanning.md`; Test `tests/test_agent_loop.py`, `tests/test_app.py`

**Interfaces:**
- Produces: `Trace.design: Design | None = None`; `run_planning(..., design=None)` and `run_replanning(..., design=None)`; `_inputs` appends `Freigegebener Entwurf:` with `{"components": …, "interfaces": …}` only (no flows).

- [ ] **Step 1: Failing tests:** request text contains `Freigegebener Entwurf:` and the interface name, and not the flow ID `A1`, when a design is passed; unchanged request text without one (compare with the current golden assertion). AppTest Review Focus 5: approve design, then change requirements → planning page chip `Entwurf` shows `geändert` and the monkeypatched `run_planning` receives `design=None`.
- [ ] **Steps 2–4:** FAIL → implement (planung: `design = lifecycle.approved_design(life)`, pass to both runs; chip next to the Anforderungen chip; prompts: one sentence "Ist ein Entwurf freigegeben, schneide Aufgaben entlang seiner Komponenten und Schnittstellen.") → PASS.
- [ ] **Step 5: Commit** `feat(planung): the approved design is context for the planning agent`.

### Task 8: Docs and full check

**Files:** Modify `docs/lebenszyklus.md` (phase 3 `umgesetzt`, code table rows for `diagram.py`, `views/entwurf.py`), `README.md` (menu table, agent table, path with 6 steps).

- [ ] **Step 1:** Update both files.
- [ ] **Step 2:** `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` → all pass; `ls data logs` identical before and after.
- [ ] **Step 3:** Browser walk-through on localhost (built-in browser): fill the four tables by hand for one flow, see the SVG in light and dark, approve, see the path; desktop and 375 px width. No live API run.
- [ ] **Step 4: Commit** `docs: the Entwurf phase`.
