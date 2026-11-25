"""D14 : chaque couleur de texte du design system garde un contraste WCAG AA (>= 4,5:1) sur chaque fond, en thème sombre et clair.

Mesuré le 24/11 : pire cas 4,65 (`--neg` sur `--surface-3`, sombre) et 5,03 (`--text-3` sur `--surface-3`, clair). Un nouveau jeton de couleur
qui passerait sous le seuil fait échouer ce test au lieu de rendre un texte illisible."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parents[2] / "patrick" / "webapp" / "static" / "patrick.css").read_text(encoding="utf-8")
TEXT = re.compile(r"(text|pos|neg|warn|info|brand)")
SURFACE = re.compile(r"(bg|surface)")


def _block(selector: str) -> dict[str, str]:
    start = CSS.index(selector + " {")
    depth, end = 0, start
    for i, ch in enumerate(CSS[start:], start):
        depth += (ch == "{") - (ch == "}")
        if ch == "}" and depth == 0:
            end = i
            break
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", CSS[start:end]))


def _lum(hex_: str) -> float:
    c = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


@pytest.mark.parametrize("selector", [":root", ':root[data-theme="light"]'])
def test_every_text_colour_is_readable_on_every_surface(selector):
    tokens = _block(selector)
    texts = {k: v for k, v in tokens.items() if TEXT.match(k)}
    surfaces = {k: v for k, v in tokens.items() if SURFACE.match(k)}
    assert len(texts) >= 6 and len(surfaces) >= 3
    low = [(t, s, round(_ratio(tv, sv), 2)) for t, tv in texts.items() for s, sv in surfaces.items() if _ratio(tv, sv) < 4.5]
    assert low == [], f"contraste < 4,5:1 : {low}"
