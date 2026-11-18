"""Check the effective bind address resolved by the Streamlit CLI."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.mark.parametrize("location", ["app", "repository", "elsewhere"])
def test_streamlit_cli_resolves_loopback_address_before_server_start(location, tmp_path):
    repo = APP.parents[2]
    if location == "app":
        cwd, entry = APP.parent, APP.name
    elif location == "repository":
        cwd, entry = repo, str(APP.relative_to(repo))
    else:
        cwd, entry = tmp_path, str(APP)
        config_dir = cwd / ".streamlit"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[server]\naddress = "0.0.0.0"\n', encoding="utf-8")

    # Exercise the real CLI and its config discovery in a fresh process. Stop at the
    # server entry point so the test needs no network socket, browser or credentials.
    probe = """
import sys
from unittest.mock import patch

from streamlit import config
from streamlit.web import bootstrap, cli

with patch.object(bootstrap, "run", side_effect=lambda *args: print(
    config.get_option("server.address")
)):
    cli.main(["run", sys.argv[1], "--server.headless=true"])
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("STREAMLIT_")}
    result = subprocess.run(
        [sys.executable, "-c", probe, entry],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert result.stdout.strip() in {"localhost", "127.0.0.1", "::1"}, result.stderr
