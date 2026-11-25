"""PM-Agent website: name, logo and the menu. Every menu entry is a script in views/. Not in
pages/: Streamlit treats that folder as its old kind of multipage app (see the test about a
link to a page as first visit in tests/test_app.py).

Run from 04-Prototyp/pm_agent:  uv run --env-file .env streamlit run app.py
"""

from pathlib import Path

import streamlit as st

from pm_agent.ui import NEW_MEMBER, PAGES, as_text, group_tabs, journey, show_notice
from pm_agent.workbench import InputError, load_team

ROOT = Path(__file__).parent
# Streamlit opens and closes an expander (and st.status) by animating its height for 0.5 s
# with the Web Animations API, also when the system asks for less motion; CSS cannot reach
# that. With less motion asked for, it gets no duration and opens and closes at once.
# ponytail: patches Element.animate for <details> only; drop it once Streamlit checks
# prefers-reduced-motion there itself.
STILL_DETAILS = (
    "if (!Element.prototype.animate.still) { const animate = Element.prototype.animate; "
    "Element.prototype.animate = function (frames, options) { const still = "
    "this.tagName === 'DETAILS' && matchMedia('(prefers-reduced-motion: reduce)').matches; "
    "return animate.call(this, frames, still ? { ...options, duration: 0 } : options); }; "
    "Element.prototype.animate.still = true; }"
)

st.set_page_config(page_title="PM-Agent", page_icon=":material/view_timeline:", layout="wide")
state = st.session_state

# One entry per group: the first page of a group stands for it, the other pages of the group
# are hidden here and open as tabs on top of the page (ui.GROUPS, ui.group_tabs).
MENU = {
    "": [
        st.Page("views/startseite.py", title="Startseite", icon=":material/home:"),
        st.Page("views/auftrag.py", title="Vorbereiten", icon=":material/flag:"),
        st.Page("views/anforderungen.py", title="Anforderungen", visibility="hidden"),
        st.Page("views/entwurf.py", title="Entwurf", visibility="hidden"),
        st.Page("views/testplan.py", title="Testplan", visibility="hidden"),
    ],
    "Umsetzen": [
        st.Page("views/planung.py", title="Planung", icon=":material/view_timeline:"),
        st.Page("views/durchfuehrung.py", title="Durchführung", icon=":material/task_alt:"),
        st.Page("views/kontrolle.py", title="Kontrolle", icon=":material/monitoring:"),
        st.Page("views/testlauf.py", title="Test", visibility="hidden"),
        st.Page("views/abschluss.py", title="Abschluss", icon=":material/flag_circle:"),
    ],
    "Mehr": [
        st.Page("views/ki_lab.py", title="KI-Lab", icon=":material/science:"),
        st.Page("views/ueber_uns.py", title="Info", icon=":material/info:"),
        st.Page("views/impressum.py", title="Impressum", visibility="hidden"),
    ],
}
# The view of a team member (ui.lead): their own details and tasks, where the project stands,
# and the lab to take part in. No sign-in: a view, not access control.
TEAM = {
    "": [
        st.Page("views/mein_bereich.py", title="Mein Bereich", icon=":material/person:"),
        st.Page("views/projektstand.py", title="Projektstand", icon=":material/monitoring:"),
    ],
    "Mehr": [
        st.Page("views/ki_lab.py", title="KI-Lab", icon=":material/science:"),
        st.Page("views/ueber_uns.py", title="Info", icon=":material/info:"),
        st.Page("views/impressum.py", title="Impressum", visibility="hidden"),
    ],
}
with st.sidebar:
    role = st.radio("Ansicht", ["Leitung", "Team"], horizontal=True, key="role")
    if role == "Team":
        if "me_next" in state:  # a new member saved their name on Mein Bereich
            state.me = state.pop("me_next")
        try:
            names = [m.name for m in load_team()]
        except InputError as err:
            names = []
            st.error(f"Das Team konnte nicht gelesen werden: {as_text(str(err))}")
        st.selectbox("Ich bin", [*names, NEW_MEMBER], key="me")
page = st.navigation(MENU if role == "Leitung" else TEAM)
# The Planung page restores its table editors after a visit to another page.
state.page_changed = state.get("page") != page.url_path
state.page = page.url_path

st.html(ROOT / "assets" / "style.css")
with st.container(
    key="topbar", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
):
    # Streamlit serves every page as English and has no setting for it. Marked as German, a
    # browser does not offer to translate the page and a screen reader reads it as German.
    # The script rides with the brand: an element of its own would add a gap above the bar.
    st.html(
        '<div class="brand">PM-AGENT<small>KI IM PROJEKTMANAGEMENT</small></div>'
        f'<script>{STILL_DETAILS} document.documentElement.lang = "de"</script>',
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

# A container of its own per page: a page change mounts a new one, which is what the page
# transition in assets/style.css hangs on.
show_notice()
home = "startseite" if role == "Leitung" else "mein_bereich"  # the first page has no url_path
with st.container(key=f"page-{page.url_path or home}"):
    group_tabs(page.url_path)
    if page.url_path in PAGES:  # the pages of a phase
        journey(page.url_path)
    page.run()
# Not reached when the page reruns: its notice then waits for the next run, above.
show_notice()
