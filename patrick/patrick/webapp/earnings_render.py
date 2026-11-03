"""Rendu HTML des résultats d'études (cellules formatées, graphiques SVG) : fonctions pures exposées aux gabarits Jinja.

Les graphiques sont des SVG sans script, colorés par les jetons CSS (`var(--brand)`...) donc corrects en thème clair et sombre.
Tout texte venu d'une étude (libellés, titres de tableau) passe par `escape` : un libellé hostile ne peut pas injecter de balise."""
from __future__ import annotations

import math

from markupsafe import Markup, escape

_DASH = Markup('<span class="na">—</span>')


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def fmt(value, kind: str = "str") -> Markup:
    """Formate une cellule selon sa nature (pct, pct0, num2, num3, int, p, str)."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return _DASH
    if kind == "str" or not _num(value):
        return Markup(escape(str(value)))
    if kind == "pct":
        return Markup(escape(f"{value * 100:+.2f} %"))
    if kind == "pct0":
        return Markup(escape(f"{value * 100:.0f} %"))
    if kind == "pct1":
        return Markup(escape(f"{value * 100:.1f} %"))
    if kind == "num2":
        return Markup(escape(f"{value:.2f}"))
    if kind == "num3":
        return Markup(escape(f"{value:.3f}"))
    if kind == "int":
        return Markup(escape(f"{int(value):d}"))
    if kind == "p":
        text = "<0.001" if value < 0.001 else f"{value:.3f}"
        cls = "p-sig" if value < 0.05 else "p-ns"
        return Markup(f'<span class="{cls}">{escape(text)}</span>')
    return Markup(escape(str(value)))


def _axis(values: list[float], pad: float = 0.08) -> tuple[float, float]:
    finite = [v for v in values if _num(v)]
    if not finite:
        return -1.0, 1.0
    lo, hi = min(finite), max(finite)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    return lo - span * pad, hi + span * pad


def _tick(v: float, kind: str) -> str:
    if kind in ("pct", "pct0"):
        return f"{v * 100:.1f} %"
    return f"{v:.2f}"


_COLORS = ("var(--brand)", "var(--warn)", "var(--pos)", "var(--text-3)")


def line_svg(block: dict, width: int = 640, height: int = 230) -> Markup:
    xs, series = block["x"], block["series"]
    if len(xs) < 2 or not series:
        return Markup("")
    left, right, top, bottom = 56, 12, 12, 34
    ys = [v for s in series for v in s["y"]] + (block["band"]["lo"] + block["band"]["hi"] if block.get("band") else [])
    lo, hi = _axis(ys)
    kind = block.get("y_kind", "num2")

    def px(i):
        return left + (width - left - right) * i / (len(xs) - 1)

    def py(v):
        return top + (height - top - bottom) * (1 - (v - lo) / (hi - lo))

    parts = [f'<svg class="earn-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(block.get("title", ""))}">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{py(v):.1f}" y2="{py(v):.1f}" stroke="var(--chart-grid)" stroke-width="1"/>'
                     f'<text x="{left - 6}" y="{py(v) + 4:.1f}" text-anchor="end" class="earn-tick">{escape(_tick(v, kind))}</text>')
    if lo < 0 < hi:
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{py(0):.1f}" y2="{py(0):.1f}" stroke="var(--line-strong)" stroke-width="1.2"/>')
    step = max(len(xs) // 8, 1)
    for i in range(0, len(xs), step):
        parts.append(f'<text x="{px(i):.1f}" y="{height - 14}" text-anchor="middle" class="earn-tick">{escape(str(xs[i]))}</text>')
    if block.get("x_label"):
        parts.append(f'<text x="{(left + width - right) / 2:.1f}" y="{height - 2}" text-anchor="middle" class="earn-tick">{escape(block["x_label"])}</text>')
    band = block.get("band")
    if band and len(band["lo"]) == len(xs):
        up = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(band["hi"]))
        down = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in reversed(list(enumerate(band["lo"]))))
        parts.append(f'<polygon points="{up} {down}" fill="var(--brand)" opacity="0.14"/>')
    for n, s in enumerate(series):
        pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(s["y"]) if _num(v))
        dash = ' stroke-dasharray="4 3"' if n > 0 and s["name"] in ("parfaite",) else ""
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{_COLORS[min(n, 3)]}" stroke-width="2"{dash}/>')
    parts.append("</svg>")
    legend = "".join(f'<span class="earn-legend"><i style="background:{_COLORS[min(n, 3)]}"></i>{escape(s["name"])}</span>' for n, s in enumerate(series))
    return Markup("".join(parts) + f'<div class="earn-legend-row">{legend}</div>')


def bars_svg(block: dict, width: int = 640) -> Markup:
    labels, values, kind = block["labels"], block["values"], block.get("kind", "num2")
    pairs = [(label, v) for label, v in zip(labels, values) if _num(v)][:24]
    if not pairs:
        return Markup("")
    lo, hi = _axis([0.0] + [v for _, v in pairs], pad=0.05)
    row_h, label_w = 22, 170
    height = row_h * len(pairs) + 8

    def px(v):
        return label_w + (width - label_w - 70) * (v - lo) / (hi - lo)

    parts = [f'<svg class="earn-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(block.get("title", ""))}">']
    zero = px(0)
    for k, (label, v) in enumerate(pairs):
        y = 4 + k * row_h
        x0, x1 = min(zero, px(v)), max(zero, px(v))
        color = "var(--pos)" if v >= 0 else "var(--neg)"
        parts.append(f'<text x="{label_w - 8}" y="{y + 14}" text-anchor="end" class="earn-tick">{escape(label[:26])}</text>'
                     f'<rect x="{x0:.1f}" y="{y + 3}" width="{max(x1 - x0, 1):.1f}" height="{row_h - 8}" fill="{color}" opacity="0.75"/>'
                     f'<text x="{x1 + 5:.1f}" y="{y + 14}" class="earn-tick">{escape(_tick(v, kind) if kind in ("pct", "pct0") else f"{v:.3f}")}</text>')
    parts.append(f'<line x1="{zero:.1f}" x2="{zero:.1f}" y1="0" y2="{height}" stroke="var(--line-strong)"/></svg>')
    return Markup("".join(parts))


def spark(values: list[float], width: int = 90, height: int = 22) -> Markup:
    """Mini-courbe de quelques réactions successives (signe par couleur)."""
    finite = [v for v in values if _num(v)]
    if len(finite) < 2:
        return _DASH
    lo, hi = _axis(finite, 0.15)
    pts = " ".join(f"{2 + (width - 4) * i / (len(finite) - 1):.1f},{2 + (height - 4) * (1 - (v - lo) / (hi - lo)):.1f}" for i, v in enumerate(finite))
    return Markup(f'<svg class="earn-spark" viewBox="0 0 {width} {height}" aria-hidden="true"><polyline points="{pts}" fill="none" stroke="var(--brand)" stroke-width="1.6"/></svg>')
