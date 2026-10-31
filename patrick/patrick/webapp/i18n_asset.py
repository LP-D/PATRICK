"""Chaînes FR/EN de la fiche d'un actif (`/targets/{symbole}`) et des signaux des pages de classes d'actifs. Fusionnées dans `i18n.STRINGS`."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


ASSET_STRINGS: dict[str, dict[str, str]] = {
    # --- en-tête de la fiche
    "as_source_yfinance": _s("Yahoo Finance", "Yahoo Finance"),
    "as_source_fred": _s("FRED", "FRED"),
    "as_history": _s("historique depuis le {d} ({y} ans)", "history since {d} ({y} years)"),
    "as_launch_ml": _s("Lancer en machine learning", "Launch as machine learning"),
    "as_launch_dl": _s("Deep learning", "Deep learning"),
    "as_launch_rl": _s("Reinforcement learning", "Reinforcement learning"),
    "as_news_all": _s("Toutes les actualités", "All the news"),
    # --- sections
    "as_market_h": _s("Marché", "Market"),
    "as_signals_h": _s("Signaux par horizon", "Signals by horizon"),
    "as_news_h": _s("Actualités", "News"),
    "as_funds_h": _s("Dans les fonds", "In the funds"),
    "as_runs_h": _s("Entraînements", "Training runs"),
    "as_peers_h": _s("Dans le même groupe", "In the same group"),
    # --- signaux
    "as_col_signal": _s("Signal", "Signal"),
    "as_col_champion": _s("Champion", "Champion"),
    "as_col_live": _s("Réussite en direct", "Live hit rate"),
    "as_col_dm": _s("Test DM (p)", "DM test (p)"),
    "as_champ_line": _s("{algo} · {n} variables", "{algo} · {n} features"),
    "as_no_signal": _s("Aucun signal : cet actif n'a pas encore de modèle entraîné.", "No signal: this asset has no trained model yet."),
    "as_no_signal_hint": _s("Un run rapide suffit à obtenir un premier signal par horizon.", "A quick run is enough to get a first signal per horizon."),
    "as_signals_foot": _s("Un signal par horizon, issu du champion si l'horizon en a un. Survole une case pour le détail (confiance, test DM, fiabilité en direct, dérive).",
                          "One signal per horizon, from the champion when the horizon has one. Hover a cell for the detail (confidence, DM test, live reliability, drift)."),
    # --- contexte de marché d'une action
    "as_ctx_home": _s("Indice de sa place :", "Home-market index:"),
    "as_ctx_no_home": _s("Pas d'indice utilisable pour sa place de cotation.", "No usable index for its listing venue."),
    "as_ctx_world": _s("Référence mondiale :", "Global reference:"),
    "as_ctx_euro": _s("Composite zone euro :", "Euro-area composite:"),
    "as_ctx_foot": _s("Les features de contexte de cette action (rendement relatif, bêta, corrélation, volatilité propre, force relative) se calculent contre ces références.",
                      "This stock's context features (relative return, beta, correlation, idiosyncratic volatility, relative strength) are computed against these references."),
    # --- fonds
    "as_funds_line": _s("{n} ordre(s), le dernier le {d}", "{n} order(s), the last on {d}"),
    "as_funds_none": _s("Aucune stratégie du fonds n'a encore passé d'ordre sur cet actif.", "No fund strategy has placed an order on this asset yet."),
    # --- pages de classes d'actifs
    "cls_col_signals": _s("Signaux", "Signals"),
    "cls_signals_hint": _s("Un repère par horizon (1 à 10 jours) : ▲ hausse, ▼ baisse, doublé si le mouvement est fort. Survole pour le détail.",
                           "One marker per horizon (1 to 10 days): ▲ up, ▼ down, doubled for a strong move. Hover for the detail."),
}

# Clés lues par le navigateur (`window.I18N`) : aucune pour l'instant, les libellés des signaux sont posés par le serveur.
ASSET_JS_KEYS: tuple[str, ...] = ()
