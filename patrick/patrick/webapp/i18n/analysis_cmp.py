"""Chaînes FR/EN du comparateur de runs (`/analyses/comparer`, `static/analyses_compare.js`). Fusionnées dans `ANALYSIS_STRINGS`."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


CMP_ANALYSIS_STRINGS: dict[str, dict[str, str]] = {
    "ac_title": _s("Comparaison détaillée de runs", "Detailed run comparison"),
    "ac_crumb": _s("Comparer", "Compare"),
    "ac_subtitle": _s("Chiffres de tête, courbes superposées, plis, tests de Diebold-Mariano et différences de configuration, pour 2 à 4 runs ML ou DL.", "Headline numbers, overlaid curves, folds, Diebold-Mariano tests and configuration differences, for 2 to 4 ML or DL runs."),
    "ac_s_head": _s("Chiffres de tête", "Headline numbers"),
    "ac_s_curves": _s("Courbes superposées", "Overlaid curves"),
    "ac_s_folds": _s("Exactitude par pli", "Accuracy by fold"),
    "ac_s_dm": _s("Matrice de Diebold-Mariano", "Diebold-Mariano matrix"),
    "ac_h_dm": _s("Chaque case compare deux runs sur leurs dates communes (perte 0/1 de la direction), p corrigée par Holm sur toutes les paires.", "Each cell compares two runs on their common dates (0/1 direction loss), p corrected by Holm over all pairs."),
    "ac_s_diff": _s("Différences de configuration", "Configuration differences"),
    "ac_h_diff": _s("Seuls les réglages qui diffèrent entre les runs sont listés.", "Only the settings that differ between the runs are listed."),
    "ac_mixed": _s("Les runs n'ont pas la même cible et le même horizon : les tests de Diebold-Mariano ne sont pas calculés et achat-garde n'est pas tracé.", "The runs do not share the same target and horizon: Diebold-Mariano tests are not computed and buy-and-hold is not drawn."),
    "ac_head_hint": _s("Vert : meilleure valeur de la ligne. Équité simulée long/court à {c} points de base par aller.", "Green: best value of the row. Simulated long/short equity at {c} basis points per turn."),
    "ac_eq_total": _s("Rendement simulé long/court", "Simulated long/short return"),
    "ac_eq_sharpe": _s("Sharpe simulé", "Simulated Sharpe"),
    "ac_eq_dd": _s("Pire baisse simulée", "Simulated max drawdown"),
    "ac_eq": _s("Équité simulée long/court", "Simulated long/short equity"),
    "ac_eq_hint": _s("Le signal de chaque run appliqué aux rendements réalisés (départ à 1). Un écart entre deux runs de cibles différentes ne se compare pas.", "Each run's signal applied to realised returns (start at 1). A gap between runs on different targets is not comparable."),
    "ac_rel": _s("Fiabilité de P(hausse)", "P(up) reliability"),
    "ac_folds_hint": _s("Vert : le pli bat le côté majoritaire de sa propre période ; rouge : non.", "Green: the fold beats its own period's majority side; red: not."),
    "ac_dm_corner": _s("ligne contre colonne", "row against column"),
    "ac_dm_cell": _s("p brute {p} · p Holm {pa} · {n} dates communes · perte {a} contre {b}", "raw p {p} · Holm p {pa} · {n} common dates · loss {a} vs {b}"),
    "ac_dm_legend": _s("▲ : la ligne a la perte la plus basse, ▼ : la colonne ; le chiffre est la p-value corrigée ({m} paires testées). n/a : non testable.", "▲: the row has the lowest loss, ▼: the column; the figure is the corrected p-value ({m} pairs tested). n/a: not testable."),
    "ac_dm_reason_different_target_or_horizon": _s("Cibles ou horizons différents", "Different targets or horizons"),
    "ac_dm_reason_few_common_dates": _s("Moins de 30 dates communes", "Fewer than 30 common dates"),
    "ac_dm_reason_horizon_too_long": _s("Horizon trop long pour le nombre de dates", "Horizon too long for the number of dates"),
    "ac_dm_reason_too_few_observations": _s("Trop peu d'observations", "Too few observations"),
    "ac_dm_reason_undefined_variance": _s("Variance indéfinie", "Undefined variance"),
    "ac_dm_reason_unknown": _s("Non testable", "Not testable"),
    "ac_diff_none": _s("Les configurations sont identiques.", "The configurations are identical."),
    "ac_diff_key": _s("Réglage", "Setting"),
    "ac_diff_count": _s("{n} réglage(s) diffèrent.", "{n} setting(s) differ."),
    "ac_compare": _s("Comparer en détail", "Compare in detail"),
    "ac_compare_selected": _s("Comparer la sélection ({n})", "Compare selection ({n})"),
    "ac_pick_hint": _s("Cocher 2 à 4 runs ML ou DL pour les comparer en détail.", "Tick 2 to 4 ML or DL runs to compare them in detail."),
    "ac_c_pick": _s("Choix", "Pick"),
}
