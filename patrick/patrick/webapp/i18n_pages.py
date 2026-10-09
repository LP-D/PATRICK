"""Chaînes FR/EN des pages ajoutées à la refonte du 2026-10-09 : qualité des données, vocabulaire, classes d'actifs,
analyse des séries et des modèles, métriques, aide statistique. Fusionnées dans `i18n.STRINGS` ; `PAGES_JS_KEYS`
complète `i18n.js_strings`."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


PAGES_STRINGS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ navigation
    "nav_data_quality": _s("Qualité des données", "Data quality"),
    "nav_vocabulary": _s("Vocabulaire", "Vocabulary"),
    "nav_analysis": _s("Séries & modèles", "Series & models"),
    "nav_cat_models": _s("MODÈLES", "MODELS"),
    "nav_equity": _s("Equity", "Equity"),
    "nav_indices": _s("Indices", "Indices"),
    "nav_crypto": _s("Cryptos", "Cryptos"),
    "nav_fx": _s("Devises", "FX"),
    "nav_rates": _s("Taux & crédit", "Rates & credit"),
    "nav_etfs": _s("ETF", "ETFs"),

    # ------------------------------------------------------------------ qualité des données
    "dq_title": _s("Qualité des données", "Data quality"),
    "dq_subtitle": _s(
        "Ce que les entraînements ont réellement vécu côté données : échecs et leur cause, séries écartées à "
        "l'ingestion, historique disponible, résultats trop beaux pour être vrais. Aucune performance de modèle ici.",
        "What training runs really went through on the data side: failures and their cause, series dropped at "
        "ingestion, available history, results too good to be true. No model performance here."),
    "dq_threshold_label": _s("Historique minimum (années)", "Minimum history (years)"),
    "dq_threshold_apply": _s("Appliquer", "Apply"),
    "dq_kpi_runs": _s("Runs terminés", "Finished runs"),
    "dq_kpi_runs_rel": _s("{failed} en échec sur {total} runs en base", "{failed} failed out of {total} runs in the database"),
    "dq_kpi_failures": _s("Causes d'échec distinctes", "Distinct failure causes"),
    "dq_kpi_failures_rel": _s("{n} entraînement(s) concerné(s)", "{n} run(s) affected"),
    "dq_kpi_series": _s("Séries écartées", "Series dropped"),
    "dq_kpi_series_rel": _s("(série, motif) distincts, tous snapshots confondus", "distinct (series, reason), all snapshots"),
    "dq_kpi_history": _s("Historique insuffisant", "Insufficient history"),
    "dq_kpi_history_rel": _s("cibles sous le seuil de {y} ans, sur {total} listées", "targets under the {y}-year threshold, out of {total} listed"),
    "dq_kpi_suspect": _s("Résultats suspects", "Suspect results"),
    "dq_kpi_suspect_rel": _s("runs avec un score au-delà du plausible", "runs with a score beyond plausible"),
    "dq_failures_title": _s("Pourquoi des entraînements ont échoué", "Why training runs failed"),
    "dq_failures_empty": _s("Aucun échec enregistré.", "No failure recorded."),
    "dq_failures_n": _s("{n} fois", "{n} time(s)"),
    "dq_failures_targets": _s("Cibles : {targets}", "Targets: {targets}"),
    "dq_failures_last": _s("dernier : {at}", "last: {at}"),
    "dq_failures_fix": _s("État", "Status"),
    "dq_issues_title": _s("Séries écartées ou décalées à l'ingestion", "Series dropped or shifted at ingestion"),
    "dq_issues_intro": _s(
        "Chaque motif est un contrôle de qualité qui retire une série du pool de features d'un run. Une série retirée "
        "n'est pas perdue : elle reste une cible possible.",
        "Each reason is a quality gate that removes a series from a run's feature pool. A dropped series is not lost: "
        "it stays a possible target."),
    "dq_col_series": _s("Série", "Series"),
    "dq_col_detail": _s("Détail", "Detail"),
    "dq_col_seen": _s("Vue dans", "Seen in"),
    "dq_col_last": _s("Dernière fois", "Last seen"),
    "dq_snapshots": _s("{n} snapshot(s)", "{n} snapshot(s)"),
    "dq_effect": _s("Effet", "Effect"),
    "dq_excluded_title": _s("Symboles exclus définitivement", "Symbols excluded for good"),
    "dq_excluded_hint": _s("Cotations introuvables chez Yahoo : jamais retentés.", "Not served by Yahoo: never retried."),
    "dq_history_title": _s("Historique disponible par cible", "Available history per target"),
    "dq_history_intro": _s(
        "Comparé au seuil ci-dessus. La profondeur vient des données déjà ingérées ; à défaut, de la première cotation "
        "vérifiée. Une cible sous le seuil est grisée dans la page Lancer.",
        "Compared to the threshold above. Depth comes from already-ingested data; otherwise from the verified first "
        "listing. A target under the threshold is greyed out in the Launch page."),
    "dq_status_ok": _s("Suffisant", "Sufficient"),
    "dq_status_short": _s("Insuffisant", "Insufficient"),
    "dq_status_unknown": _s("Non vérifié", "Not verified"),
    "dq_col_target": _s("Cible", "Target"),
    "dq_col_first": _s("Début", "Start"),
    "dq_col_years": _s("Années", "Years"),
    "dq_col_obs": _s("Observations", "Observations"),
    "dq_col_status": _s("État", "Status"),
    "dq_col_source": _s("Source", "Source"),
    "dq_source_store": _s("données ingérées", "ingested data"),
    "dq_source_declared": _s("1re cotation vérifiée", "verified first listing"),
    "dq_history_only_short": _s("Seulement les cibles insuffisantes", "Only insufficient targets"),
    "dq_suspect_title": _s("Résultats suspects : fuite de données probable", "Suspect results: probable data leak"),
    "dq_suspect_intro": _s(
        "Un F1 directionnel ou une AUC aussi hauts ne se voient sur aucun marché liquide. Cause identifiée : la fenêtre du "
        "label recouvrait des données déjà observées (voir la ligne « Décalage anti-fuite »). Corrigé pour les nouveaux "
        "runs ; ces modèles ne sont plus éligibles au titre de champion.",
        "A directional F1 or AUC this high is not seen on any liquid market. Identified cause: the label window "
        "overlapped data already observed (see the 'Anti-leak shift' reason). Fixed for new runs; these models are "
        "no longer eligible to be champion."),
    "dq_suspect_empty": _s("Aucun résultat suspect.", "No suspect result."),
    "dq_col_run": _s("Run", "Run"),
    "dq_col_horizon": _s("Horizon", "Horizon"),
    "dq_col_cause": _s("Cause", "Cause"),
    "dq_generated": _s("Calculé le {at}", "Computed on {at}"),
    "dq_none": _s("Aucun.", "None."),

    # ------------------------------------------------------------------ lancement : cibles grisées
    "field_min_history_years": _s("Historique minimum (années)", "Minimum history (years)"),
    "min_history_hint": _s(
        "Les cibles dont les données remontent moins loin sont grisées dans la liste. Défaut : {n} ans.",
        "Targets whose data goes back less far are greyed out in the list. Default: {n} years."),
    "target_short_history": _s("historique insuffisant : depuis {first}, {years} ans requis",
                               "insufficient history: since {first}, {years} years required"),
    "target_greyed_count": _s("{n} cible(s) grisée(s) : historique inférieur à {years} ans",
                              "{n} target(s) greyed out: history under {years} years"),
}

PAGES_JS_KEYS: list[str] = ["target_short_history", "target_greyed_count"]
