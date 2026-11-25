"""Rules read from the source, for bugs that came back on a page the first fix did not touch.
Each test names the PRs that fixed the same bug by hand."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCES = [*ROOT.glob("*.py"), *(ROOT / "views").glob("*.py"), *(ROOT / "src").rglob("*.py")]
# Every one of these renders its text as Markdown.
MARKDOWN = {"markdown", "caption", "error", "warning", "info", "success", "write"}


def test_the_rules_below_find_the_sources():
    # A moved folder would leave them checking nothing.
    assert {"testplan.py", "ui.py", "app.py"} <= {source.name for source in SOURCES}


def test_every_page_table_keeps_unsaved_edits_through_a_page_change():
    # PR 40 and PR 53 fixed lost edits page by page, and the Testplan was missed. A table
    # goes through ui.kept_editor; the Planung keeps its two tables on its own.
    for source in (ROOT / "views").glob("*.py"):
        if source.name != "planung.py":
            assert "st.data_editor(" not in source.read_text(encoding="utf-8"), source.name


def test_current_test_results_and_signoffs_use_evidence_helpers():
    found = []
    # Tracking and closing also manage historical records. Planung checks whether
    # there are records to preserve when offering the re-adoption choice.
    for source in SOURCES:
        if source.name in {"tracking.py", "closing.py", "planung.py"}:
            continue
        found += [
            f"{source.name}:{node.lineno}"
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
            if isinstance(node, ast.Attribute)
            and node.attr in {"results", "signoffs"}
            and isinstance(node.value, ast.Name)
            and node.value.id == "tracking"
        ]
    assert found == []


def test_error_messages_are_shown_as_written():
    # PR 44 and the commits before it: text in a message rendered as a link or an image.
    # An error can quote a cell, a file name or what the agent wrote; ui.as_text escapes it.
    # The reason for a damaged team.json names the place: a skill name is one.
    found = []
    for source in SOURCES:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        caught = {node.name for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)}
        for call in ast.walk(tree):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in MARKDOWN
                and call.args
                and isinstance(call.args[0], ast.JoinedStr)
            ):
                continue
            for part in call.args[0].values:
                if not isinstance(part, ast.FormattedValue):
                    continue
                value = part.value
                name = getattr(value, "id", None) or getattr(value, "attr", "")
                # A caught exception, or one kept for later as rest_error, state.x_error.
                if name in caught or name.endswith("_error"):
                    found.append(f"{source.name}:{call.lineno}")
    assert found == []


def test_the_readme_names_every_page_of_the_menu():
    # PR 19, 35, 49 and 54 brought the Startseite or the docs up to pages added before.
    titles = re.findall(r'st\.Page\("[^"]+", title="([^"]+)"', (ROOT / "app.py").read_text("utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    # A first cell names one or more pages: "Umsetzen · Test", "Über uns, Impressum".
    first_cells = [line.split("|")[1] for line in readme.splitlines() if line.startswith("| ")]
    named = {name.strip() for cell in first_cells for name in re.split("[·,]", cell)}
    assert len(titles) > 10
    assert [title for title in titles if title not in named] == []


def test_working_days_are_counted_in_planning_only():
    # Nine fixes (slack against critical path, free days as buffer, an end moved in calendar
    # days …) came from days counted again elsewhere. planning.py counts them; tracking.monday
    # only finds the start of a week.
    found = []
    for source in SOURCES:
        if source.name == "planning.py":
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        allowed = {
            line
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "monday"
            for line in range(node.lineno, node.end_lineno + 1)
        }
        found += [
            f"{source.name}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"days", "weekday", "isoweekday"}
            and node.lineno not in allowed
        ]
    assert found == []


def test_empty_cells_of_editable_tables_stay_empty():
    # Without a placeholder an empty cell reads "None" (Fertig am of every open task).
    missing = []
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "data_editor"
                and "placeholder" not in {k.arg for k in node.keywords}
            ):
                missing.append(f"{path.name}:{node.lineno}")
    assert not missing, missing


def test_findings_of_a_check_share_one_box_per_kind():
    # One box per finding stacked eleven boxes beside the table they came from: ui.messages.
    stacked = []
    for path in SOURCES:
        for loop in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(loop, ast.For):
                # Shown for each item; an error inside a try in the loop is one at a time.
                for statement in loop.body:
                    node = statement.value if isinstance(statement, ast.Expr) else None
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"error", "warning"}
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "st"
                    ):
                        stacked.append(f"{path.name}:{node.lineno}")
    assert not stacked, stacked


def test_the_project_path_names_each_step_like_the_menu():
    # "Prüfen" in the path above the title "Kontrolle": one step, two names.
    from pm_agent.ui import GROUPS, JOURNEY

    pages = re.findall(
        r'st\.Page\("views/(\w+)\.py", title="([^"]+)"', (ROOT / "app.py").read_text("utf-8")
    )
    titles = dict(pages)
    # The first page of a group stands in the menu under the name of the group.
    heads = {pages[0][0]: group for group, pages in GROUPS.items()}
    assert [
        (slug, name) for slug, name, _ in JOURNEY if titles[slug] != heads.get(slug, name)
    ] == []
    # Every other step is named in the tabs of its group as in the path.
    labels = {slug: label for pages in GROUPS.values() for slug, label in pages}
    assert [(slug, name) for slug, name, _ in JOURNEY if labels.get(slug, name) != name] == []


def test_numbers_to_fill_in_follow_the_language_of_the_browser():
    # Without a format, "0.0" with a point stood beside "76,5 h" on the Kontrolle.
    bare = []
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "NumberColumn"
                and "format" not in {k.arg for k in node.keywords}
            ):
                bare.append(f"{path.name}:{node.lineno}")
    assert not bare, bare


def test_the_menu_groups_pages_by_phase():
    # "Agenten" held seven pages, three of them without an agent, while four pages with one
    # stood under "Vorbereiten": the group said who acts, and said it wrongly.
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    groups = re.findall(r'^    "([^"]*)": \[', source, flags=re.M)
    assert groups == ["", "Umsetzen", "Mehr"]
    assert not (ROOT / "views" / "betrieb.py").exists()
    assert not (ROOT / "views" / "iteration.py").exists()


def test_no_text_shown_to_the_project_lead_names_the_model_claude():
    # A different model answers now, and the pages call it "der Agent". No string that
    # reaches a page or a document names Claude (the comments follow in the next rule).
    found = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and re.search("claude", node.value, re.I)
            ):
                found.append(f"{path.name}:{node.lineno}")
    assert not found, found


def test_texts_split_over_lines_keep_the_space_between_words():
    # "Der Agent entwirft" + "die Lessons Learned" read "entwirftdie" on the Abschluss.
    import io
    import itertools
    import tokenize

    glued = []
    for path in SOURCES:
        tokens = list(tokenize.generate_tokens(io.StringIO(path.read_text("utf-8")).readline))
        strings = [t for t in tokens if t.type not in (tokenize.NL, tokenize.COMMENT)]
        for first, second in itertools.pairwise(strings):
            if first.type == second.type == tokenize.STRING and first.end[0] < second.start[0]:
                left, right = first.string.rstrip("\"'"), second.string.lstrip("rbfRBF\"'")
                ends_in_word = left[-1:].isalpha() and not left.endswith("\\n")
                if ends_in_word and right[:1].isalpha():
                    glued.append(f"{path.name}:{first.start[0]}")
    assert not glued, glued


def test_the_menu_shows_one_entry_per_group_and_hides_the_rest():
    # Thirteen entries were too many to scan. The pages of a group are tabs on its page; the
    # menu shows its first page only, and every other page of the group is hidden there.
    from pm_agent.ui import GROUPS

    entries = re.findall(
        r'st\.Page\("views/(\w+)\.py", title="([^"]+)"[^)]*?(visibility="hidden")?\)',
        (ROOT / "app.py").read_text("utf-8"),
    )
    shown = [title for _, title, hidden in entries if not hidden]
    assert shown == [
        "Startseite", "Vorbereiten", "Planung", "Durchführung", "Kontrolle", "Abschluss",
        "KI-Lab", "Info",
    ]  # fmt: skip
    hidden = {slug for slug, _, hidden in entries if hidden}
    rest = {slug for pages in GROUPS.values() for slug, _ in pages[1:]}
    assert hidden == rest


def test_no_page_shows_a_document_again_below_its_download():
    # A "Vorschau" under each download repeated the tables above it, on seven pages.
    found = [
        f"{path.name}:{node.lineno}"
        for path in (ROOT / "views").glob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "expander"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and str(node.args[0].value).startswith("Vorschau")
    ]
    assert found == []


def test_every_page_with_a_check_opens_with_its_verdict():
    # Errors and warnings stood below the tables they came from; the result was hard to find.
    # A page that shows the findings of a check (ui.messages) says the result on top too.
    missing = [
        path.name
        for path in (ROOT / "views").glob("*.py")
        if "messages(" in (text := path.read_text(encoding="utf-8")) and "verdict(" not in text
    ]
    assert missing == []


def test_what_the_agents_read_has_its_dates_and_numbers_written_the_german_way():
    # The agents repeat numbers and dates as they get them: "Fortschritt bei 0.0" in the
    # status report, "2026-12-10" in the steps of a test case. The input of an agent before
    # or after the plan goes through tracking.as_shown. (The planning agent keeps ISO dates:
    # it sends them back in set_absence. Lessons keep the weeks for their refs.)
    unshown = []
    for name in ("lifecycle.py", "followup.py"):
        tree = ast.parse((ROOT / "src" / "pm_agent" / name).read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef) or not (
                function.name.startswith("run_") or function.name == "facts"
            ):
                continue
            for call in ast.walk(function):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "dumps"
                    and not (
                        call.args
                        and isinstance(call.args[0], ast.Call)
                        and getattr(call.args[0].func, "id", "") == "as_shown"
                    )
                ):
                    unshown.append(f"{name}:{call.lineno}")
    assert unshown == []


def test_no_text_says_the_data_go_to_openai():
    # The data go to the service in OPENAI_BASE_URL (the school's endpoint), not necessarily to
    # OpenAI. Consent and data notes name it through ui.ai_service; the KI-Lab page names the
    # host of the endpoint the lab is configured with.
    lab = ROOT.parent / "ki_lab" / "web" / "app.js"
    found = [
        f"{path.name}:{number}"
        for path in [*SOURCES, lab]
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\ban (die OpenAI API|OpenAI)\b(?! model)", line)
        and not line.lstrip().startswith("#")
    ]
    assert found == []


def test_no_function_binds_a_module_constant_as_its_default():
    # `def load_team(path=TEAM_FILE)` takes the value at import. A script or test that then
    # points workbench.TEAM_FILE (or agent.LOG_DIR, lab_server.PORT) elsewhere still read and
    # wrote the real data/ and logs/ (found while recording the demo, 22.11.2026). Defaults
    # are None and the constant is read inside, at call time.
    found = []
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                args = node.args
                for default in [*args.defaults, *(d for d in args.kw_defaults if d)]:
                    if isinstance(default, ast.Name) and re.search(
                        r"(_DIR|_FILE|_CSV|PORT)$", default.id
                    ):
                        found.append(f"{path.name}:{node.lineno} {node.name}={default.id}")
    assert found == []


def test_existing_defects_and_incidents_are_updated_with_model_copy():
    # Building `Defect(id=..., ...)` or `Incident(id=..., ...)` from form fields resets
    # fields the form does not carry (`status`, `fixed_on`, `on`) to their defaults.
    found = [
        f"{path.name}:{node.lineno}"
        for path in SOURCES
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") in {"Defect", "Incident"}
        and "id" in {kw.arg for kw in node.keywords}
    ]
    assert found == []


def test_the_log_folder_has_one_name():
    # `from pm_agent.agent import LOG_DIR` copies the folder at import: pointing
    # agent.LOG_DIR elsewhere later leaves the copy behind. Use `agents.LOG_DIR` instead.
    found = [
        f"{path.name}:{node.lineno}"
        for path in SOURCES
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and any(a.name == "LOG_DIR" for a in node.names)
    ]
    assert found == []


def test_no_comment_or_docstring_names_the_model_claude():
    # The model is not Claude any more; comments and docstrings say "the agent" like the
    # pages. Only the folder `.claude/` may appear.
    found = [
        f"{path.name}:{number}"
        for path in SOURCES
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "Claude" in line
    ]
    assert found == []


def test_every_kept_editor_raises_its_version_before_rerun_on_save():
    # Without raising the version before `st.rerun()`, `kept_editor` sees the newly saved
    # basis with the old dirty_version and warns "Der gespeicherte Stand wurde inzwischen
    # geändert" right after the project lead's own save.
    missing = []
    for path in (ROOT / "views").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        versions = {
            node.args[1].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "kept_editor"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
        }
        blocks = [
            block
            for node in ast.walk(tree)
            if isinstance(node, ast.If | ast.Try)
            for block in (node.body, node.orelse)
        ]
        raised_before_rerun = {
            target.attr
            for block in blocks
            if any(
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr == "rerun"
                for stmt in block
            )
            for stmt in block
            if isinstance(stmt, ast.Assign)
            for target in stmt.targets
            if isinstance(target, ast.Attribute)
        }
        for version in sorted(versions - raised_before_rerun):
            missing.append(f"{path.name}:{version}")
    assert missing == []


def test_no_view_builds_a_dataframe_from_a_raw_model_dump():
    # `pd.DataFrame([i.model_dump(mode="json") ...])` exposed English field names and ISO
    # dates on the German page instead of German column titles and DD.MM.YYYY.
    found = [
        f"{path.name}:{node.lineno}"
        for path in (ROOT / "views").glob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "DataFrame"
        and any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and inner.func.attr == "model_dump"
            for inner in ast.walk(node)
        )
    ]
    assert found == []


def _calls(node: ast.AST, name: str) -> bool:
    """Whether `node` calls a function or method of this name somewhere inside."""
    return any(
        isinstance(call, ast.Call)
        and (getattr(call.func, "id", None) == name or getattr(call.func, "attr", None) == name)
        for call in ast.walk(node)
    )


def test_every_save_that_reruns_the_page_says_so():
    # PR 99 (UX review): saves and approvals on nine pages reran the page without a word. Say
    # it with ui.notify before st.rerun() (a page's change() helper does that itself). Reruns
    # that show their own result need no notice: the KI-Lab once started, and the proposal of
    # the agent in the Planung.
    silent = []
    for path in [*(ROOT / "views").glob("*.py"), ROOT / "src" / "pm_agent" / "ui.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for field in ("body", "orelse"):
                block = getattr(node, field, None)
                if not isinstance(block, list):
                    continue
                for index, stmt in enumerate(block):
                    if not (isinstance(stmt, ast.Expr) and _calls(stmt, "rerun")):
                        continue
                    told = any(_calls(before, "notify") for before in block[:index])
                    if isinstance(node, ast.If) and _calls(node.test, "change"):
                        told = True
                    if not told:
                        silent.append(path.name)
    assert sorted(silent) == ["ki_lab.py", "planung.py"], (
        "Call ui.notify('… gespeichert.') right before st.rerun()"
    )


def test_every_callback_that_saves_says_so():
    # The same for buttons that save in a callback (review of PR 99): through the page's
    # change() helper, which notifies, or with ui.notify of its own.
    saves = {"save_if_current", "store", "save_team", "adopt", "append_run"}
    silent = []
    for path in (ROOT / "views").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        callbacks = {
            keyword.value.id
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            for keyword in call.keywords
            if keyword.arg in ("on_click", "on_change") and isinstance(keyword.value, ast.Name)
        }
        for function in ast.walk(tree):
            if not (isinstance(function, ast.FunctionDef) and function.name in callbacks):
                continue
            if any(_calls(function, name) for name in saves) and not _calls(function, "notify"):
                silent.append(f"{path.name}:{function.name}")
    # The export of the Planung is answered by the download itself.
    assert silent == ["planung.py:record_export"], "Call ui.notify in the callback"


def test_notices_go_through_one_helper():
    # One look and one place for them: ui.notify, shown by app.py.
    found = [
        f"{source.name}:{node.lineno}"
        for source in SOURCES
        if source.name != "ui.py"
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and node.attr == "toast"
    ]
    assert found == [], "Use ui.notify instead of st.toast"


def test_an_approved_phase_hides_its_approval_instead_of_greying_it_out():
    # PR 99: "… freigeben" stayed on four pages, greyed out, under "Freigegeben am …".
    shown = []
    for path in (ROOT / "views").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.If):
                continue
            for call in ast.walk(node.test):
                label = call.args[0] if isinstance(call, ast.Call) and call.args else None
                if not (
                    getattr(call, "func", None) is not None
                    and getattr(call.func, "attr", None) == "button"
                    and isinstance(label, ast.Constant)
                    and str(label.value).endswith(" freigeben")
                ):
                    continue
                guard = node.test.values[0] if isinstance(node.test, ast.BoolOp) else None
                if not (
                    isinstance(node.test.op if guard else None, ast.And)
                    and isinstance(guard, ast.Compare)
                    and isinstance(guard.ops[0], ast.NotEq)
                    and getattr(guard.comparators[0], "value", None) == "freigegeben"
                ):
                    shown.append(f"{path.name}:{call.lineno}")
    assert len(list((ROOT / "views").glob("*.py"))) > 10
    assert shown == [], "Leave the button out once approved: `if phase != 'freigegeben' and …`"


CSS = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
# Movement in a reduced-motion block: the value each token gets there.
STILL = {
    "--rise": "0px",
    "--lift-y": "0px",
    "--lift-y-card": "0px",
    "--nudge": "0px",
    "--pushed": "1",
}


def _rules(css: str) -> list[tuple[str, str]]:
    """Selector and body of every rule, comments removed; nested blocks flattened."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def test_motion_uses_one_set_of_durations():
    # Motion of the UX review (task 2): one curve and a few durations in :root, so the same
    # kind of change moves the same everywhere. A literal duration or another curve slips
    # past that (review of the motion PR: the diagram of the Startseite was left out).
    found = []
    for selector, body in _rules(CSS):
        if ":root" in selector:
            continue
        for declaration in body.split(";"):
            name, _, value = declaration.partition(":")
            name = name.strip()
            if not name.startswith(("transition", "animation")) or value.strip() == "none":
                continue
            literal = re.search(r"\b\d*\.?\d+m?s\b", value)
            curve = name in ("transition", "animation", "transition-timing-function")
            if literal or (curve and "var(--ease)" not in value):
                found.append(f"{selector.strip()}: {declaration.strip()}")
    assert found == [], "Use var(--press|--hover|--state|--enter|--page) and var(--ease)"


def test_motion_moves_nothing_that_reflows_the_page():
    # Only what the compositor can move cheaply, or colours: a transition on size, position
    # or the flow of the text makes the page reflow on every frame.
    layout = (
        r"\b(all|width|height|inset|top|left|right|bottom|margin[\w-]*|padding[\w-]*|[\w-]*gap"
        r"|grid[\w-]*|flex[\w-]*|font-size|line-height|letter-spacing|border-width)\b"
    )
    found = [
        selector.strip()
        for selector, body in _rules(CSS)
        for declaration in body.split(";")
        if re.match(r"\s*transition(-property)?\s*:", declaration)
        and re.search(layout, declaration.split(":", 1)[1])
    ]
    keyframes = re.findall(r"@keyframes\s+(\w+)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}", CSS)
    moving = {name for name, body in keyframes if re.search(layout + r"\s*:", body)}
    assert found == [] and moving == set()


def test_reduced_motion_stops_everything_that_travels():
    # Asked for less motion, nothing travels, lifts or gives way: every movement token is
    # set to stand still there, and each one is used by a rule.
    block = CSS[CSS.index("@media (prefers-reduced-motion: reduce)") :]
    for token, still in STILL.items():
        assert re.search(rf"{token}:\s*{still};", block), token
        assert f"var({token})" in CSS, token
    # Streamlit animates the height of an expander itself; app.py holds it still (review of
    # the motion PR).
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "matchMedia('(prefers-reduced-motion: reduce)')" in app
