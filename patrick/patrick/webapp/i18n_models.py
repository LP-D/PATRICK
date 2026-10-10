"""Chaînes FR/EN des pages Modèles (ML, DL, RL) et de la page Exploration. Fusionnées dans `i18n.STRINGS` ;
`MODELS_JS_KEYS` complète `i18n.js_strings` (clés lues côté navigateur via `window.I18N`).

Convention : un texte explicatif est écrit une seule fois ici et affiché derrière un « ? » (`static/help.js`) ; seuls les titres,
libellés, valeurs et boutons restent visibles à l'écran."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


MODELS_STRINGS: dict[str, dict[str, str]] = {
    # --- navigation
    "nav_cat_models": _s("MODÈLES", "MODELS"),
    "nav_ml": _s("Machine learning", "Machine learning"),
    "nav_dl": _s("Deep learning", "Deep learning"),
    "nav_rl": _s("Reinforcement learning", "Reinforcement learning"),
    "nav_exploration": _s("Exploration", "Exploration"),

    # --- page ML
    "ml_title": _s("Machine learning", "Machine learning"),
    "ml_subtitle": _s(
        "Arbres, forêts et boosting : cadre un run, lance-le, suis-le. Les blocs repliés portent des valeurs par défaut issues de "
        "résultats mesurés ; chaque brique de rigueur affiche son état, ON comme OFF, sans qu'il faille l'ouvrir.",
        "Trees, forests and boosting: frame a run, launch it, follow it. Collapsed blocks carry defaults derived from measured "
        "results; every rigor gate shows its state, ON or OFF, without opening it."),
}

MODELS_JS_KEYS: tuple[str, ...] = ()
