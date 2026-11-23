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
# Every page of the site by its address; "" is the Startseite.
PAGES = ["", *sorted(p.stem for p in (ROOT / "views").glob("*.py") if p.stem != "startseite")]
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


def opened(page, url: str) -> None:
    """Open `url` and wait until Streamlit has run the page to its end."""
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="stMainBlockContainer"] :is(h1, h2, h3)', timeout=30_000)
    page.wait_for_function(
        "!document.querySelector('[data-stale=\"true\"]')",
        timeout=30_000,
    )


@pytest.mark.parametrize("width", [1440, 375])
def test_every_page_opens_without_an_error(site, browser, width):
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    for path in PAGES:
        opened(page, f"{site}/{path}")
        if page.locator('[data-testid="stException"]').count():
            errors.append(f"/{path}: Ausnahme auf der Seite")
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        if overflow > 0:
            errors.append(f"/{path}: {overflow} px waagrecht zu breit")
    page.close()
    assert errors == []


def test_the_menu_has_its_eight_entries(site, browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    opened(page, site)
    links = page.locator('[data-testid="stSidebarNavLink"]').all_inner_texts()
    page.close()
    # Each link starts with the name of its icon (a ligature of the icon font), then the title.
    assert [link.split()[-1] for link in links] == MENU
