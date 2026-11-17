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


def test_error_messages_are_shown_as_written():
    # PR 44 and the commits before it: text in a message rendered as a link or an image.
    # An error can quote a cell, a file name or what Claude wrote; ui.as_text escapes it.
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
    first_cells = {line.split("|")[1] for line in readme.splitlines() if line.startswith("| ")}
    named = " ".join(first_cells)
    assert len(titles) > 10
    assert [title for title in titles if title not in named] == []
