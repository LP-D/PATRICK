"""Chaînes FR/EN du moteur de graphiques commun (`static/chart_kit.js`) et des messages JS qui n'avaient pas de clé. Fusionnées dans
`i18n.STRINGS` ; `CHART_JS_KEYS` complète `i18n.js_strings` (lues par les scripts via `window.I18N`, sur toutes les pages)."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


CHART_STRINGS: dict[str, dict[str, str]] = {
    "chart_zoom_in": _s("Zoom avant", "Zoom in"),
    "chart_zoom_out": _s("Zoom arrière", "Zoom out"),
    "chart_reset": _s("Vue initiale", "Reset zoom"),
    "chart_hint": _s("Glisser pour zoomer · double-clic : vue initiale", "Drag to zoom · double-click to reset"),
    "chart_empty": _s("Aucune donnée à tracer.", "No data to plot."),
    "chart_aria": _s(
        "{title} : {n} points du {from} au {to}, de {min} à {max}. Glisser pour zoomer, double-clic pour revenir à la vue initiale.",
        "{title}: {n} points from {from} to {to}, from {min} to {max}. Drag to zoom, double-click to reset."),
    "chart_toggle_series": _s("Afficher ou masquer cette série", "Show or hide this series"),
    "chart_range_1m": _s("1M", "1M"),
    "chart_range_3m": _s("3M", "3M"),
    "chart_range_6m": _s("6M", "6M"),
    "chart_range_1y": _s("1A", "1Y"),
    "chart_range_5y": _s("5A", "5Y"),
    "chart_range_all": _s("Tout", "All"),
    "chart_range_max": _s("Max", "Max"),
}

CHART_JS_KEYS: tuple[str, ...] = tuple(CHART_STRINGS)
