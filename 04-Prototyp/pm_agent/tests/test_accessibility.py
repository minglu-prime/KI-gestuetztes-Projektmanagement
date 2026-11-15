"""What a reader with weak sight or a screen reader gets: contrast of small text (WCAG 2.1 AA,
4.5 to 1) and a description for every chart."""

import re
from pathlib import Path

CSS = (Path(__file__).parents[1] / "assets" / "style.css").read_text(encoding="utf-8")
COLOURS = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-f]{6})", CSS))
PAGE = "#f5f6f0"  # backgroundColor in .streamlit/config.toml


def _luminance(colour: str) -> float:
    parts = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    red, green, blue = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in parts)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(text: str, back: str) -> float:
    high, low = sorted((_luminance(text), _luminance(back)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_muted_text_is_readable_on_every_background_it_sits_on():
    # Labels of 10 to 13 px: on the page, on white cards and chips, and on the sage panels
    # (the diagram on the Startseite, the KI-Lab card).
    for back in (PAGE, "#ffffff", COLOURS["sage"]):
        assert _contrast(COLOURS["muted"], back) >= 4.5, back


def test_every_chart_on_a_page_says_what_it_shows():
    # A chart is a picture; ui.on_panel gives it the sentence a screen reader reads out.
    pages = Path(__file__).parents[1] / "pages"
    for page in pages.glob("*.py"):
        source = page.read_text(encoding="utf-8")
        assert source.count("st.altair_chart(") == source.count("on_panel("), page.name


def test_no_heading_reads_out_the_name_of_its_icon():
    # Streamlit gives an icon in Markdown role="img" and the English label "<name> icon": a
    # screen reader said "trending_up icon Prognose". ui.heading hides the icon instead.
    pages = Path(__file__).parents[1] / "pages"
    for page in pages.glob("*.py"):
        source = page.read_text(encoding="utf-8")
        assert not re.search(r"#+ (\{icon\}|:material/)", source), page.name


def test_heading_hides_the_icon_from_screen_readers():
    from streamlit.testing.v1 import AppTest

    def page():
        from pm_agent.ui import heading

        heading("trending_up", "Prognose & <Plan>")

    app = AppTest.from_function(page).run()
    assert not app.exception
    assert app.markdown[0].value == (
        '#### <span class="icon" aria-hidden="true">trending_up</span> Prognose &amp; &lt;Plan&gt;'
    )


def test_on_panel_sets_the_description_and_the_white_of_the_panel():
    import altair as alt

    from pm_agent.ui import on_panel

    spec = on_panel(alt.Chart().mark_bar(), "Balken je Aufgabe.").to_dict()
    assert spec["description"] == "Balken je Aufgabe."
    assert spec["background"] == "#ffffff"
