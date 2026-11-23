"""The site on an empty temporary folder, for the browser smoke test (test_browsers.py).

Run as `streamlit run smoke_app.py` with PM_SMOKE_DIR set (next to app.py: Streamlit finds
the pages relative to the script it runs). Data, logs and the team go there, and the KI-Lab
is looked for on a port where nothing listens. The real data/ and logs/ stay untouched.
"""

import os
import runpy
from pathlib import Path

from pm_agent import agent, lab_server, lifecycle, tracking, workbench

folder = Path(os.environ["PM_SMOKE_DIR"])
tracking.PROJECT_FILE = folder / "data" / "projekt.json"
lifecycle.FILE = folder / "data" / "vorhaben.json"
workbench.DATA_DIR = folder / "data"
workbench.TEAM_FILE = folder / "data" / "team.json"
workbench.RUNS_CSV = folder / "logs" / "runs.csv"
agent.LOG_DIR = folder / "logs"
lab_server.PORT = int(os.environ["PM_SMOKE_LAB_PORT"])

runpy.run_path(str(Path(__file__).parent / "app.py"), run_name="__main__")
