"""Smoke test of the running site in real browsers: every page opens without an error, the
menu has its eight entries, and at 375 px nothing scrolls sideways.

Skipped unless PM_BROWSERS names the browsers, e.g. PM_BROWSERS=chromium,firefox,webkit (the
CI job) or PM_BROWSERS=chrome (the installed Chrome). Needs the `browser` dependency group:
    uv sync --group browser && uv run playwright install chromium firefox webkit
The site runs on an empty temporary folder (smoke_app.py), never on data/.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

BROWSERS = [b for b in os.environ.get("PM_BROWSERS", "").split(",") if b]
pytestmark = pytest.mark.skipif(not BROWSERS, reason="PM_BROWSERS is not set")

ROOT = Path(__file__).parents[1]
# Every page of the site by its address and expected heading (h1/h2): a silent fallback to
# the Startseite fails the check.
LEAD_PAGES = [
    ("", "Der Agent schlägt vor."),
    ("abschluss", "Abschluss"),
    ("anforderungen", "Anforderungen"),
    ("auftrag", "Projektauftrag"),
    ("durchfuehrung", "Durchführung"),
    ("entwurf", "Entwurf"),
    ("impressum", "Impressum"),
    ("ki_lab", "KI-Lab"),
    ("kontrolle", "Kontrolle"),
    ("planung", "Planung"),
    ("testlauf", "Test"),
    ("testplan", "Testplan"),
    ("ueber_uns", "Über uns"),
]
TEAM_PAGES = [
    ("?ansicht=Team", "Mein Bereich"),
    ("projektstand?ansicht=Team", "Projektstand"),
]
MENU = [
    "Startseite",
    "Vorbereiten",
    "Planung",
    "Durchführung",
    "Kontrolle",
    "Abschluss",
    "KI-Lab",
    "Info",
]
TEAM_MENU = ["Mein Bereich", "Projektstand", "KI-Lab", "Info"]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    port = free_port()
    folder = tmp_path_factory.mktemp("smoke")
    log_file = folder / "server.log"
    env = {
        **os.environ,
        "PM_SMOKE_DIR": str(folder),
        "PM_SMOKE_LAB_PORT": str(free_port()),
    }
    log = log_file.open("wb")  # a pipe nobody reads would stall the server once it is full
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(ROOT / "smoke_app.py"),
            "--server.headless=true",
            "--server.address=localhost",
            f"--server.port={port}",
            "--browser.gatherUsageStats=false",
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    url = f"http://localhost:{port}"
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"{url}/_stcore/health", timeout=1) as answer:
                    if answer.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail(f"Die Seite startete nicht:\n{log_file.read_text(errors='replace')}")
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)
        log.close()


@pytest.fixture(scope="module", params=BROWSERS)
def browser(request):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        name = request.param
        if name == "chrome":
            launched = p.chromium.launch(channel="chrome")
        else:
            launched = getattr(p, name).launch()
        yield launched
        launched.close()


def settled(page) -> None:
    """Wait until Streamlit has finished rendering the current run."""
    page.wait_for_selector('[data-testid="stMainBlockContainer"] :is(h1, h2, h3)', timeout=30_000)
    page.wait_for_function(
        "!document.querySelector('[data-stale=\"true\"]')",
        timeout=30_000,
    )


def opened(page, url: str) -> None:
    """Open `url` and wait until Streamlit has run the page to its end."""
    page.goto(url, wait_until="domcontentloaded")
    settled(page)


def heading_text(page) -> str:
    return page.locator('[data-testid="stMainBlockContainer"] :is(h1, h2)').first.inner_text()


def menu_titles(page) -> list[str]:
    # Each link starts with the name of its icon (a ligature of the icon font), then the title.
    links = page.locator('[data-testid="stSidebarNavLink"]').all_inner_texts()
    return [link.split(None, 1)[-1].strip() for link in links]


@pytest.mark.parametrize("width", [1440, 375])
def test_every_page_opens_without_an_error(site, browser, width):
    covered = {"startseite" if p == "" else p for p, _ in LEAD_PAGES} | {
        "mein_bereich" if p.startswith("?") else p.split("?")[0] for p, _ in TEAM_PAGES
    }
    assert covered == {p.stem for p in (ROOT / "views").glob("*.py")}

    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    for path, expected in [*LEAD_PAGES, *TEAM_PAGES]:
        url = f"{site}/{path}" if path and not path.startswith("?") else f"{site}{path}"
        opened(page, url)
        if page.locator('[data-testid="stException"]').count():
            errors.append(f"/{path}: Ausnahme auf der Seite")
        shown = heading_text(page)
        if expected not in shown:
            errors.append(f"/{path}: erwartete Überschrift '{expected}', sah '{shown}'")
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        if overflow > 0:
            errors.append(f"/{path}: {overflow} px waagrecht zu breit")
    page.close()
    assert errors == []


def test_the_menu_has_its_eight_entries(site, browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    opened(page, site)
    titles = menu_titles(page)
    page.close()
    assert titles == MENU


def test_team_view_opens_mein_bereich_and_projektstand_and_survives_reload(site, browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    opened(page, site)
    page.locator('[data-testid="stSidebar"]').get_by_text("Team", exact=True).click()
    page.locator('[data-testid="stMainBlockContainer"] h2', has_text="Mein Bereich").wait_for(
        timeout=30_000
    )
    page.get_by_text("Wähle links unter „Ich bin“ deinen Namen.").wait_for(
        state="visible", timeout=30_000
    )
    settled(page)
    assert menu_titles(page) == TEAM_MENU

    page.locator('[data-testid="stSidebarNavLink"]').filter(has_text="Projektstand").click()
    page.locator('[data-testid="stMainBlockContainer"] h2', has_text="Projektstand").wait_for(
        timeout=30_000
    )
    page.get_by_text("Noch kein Projekt übernommen.").wait_for(state="visible", timeout=30_000)
    settled(page)

    # Refreshing in Team view keeps the view and current page via query parameters.
    page.reload(wait_until="domcontentloaded")
    page.locator('[data-testid="stMainBlockContainer"] h2', has_text="Projektstand").wait_for(
        timeout=30_000
    )
    page.get_by_text("Noch kein Projekt übernommen.").wait_for(state="visible", timeout=30_000)
    settled(page)
    assert not page.locator('[data-testid="stException"]').count()
    assert menu_titles(page) == TEAM_MENU
    page.close()
