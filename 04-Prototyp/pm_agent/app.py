"""PM-Agent website: name, logo and the menu. Every menu entry is a script in pages/.

Run from 04-Prototyp/pm_agent:  uv run --env-file .env streamlit run app.py
"""

from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent

st.set_page_config(page_title="PM-Agent", page_icon=":material/view_timeline:", layout="wide")
state = st.session_state

page = st.navigation(
    {
        "": [st.Page("pages/startseite.py", title="Startseite", icon=":material/home:")],
        "Agenten": [
            st.Page("pages/planung.py", title="Planung", icon=":material/view_timeline:"),
            st.Page("pages/durchfuehrung.py", title="Durchführung", icon=":material/task_alt:"),
            st.Page("pages/kontrolle.py", title="Kontrolle", icon=":material/monitoring:"),
        ],
        "Experiment": [st.Page("pages/ki_lab.py", title="KI-Lab", icon=":material/science:")],
        "Info": [
            st.Page("pages/ueber_uns.py", title="Über uns", icon=":material/groups:"),
            st.Page("pages/impressum.py", title="Impressum", icon=":material/gavel:"),
        ],
    }
)

name, logo_slot = st.columns([5, 1], vertical_alignment="center")
name.title("PM-Agent")
# The group has no logo yet. Put a file here and it shows; nothing is drawn without one.
logo = next(
    (p for p in (ROOT / "assets" / "logo.svg", ROOT / "assets" / "logo.png") if p.exists()), None
)
if logo:
    logo_slot.image(str(logo), width=120)

# The Planung page restores its table editors after a visit to another page.
state.page_changed = state.get("page") != page.url_path
state.page = page.url_path
page.run()
