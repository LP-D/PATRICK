"""Vocabulaire des événements de résultats (bulles « ? » et page /vocabulary). Même forme que `glossary_text`."""
from __future__ import annotations


def _g(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


GLOSSARY_EARNINGS: dict[str, dict[str, str]] = {
    "earn_event_study": _g(
        "Event study : on mesure de combien un titre s'écarte de ce qu'un modèle attendait autour d'un événement (ici une publication de résultats). "
        "Le rendement anormal (AR) est le rendement réel moins le rendement attendu ; le CAR est la somme des AR sur une fenêtre ; la moyenne des CAR sur "
        "plusieurs événements est le CAAR. J0 est le jour où le cours réagit : le jour même si l'annonce précède l'ouverture, le lendemain si elle suit la clôture.",
        "Event study: we measure how far a stock moves from what a model expected around an event (here an earnings release). The abnormal return (AR) is the "
        "actual return minus the expected one; the CAR is the sum of ARs over a window; the average CAR across events is the CAAR. J0 is the day the price reacts: "
        "the same day if the release precedes the open, the next day if it follows the close."),
    "earn_week_view": _g(
        "Vue semaine : les titres de la newsletter classés par amplitude attendue de leur réaction. L'amplitude est la moyenne historique de |CAR|, ramenée vers "
        "celle du secteur d'autant plus que le titre a peu d'annonces (rétrécissement bayésien empirique). Les drapeaux disent ce qui manque : timing incertain, N insuffisant, "
        "signal analyste indisponible.",
        "Week view: the newsletter's stocks ranked by expected reaction amplitude. Amplitude is the historical mean |CAR|, shrunk toward the sector the more so as the stock has "
        "few announcements (empirical-Bayes shrinkage). Flags say what is missing: uncertain timing, N too small, analyst signal unavailable."),
    "earn_snapshot": _g(
        "Instantané quotidien : Yahoo ne donne le consensus des analystes, les options et les vendeurs à découvert que pour AUJOURD'HUI. On les stocke chaque jour : "
        "après quelques trimestres, ce sont de vraies séries datées, utilisables en backtest sans information future. Avant cela, un signal analyste est un affichage.",
        "Daily snapshot: Yahoo only gives analyst consensus, options and short interest for TODAY. We store them every day: after a few quarters they become real dated series "
        "usable in backtests without future information. Until then an analyst signal is a display."),
    "earn_library": _g(
        "Bibliothèque : chaque étude est une brique activable et paramétrable. Calculée une fois, puis lue depuis le cache (la clé contient les paramètres et la version des "
        "données). Le registre FDR en bas de page corrige l'ensemble des tests essayés : une bibliothèque de plusieurs dizaines d'études produit mécaniquement du bruit « significatif ».",
        "Library: each study is an enableable, parameterised building block. Computed once, then read from the cache (the key contains the parameters and the data version). The FDR "
        "ledger at the bottom corrects all tests tried: a library of dozens of studies mechanically produces \"significant\" noise."),
    "earn_fdr": _g(
        "FDR (taux de fausses découvertes) : parmi les résultats déclarés significatifs, la part attendue de faux positifs. Benjamini-Hochberg ajuste chaque p-value selon son rang "
        "parmi tous les tests essayés (q). Un résultat « significatif » avant correction mais qui ne survit pas est très probablement du bruit.",
        "FDR (false discovery rate): among the results declared significant, the expected share of false positives. Benjamini-Hochberg adjusts each p-value by its rank among all the "
        "tests tried (q). A result \"significant\" before correction that does not survive is very probably noise."),
    "earn_car": _g(
        "CAR : rendement anormal cumulé, somme des rendements du titre moins ceux attendus par le modèle (marché par défaut). Le BHAR compose les rendements au lieu de les sommer. "
        "Test de référence : BMP (Boehmer-Musumeci-Poulsen), robuste à la hausse de variance les jours d'annonce ; Kolari-Pynnönen le corrige en plus de la corrélation entre annonces "
        "d'une même semaine ; le bootstrap par blocs de dates en est le contrôle.",
        "CAR: cumulative abnormal return, the sum of the stock's returns minus those the model expected (market by default). BHAR compounds returns instead of summing them. Reference "
        "test: BMP (Boehmer-Musumeci-Poulsen), robust to the variance increase on announcement days; Kolari-Pynnönen also corrects for correlation between announcements of the same "
        "week; the date-block bootstrap is the control."),
}

LABELS: dict[str, str] = {k: f"gl_t_{k}" for k in GLOSSARY_EARNINGS}
CATEGORY: dict[str, str] = {}

LABEL_STRINGS: dict[str, dict[str, str]] = {
    "gl_t_earn_event_study": _g("Étude d'événement de résultats", "Earnings event study"),
    "gl_t_earn_week_view": _g("Vue semaine", "Week view"),
    "gl_t_earn_snapshot": _g("Instantané quotidien", "Daily snapshot"),
    "gl_t_earn_library": _g("Bibliothèque d'études", "Study library"),
    "gl_t_earn_fdr": _g("Taux de fausses découvertes (FDR)", "False discovery rate (FDR)"),
    "gl_t_earn_car": _g("CAR, CAAR et BHAR", "CAR, CAAR and BHAR"),
}
