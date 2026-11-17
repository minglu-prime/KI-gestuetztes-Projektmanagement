"""PM-Agent website: name, logo and the menu. Every menu entry is a script in views/. Not in
pages/: Streamlit treats that folder as its old kind of multipage app (see the test about a
link to a page as first visit in tests/test_app.py).

Run from 04-Prototyp/pm_agent:  uv run --env-file .env streamlit run app.py
"""

from pathlib import Path

import streamlit as st

from pm_agent.ui import PAGES, journey

ROOT = Path(__file__).parent

st.set_page_config(page_title="PM-Agent", page_icon=":material/view_timeline:", layout="wide")
state = st.session_state

MENU = {
    "": [st.Page("views/startseite.py", title="Startseite", icon=":material/home:")],
    "Vorbereiten": [
        st.Page("views/auftrag.py", title="Projektauftrag", icon=":material/flag:"),
        st.Page("views/anforderungen.py", title="Anforderungen", icon=":material/checklist:"),
        st.Page("views/entwurf.py", title="Entwurf", icon=":material/account_tree:"),
        st.Page("views/testplan.py", title="Testplan", icon=":material/rule:"),
    ],
    "Agenten": [
        st.Page("views/planung.py", title="Planung", icon=":material/view_timeline:"),
        st.Page("views/durchfuehrung.py", title="Durchführung", icon=":material/task_alt:"),
        st.Page("views/testlauf.py", title="Test", icon=":material/bug_report:"),
        st.Page("views/kontrolle.py", title="Kontrolle", icon=":material/monitoring:"),
        st.Page("views/abschluss.py", title="Abschluss", icon=":material/flag_circle:"),
        st.Page("views/betrieb.py", title="Betrieb", icon=":material/settings:"),
    ],
    "Experiment": [st.Page("views/ki_lab.py", title="KI-Lab", icon=":material/science:")],
    "Info": [
        st.Page("views/ueber_uns.py", title="Über uns", icon=":material/groups:"),
        st.Page("views/impressum.py", title="Impressum", icon=":material/gavel:"),
    ],
}
page = st.navigation(MENU)
section = next(name for name, pages in MENU.items() if page.url_path in [p.url_path for p in pages])

st.html(ROOT / "assets" / "style.css")
with st.container(
    key="topbar", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
):
    # Streamlit serves every page as English and has no setting for it. Marked as German, a
    # browser does not offer to translate the page and a screen reader reads it as German.
    # The script rides with the brand: an element of its own would add a gap above the bar.
    st.html(
        '<div class="brand">PM-AGENT<small>KI IM PROJEKTMANAGEMENT</small></div>'
        '<script>document.documentElement.lang = "de"</script>',
        width="content",
        unsafe_allow_javascript=True,
    )
    # The group has no logo yet. Put a file here and it shows; without one the bar says what
    # the site is.
    logo = next(
        (p for p in (ROOT / "assets" / "logo.svg", ROOT / "assets" / "logo.png") if p.exists()),
        None,
    )
    if logo:
        st.image(str(logo), width=120)
    else:
        st.html('<span class="badge">PROTOTYP · HSBI PROJEKTGRUPPE 4</span>', width="content")

# The Planung page restores its table editors after a visit to another page.
state.page_changed = state.get("page") != page.url_path
state.page = page.url_path
# A container of its own per page: a page change mounts new content, which is what the
# page transition in assets/style.css hangs on.
with st.container(key=f"page-{page.url_path or 'startseite'}"):
    if section:
        st.html(f'<p class="eyebrow">{section}</p>')
    if page.url_path in PAGES:  # the pages of a phase
        journey(page.url_path)
    page.run()
