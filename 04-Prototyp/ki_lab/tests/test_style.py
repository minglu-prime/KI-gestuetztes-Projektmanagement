"""Small grey text must stay readable: WCAG 2.1 AA asks 4.5 to 1 for text below 18 px."""

import re
import unittest
from pathlib import Path

CSS = (Path(__file__).parents[1] / "web" / "style.css").read_text(encoding="utf-8")

# Every background in web/style.css that carries text in var(--muted): the page, the
# sidebar, cards, the diagram, the result boxes and the AI panel.
BACKGROUNDS = ["#f5f6f0", "#ecf0e7", "#ffffff", "#e7eddf", "#edf2e7", "#edf3e8"]


def luminance(colour):
    parts = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    red, green, blue = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in parts)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(text, back):
    high, low = sorted((luminance(text), luminance(back)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class StyleTest(unittest.TestCase):
    def test_muted_text_is_readable_on_every_background_it_sits_on(self):
        muted = re.search(r"--muted:(#[0-9a-f]{6})", CSS).group(1)
        for back in BACKGROUNDS:
            with self.subTest(back=back):
                self.assertGreaterEqual(contrast(muted, back), 4.5)


if __name__ == "__main__":
    unittest.main()
