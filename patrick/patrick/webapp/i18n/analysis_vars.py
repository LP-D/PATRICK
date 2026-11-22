"""Chaînes FR/EN de la page Variables (`/variables`, `static/variables.js`). Fusionnées dans `ANALYSIS_STRINGS`."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


VARS_STRINGS: dict[str, dict[str, str]] = {
    "nav_variables": _s("Variables", "Features"),
    "av_title": _s("Explorateur de variables", "Feature explorer"),
    "av_subtitle": _s("Quelles variables les sélecteurs retiennent, pour quelles cibles, et avec quelle stabilité d'un pli à l'autre, sur tous les runs terminés.", "Which features the selectors keep, for which targets, and how stable they are from fold to fold, over every finished run."),
    "av_s_fam": _s("Familles de variables", "Feature families"),
    "av_h_fam": _s("Part du poids de sélection de chaque famille (nombre de runs × fréquence de sélection).", "Share of each family's selection weight (number of runs × selection frequency)."),
    "av_s_series": _s("Séries d'entrée les plus utilisées", "Most used input series"),
    "av_h_series": _s("La série dont une variable est dérivée (avant z-score, rendement, retard...) : le poids additionne les fréquences de sélection.", "The series a feature is derived from (before z-score, return, lag...): the weight sums selection frequencies."),
    "av_s_matrix": _s("Cibles × familles", "Targets × families"),
    "av_h_matrix": _s("Sur quoi s'appuie chaque cible : part de chaque famille dans ses variables retenues (30 cibles les plus riches en sélections).", "What each target relies on: share of each family in its selected features (the 30 targets with the most selections)."),
    "av_s_list": _s("Toutes les variables", "Every feature"),
    "av_h_list": _s("Cliquer sur une variable pour voir les runs qui l'ont retenue.", "Click a feature to see the runs that kept it."),
    "av_k_feat": _s("Variables distinctes", "Distinct features"),
    "av_k_feat_sub": _s("retenues dans {r} runs sur {t} terminés", "kept in {r} runs out of {t} finished"),
    "av_k_jac": _s("Stabilité moyenne (Jaccard)", "Mean stability (Jaccard)"),
    "av_k_jac_sub": _s("médiane {m} · {n} runs mesurés", "median {m} · {n} runs measured"),
    "av_k_low": _s("Runs à sélection instable", "Runs with unstable selection"),
    "av_k_low_sub": _s("Jaccard sous 0,5 : les variables retenues changent beaucoup d'un pli à l'autre", "Jaccard under 0.5: the kept features change a lot from fold to fold"),
    "av_k_top": _s("Variable la plus retenue", "Most kept feature"),
    "av_k_top_sub": _s("dans {r} runs sur {t} cibles", "in {r} runs over {t} targets"),
    "av_c_feature": _s("Variable", "Feature"),
    "av_c_family": _s("Famille", "Family"),
    "av_c_series": _s("Série d'entrée", "Input series"),
    "av_c_runs": _s("Runs", "Runs"),
    "av_c_targets": _s("Cibles", "Targets"),
    "av_c_freq": _s("Fréquence moyenne", "Mean frequency"),
    "av_c_always": _s("Toujours retenue", "Always kept"),
    "av_c_nfeat": _s("Variables", "Features"),
    "av_c_weight": _s("Poids", "Weight"),
    "av_m_corner": _s("cible · famille", "target · family"),
    "av_m_hint": _s("Cliquer sur une cible ouvre sa page. Une ligne dominée par une seule famille dit que le modèle de cette cible repose sur un seul type d'information.", "Clicking a target opens its page. A row dominated by one family says the target's model relies on a single kind of information."),
    "av_filter_q": _s("Rechercher une variable ou une série", "Search a feature or a series"),
    "av_rows": _s("{n} variables affichées sur {total}.", "{n} features shown out of {total}."),
    "av_d_runs": _s("retenue dans {n} runs sur {t} cibles", "kept in {n} runs over {t} targets"),
}
