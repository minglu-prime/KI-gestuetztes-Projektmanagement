"""Small text in the stylesheet stays readable (WCAG 2.1 AA: contrast of 4.5 to 1)."""

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
