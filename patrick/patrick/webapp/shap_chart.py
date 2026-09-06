"""Phase 7 -- server-side SVG for the SHAP waterfall on `/targets/{ticker}`.

Plain string-built SVG (same spirit as `_components.html`'s `sparkline`
macro, just done in Python instead of Jinja since the geometry here is a
genuine cumulative layout, not a single linear scale) -- no charting
library, no client-side rendering: `webapp/static/shap_waterfall.js` only
inserts this markup into the page, it never computes it.
"""
from __future__ import annotations

from html import escape

POSITIVE_COLOR = "var(--color-accent)"
NEGATIVE_COLOR = "var(--color-destructive)"
AXIS_COLOR = "var(--color-border)"
TEXT_COLOR = "var(--color-foreground)"
MUTED_COLOR = "var(--color-muted-foreground)"

MAX_NAME_CHARS = 34


def _truncate(name: str) -> str:
    return name if len(name) <= MAX_NAME_CHARS else name[: MAX_NAME_CHARS - 1] + "…"


def render_waterfall_svg(base_value: float, contributions: list[dict], final_value: float,
                          width: int = 720, row_height: int = 26,
                          label_width: int = 230, value_width: int = 90) -> str:
    """`contributions`: list of `{"name", "value", "shap"}`, already sorted
    (caller's choice of order -- typically |shap| descending). Renders a
    cumulative waterfall: one row for the base value, one per contribution,
    one for the final (predicted) value. `base_value + sum(shap for all
    contributions) == final_value` is assumed (the caller must pass the
    FULL contribution set, not a truncated top-N, or the last bar will not
    land on `final_value`).
    """
    n = len(contributions)
    plot_left = label_width
    plot_width = width - label_width - value_width
    n_rows = n + 2  # base + one per feature + final
    row_pad = 6
    height = n_rows * (row_height + row_pad) + row_pad + 24  # +24: x-axis labels

    # Running cumulative positions, to size the domain and each bar.
    cum = base_value
    cums = [cum]
    for c in contributions:
        cum += c["shap"]
        cums.append(cum)
    all_vals = cums + [base_value, final_value]
    vmin, vmax = min(all_vals), max(all_vals)
    vrange = (vmax - vmin) or 1.0
    pad = vrange * 0.08
    vmin, vmax = vmin - pad, vmax + pad
    vrange = vmax - vmin

    def sx(v: float) -> float:
        return plot_left + (v - vmin) / vrange * plot_width

    zero_x = sx(0.0) if vmin <= 0.0 <= vmax else None

    parts = [
        f'<svg class="shap-waterfall" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Décomposition SHAP de la prédiction, {n} features, '
        f'de la référence {base_value:.3f} au résultat {final_value:.3f}">'
    ]

    if zero_x is not None:
        parts.append(
            f'<line x1="{zero_x:.1f}" y1="0" x2="{zero_x:.1f}" y2="{height - 24:.1f}" '
            f'stroke="{AXIS_COLOR}" stroke-width="1" stroke-dasharray="2,3" />'
        )

    def row(y: float, label: str, sub: str | None, x0: float, x1: float,
            color: str, value_label: str, bold: bool = False) -> str:
        bar_y = y + 2
        bar_h = row_height - 4
        x_left, x_right = (x0, x1) if x0 <= x1 else (x1, x0)
        weight = "600" if bold else "400"
        label_html = (
            f'<text x="{label_width - 10:.1f}" y="{y + row_height / 2:.1f}" '
            f'text-anchor="end" dominant-baseline="middle" font-size="12" '
            f'font-weight="{weight}" fill="{TEXT_COLOR}">{escape(label)}</text>'
        )
        sub_html = ""
        if sub:
            sub_html = (
                f'<text x="{label_width - 10:.1f}" y="{y + row_height / 2 + 12:.1f}" '
                f'text-anchor="end" font-size="10" fill="{MUTED_COLOR}">{escape(sub)}</text>'
            )
        bar_html = (
            f'<rect x="{x_left:.1f}" y="{bar_y:.1f}" width="{max(x_right - x_left, 1.5):.1f}" '
            f'height="{bar_h}" fill="{color}" rx="2" />'
        )
        value_html = (
            f'<text x="{plot_left + plot_width + 10:.1f}" y="{y + row_height / 2:.1f}" '
            f'text-anchor="start" dominant-baseline="middle" font-size="12" '
            f'font-weight="{weight}" fill="{TEXT_COLOR}" class="pk-mono">{escape(value_label)}</text>'
        )
        return label_html + sub_html + bar_html + value_html

    y = row_pad
    parts.append(row(y, "Référence (base)", "moyenne du modèle pour cette classe",
                      sx(vmin), sx(base_value), MUTED_COLOR, f"{base_value:+.3f}"))
    for i, c in enumerate(contributions):
        y += row_height + row_pad
        color = POSITIVE_COLOR if c["shap"] >= 0 else NEGATIVE_COLOR
        sub = f"valeur observée : {c['value']:.4g}"
        parts.append(row(y, _truncate(c["name"]), sub, sx(cums[i]), sx(cums[i + 1]),
                          color, f"{c['shap']:+.3f}"))
    y += row_height + row_pad
    parts.append(row(y, "Prédiction (score brut)", None, sx(vmin), sx(final_value),
                      TEXT_COLOR, f"{final_value:+.3f}", bold=True))

    axis_y = height - 16
    parts.append(
        f'<line x1="{plot_left}" y1="{y + row_height + row_pad:.1f}" '
        f'x2="{plot_left + plot_width}" y2="{y + row_height + row_pad:.1f}" '
        f'stroke="{AXIS_COLOR}" stroke-width="1" />'
    )
    parts.append(
        f'<text x="{plot_left}" y="{axis_y:.1f}" font-size="10" fill="{MUTED_COLOR}">{vmin + pad:.2f}</text>'
    )
    parts.append(
        f'<text x="{plot_left + plot_width}" y="{axis_y:.1f}" text-anchor="end" '
        f'font-size="10" fill="{MUTED_COLOR}">{vmax - pad:.2f}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)
