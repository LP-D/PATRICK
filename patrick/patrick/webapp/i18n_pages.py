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

    # ------------------------------------------------------------------ métriques d'un modèle
    "m_split_test": _s("Test walk-forward", "Walk-forward test"),
    "m_split_test_path": _s("Test (chemins CPCV)", "Test (CPCV paths)"),
    "m_split_holdout": _s("Holdout terminal", "Terminal holdout"),
    "m_split_valid": _s("Validation interne", "Inner validation"),
    "m_fold": _s("Fold", "Fold"),
    "m_folds_word": _s("fold(s)", "fold(s)"),
    "m_mean": _s("Moyenne", "Mean"),
    "rows_more": _s("{n} de plus", "{n} more"),
    "rows_less": _s("Replier", "Collapse"),
    "m_test": _s("test", "test"),
    "m_holdout": _s("holdout", "holdout"),
    "suspect_banner_title": _s("Résultat suspect.", "Suspect result."),
    "suspect_banner_body": _s(
        "Ce score ({reason}) est impossible sur un marché liquide : le modèle a vu une information du futur. "
        "À ne pas utiliser ; le correctif est appliqué aux nouveaux runs.",
        "This score ({reason}) is impossible on a liquid market: the model saw information from the future. "
        "Do not use it; the fix applies to new runs."),
    "suspect_banner_link": _s("Voir la cause", "See the cause"),
    # ------------------------------------------------------------------ historique : directionnel / alpha
    "hist_subtitle": _s("Runs persistés en base : AUC puis F1 d'abord. Filtre-les, compare jusqu'à quatre runs ou duplique leur configuration depuis le détail.",
                        "Runs persisted in the database: AUC then F1 first. Filter them, compare up to four runs or duplicate their configuration from the detail page."),
    "hist_search": _s("Recherche", "Search"),
    "hist_search_ph": _s("Nom, cible ou ID", "Name, target or ID"),
    "hist_compare": _s("Comparer", "Compare"),
    "hist_gap": _s("Écart", "Gap"),
    "hist_started": _s("Démarré", "Started"),
    "kind_tabs_label": _s("Famille de modèles", "Model family"),
    "kind_all": _s("Tous", "All"),
    "kind_directional": _s("Directionnels", "Directional"),
    "kind_alpha": _s("Alpha", "Alpha"),
    "kind_col": _s("Type", "Type"),
    "kind_directional_hint": _s(
        "Modèles directionnels : ils prédisent le sens et l'intensité du mouvement du prix de l'actif (4 mouvements : baisse forte, baisse faible, hausse faible, hausse forte).",
        "Directional models: they predict the direction and intensity of the asset's price move (4 moves: strong down, weak down, weak up, strong up)."),
    "kind_alpha_hint": _s(
        "Modèles alpha : ils prédisent si l'actif fera mieux ou moins bien que son benchmark (rendement de l'actif moins β × rendement du benchmark), pas la direction de son prix.",
        "Alpha models: they predict whether the asset will beat or lag its benchmark (asset return minus β × benchmark return), not the direction of its price."),
    "suspect_tag": _s("suspect", "suspect"),
    "rp_remove": _s("Retirer ce run du panneau", "Remove this run from the panel"),
    "rp_scheme": _s("Schéma", "Scheme"),
    "rp_persistence": _s("Persistance (F1)", "Persistence (F1)"),
    "rp_dm": _s("DM p-value", "DM p-value"),
    "rp_dm_biased": _s("calculé sur le fold de sélection : biaisé, exclu de la correction entre cibles",
                       "computed on the selection fold: biased, excluded from the across-target correction"),
    "rp_dm_biased_tag": _s("fold de sélection", "selection fold"),
    "rp_trials": _s("Essais", "Trials"),
    "rp_duration": _s("Durée", "Duration"),
    "rp_horizons": _s("Horizons", "Horizons"),
    "rp_algos": _s("Algorithmes", "Algorithms"),
    "rp_samplers": _s("Rééchantillonnage", "Resampling"),
    "rp_full_detail": _s("Détail complet", "Full detail"),
    # ------------------------------------------------------------------ prédictions : direction ou intensité
    "pred_track_title": _s("Réussites par mouvement prédit", "Hits by predicted move"),
    "pred_since": _s("depuis le {d}", "since {d}"),
    "pred_col_move": _s("Mouvement prédit", "Predicted move"),
    "pred_col_n": _s("Jugés", "Judged"),
    "pred_col_exact": _s("Exact", "Exact"),
    "pred_col_intensity": _s("Intensité", "Intensity"),
    "pred_col_wrongway": _s("Sens", "Direction"),
    "pred_intensity_help": _s("Bon sens, mauvaise intensité : hausse forte prédite, hausse faible réalisée.",
                              "Right direction, wrong intensity: strong up predicted, weak up happened."),
    "pred_wrongway_help": _s("Mauvais sens : hausse prédite, baisse réalisée (ou l'inverse).",
                             "Wrong direction: up predicted, down happened (or the reverse)."),
    "pred_dir_title": _s("Direction seule (hausse / baisse)", "Direction only (up / down)"),
    "pred_col_right": _s("Juste", "Right"),
    "pred_col_wrong": _s("Faux", "Wrong"),
    "pred_dir_total": _s("Bon sens au total : {hits}/{n}", "Right direction overall: {hits}/{n}"),
    "pred_pending": _s("{n} signal(aux) en attente du résultat", "{n} signal(s) waiting for the outcome"),
    "pred_reading_help": _s(
        "Exact + Intensité + Sens = signaux jugés. Une erreur d'intensité garde le bon sens ; une erreur de sens est la plus coûteuse.",
        "Exact + Intensity + Direction = judged signals. An intensity error keeps the right direction; a direction error is the costliest."),
    "pred_no_track": _s("Pas encore de signal suivi : le suivi démarre au premier lancement de l'app après l'entraînement.",
                        "No tracked signal yet: tracking starts the first time the app is launched after training."),
    # ------------------------------------------------------------------ vocabulaire
    "vocab_title": _s("Vocabulaire", "Vocabulary"),
    "vocab_subtitle": _s(
        "Tous les termes utilisés dans PATRICK, expliqués : cibles, métriques, p-values, validation, données, classes d'actifs. "
        "Les mêmes définitions que les bulles « ? » des pages.",
        "Every term used in PATRICK, explained: targets, metrics, p-values, validation, data, asset classes. The same "
        "definitions as the \"?\" bubbles across the pages."),
    "vocab_search": _s("Chercher un terme (auc, p-value, alpha, fuite…)", "Search a term (auc, p-value, alpha, leak…)"),
    "vocab_count": _s("{n} terme(s) affiché(s) sur {total}", "{n} term(s) shown out of {total}"),
    "vocab_none": _s("Aucun terme ne correspond.", "No matching term."),
    "vocab_permalink": _s("Lien vers ce terme", "Link to this term"),
    "vocab_open_page": _s("Voir tout le vocabulaire", "See the whole vocabulary"),
    # ------------------------------------------------------------------ bandeau « comprendre les p-values »
    "sb_label": _s("Comprendre les p-values et les résultats statistiques", "Understand p-values and statistical results"),
    "sb_hint": _s("Procédure appliquée au run affiché", "Procedure applied to the displayed run"),
    "sb_close": _s("Fermer", "Close"),
    "sb_loading": _s("Chargement…", "Loading…"),
    "sb_error": _s("Explication indisponible.", "Explanation unavailable."),
    "sb_ref": _s("Run de référence", "Reference run"),
    "sb_pick": _s("Choisir un autre run", "Pick another run"),
    "sb_none": _s("Aucun run de référence : explication générale. Sélectionne un run (Historique, ou sa page de détail) pour voir sa procédure.",
                  "No reference run: general explanation. Select a run (History, or its detail page) to see its procedure."),
    "sb_thresholds": _s("Seuils : p < {dm} pour le test brut, {fdr} pour la correction FDR (réglables : ?dm_alpha= et ?fdr_alpha= dans l'adresse).",
                        "Thresholds: p < {dm} for the raw test, {fdr} for the FDR correction (adjustable: ?dm_alpha= and ?fdr_alpha= in the URL)."),
    "sb_pvalues": _s("Les p-values et résultats de ce run", "This run's p-values and results"),
    "sb_procedure": _s("Procédure appliquée", "Procedure applied"),
    "sb_rule": _s("Règle d'or : une p-value basse dit « le hasard explique mal ce résultat », jamais « le modèle est bon ». Elle ne vaut que si le nombre d'essais est pris en compte.",
                  "Rule of thumb: a low p-value says \"chance explains this result poorly\", never \"the model is good\". It only counts if the number of trials is accounted for."),
    "sh_title_dm": _s("p-value de Diebold-Mariano (brute)", "Diebold-Mariano p-value (raw)"),
    "sh_title_bh": _s("p-value ajustée (Benjamini-Hochberg)", "Adjusted p-value (Benjamini-Hochberg)"),
    "sh_title_spearman": _s("Corrélation test / holdout (Spearman)", "Test / holdout correlation (Spearman)"),
    "sh_title_pbo": _s("PBO : probabilité de surajustement", "PBO: probability of backtest overfitting"),
    "sh_title_trials": _s("Essais cumulés", "Cumulative trials"),
    "sh_what_dm": _s("Le modèle se trompe-t-il moins que la meilleure baseline (persistance, tendance…), au-delà du hasard ? Test unilatéral, sur le holdout terminal.",
                     "Does the model err less than the best baseline (persistence, trend…), beyond chance? One-sided test, on the terminal holdout."),
    "sh_what_bh": _s("La p-value brute, corrigée du nombre de cibles testées en même temps : plus on teste, plus une p-value basse arrive par chance.",
                     "The raw p-value, corrected for the number of targets tested at once: the more we test, the more a low p-value happens by chance."),
    "sh_what_spearman": _s("Les configurations qui gagnent sur les folds de test gagnent-elles aussi sur le holdout ? ρ proche de 1 : la sélection se généralise ; proche de 0 : c'est du bruit.",
                           "Do the configurations that win on the test folds also win on the holdout? ρ near 1: selection generalises; near 0: it is noise."),
    "sh_what_pbo": _s("Probabilité que la meilleure configuration d'un backtest soit moins bonne que la médiane hors échantillon. Au-dessus de 0,5 : surajustement probable.",
                      "Probability that a backtest's best configuration ranks below the median out of sample. Above 0.5: overfitting likely."),
    "sh_what_trials": _s("Toutes les configurations déjà essayées sur cette cible et cet horizon. Plus il y en a, plus le meilleur score est surestimé.",
                         "Every configuration already tried on this target and horizon. The more there are, the more the best score is overestimated."),
    "sh_dm_cpcv": _s("Sans objet en CPCV : le test suppose le découpage « entraînement = préfixe » du walk-forward.",
                     "Not applicable in CPCV: the test assumes walk-forward's \"train = prefix\" layout."),
    "sh_dm_missing": _s("Non calculé pour ce run (aucun essai gagnant n'a produit ce résultat).", "Not computed for this run (no winning trial produced it)."),
    "sh_dm_biased": _s("p = {p}, calculée sur le fold de sélection (celui qui a servi à choisir le modèle) : biaisée vers le significatif, exclue de la correction. Relancer le run pour le test sur le holdout.",
                       "p = {p}, computed on the selection fold (the one used to choose the model): biased toward significance, excluded from the correction. Re-run for the holdout test."),
    "sh_dm_significant": _s("p = {p} < {alpha} : le hasard explique mal que le modèle batte {baseline} (holdout, {n} observations). Brute : à lire avec l'ajustée.",
                            "p = {p} < {alpha}: chance explains poorly that the model beats {baseline} (holdout, {n} observations). Raw: read it with the adjusted one."),
    "sh_dm_not_significant": _s("p = {p} ≥ {alpha} : on ne peut pas exclure que le modèle ne batte {baseline} que par hasard (holdout, {n} observations).",
                                "p = {p} ≥ {alpha}: we cannot rule out that the model beats {baseline} by chance alone (holdout, {n} observations)."),
    "sh_bh_significant": _s("p ajustée = {adj} (rang {rank}/{n}, α = {alpha}) : reste significative après correction du nombre de cibles testées.",
                            "adjusted p = {adj} (rank {rank}/{n}, α = {alpha}): stays significant after correcting for the number of targets tested."),
    "sh_bh_not_significant": _s("p ajustée = {adj} (rang {rank}/{n}, α = {alpha}) : ne survit pas à la correction : probablement un hasard de plus parmi les cibles testées.",
                                "adjusted p = {adj} (rank {rank}/{n}, α = {alpha}): does not survive the correction: probably one more chance finding among the targets tested."),
    "sh_bh_missing": _s("Pas de résultat Diebold-Mariano à situer parmi les autres cibles.", "No Diebold-Mariano result to rank among the other targets."),
    "sh_spearman": _s("ρ = {rho} (p = {p}, {n} essais) : diagnostic en lecture seule, n'influence jamais une sélection.",
                      "ρ = {rho} (p = {p}, {n} trials): read-only diagnostic, never influences a selection."),
    "sh_spearman_missing": _s("Non calculable : {n} essai(s) avec test et holdout, minimum 3.", "Not computable: {n} trial(s) with test and holdout, minimum 3."),
    "sh_pbo": _s("PBO = {pbo}, intervalle à 90 % [{lo} ; {hi}] ({n} combinaisons).", "PBO = {pbo}, 90% interval [{lo}; {hi}] ({n} combinations)."),
    "sh_pbo_missing": _s("Non calculé : pas assez d'essais avec folds ou chemins complets sur cette cible.", "Not computed: not enough trials with complete folds or paths on this target."),
    "sh_trials": _s("{n} configuration(s) cumulées : c'est ce nombre, pas celui du run, qui sert à déflater les scores.",
                    "{n} cumulative configuration(s): this number, not the run's own, deflates the scores."),
    "sp_data": _s("Données : snapshot {snapshot}. Garde anti-fuite : {shifted} série(s) retardée(s), {dropped} retirée(s).",
                  "Data: snapshot {snapshot}. Anti-leak guard: {shifted} series delayed, {dropped} dropped."),
    "sp_scheme_wf": _s("Validation walk-forward : {folds} folds, entraînement initial {train} % de l'historique, embargo : {embargo}, purge : {purge}.",
                       "Walk-forward validation: {folds} folds, initial training {train}% of history, embargo: {embargo}, purge: {purge}."),
    "sp_scheme_cpcv": _s("Validation CPCV : {groups} groupes, {k} groupes de test par combinaison, embargo : {embargo}, purge : {purge}.",
                         "CPCV validation: {groups} groups, {k} test groups per combination, embargo: {embargo}, purge: {purge}."),
    "sp_selection": _s("Sélection : {run} essai(s) dans ce run, {all} cumulés sur la cible et l'horizon.",
                       "Selection: {run} trial(s) in this run, {all} cumulative on the target and horizon."),
    "sp_holdout": _s("Holdout terminal : les {months} derniers mois, mis de côté avant tout calcul et jamais vus par la sélection.",
                     "Terminal holdout: the last {months} months, set aside before any computation and never seen by selection."),
    "sp_holdout_cpcv": _s("Pas de holdout terminal en CPCV : toutes les combinaisons participent au scan.", "No terminal holdout in CPCV: every combination takes part in the scan."),
    "sp_dm": _s("Test de Diebold-Mariano contre {baseline} sur le holdout ({n} observations), seuil p < {alpha}.",
                "Diebold-Mariano test against {baseline} on the holdout ({n} observations), threshold p < {alpha}."),
    "sp_dm_biased": _s("Test de Diebold-Mariano contre {baseline} sur le fold de sélection ({n} observations) : biaisé, non retenu dans la correction.",
                       "Diebold-Mariano test against {baseline} on the selection fold ({n} observations): biased, not kept in the correction."),
    "sp_bh": _s("Correction de Benjamini-Hochberg à α = {alpha} sur {n} cible(s) testée(s), par famille d'actifs.",
                "Benjamini-Hochberg correction at α = {alpha} over {n} target(s) tested, per asset family."),
    # ------------------------------------------------------------------ simulation / fonds : modèles ML
    "ml_card_title": _s("Piloter avec un modèle ML entraîné", "Drive with a trained ML model"),
    "ml_card_intro": _s(
        "Choisis un modèle déjà entraîné, des seuils d'entrée et de sortie et un instrument : le fonds passe les ordres que le "
        "modèle aurait donnés, avec les mêmes frais et les mêmes règles d'enveloppe que tes ordres manuels. Les modèles "
        "directionnels prédisent le sens du prix ; les modèles alpha prédisent la surperformance sur un benchmark et se tradent "
        "en paire couverte.",
        "Pick an already-trained model, entry and exit thresholds and an instrument: the fund places the orders the model would "
        "have given, with the same fees and wrapper rules as your manual orders. Directional models predict the price direction; "
        "alpha models predict outperformance against a benchmark and are traded as a hedged pair."),
    "ml_kind_directional_short": _s("sens du prix", "price direction"),
    "ml_kind_alpha_short": _s("surperformance vs benchmark", "outperformance vs benchmark"),
    "ml_models_available": _s("{n} modèle(s)", "{n} model(s)"),
    "ml_suspect_excluded": _s("{n} modèle(s) suspect(s) non sélectionnables", "{n} suspect model(s) not selectable"),
    "ml_rule_honesty": _s(
        "Chaque règle créée est comptée comme un essai de plus sur la cible : essayer des seuils jusqu'à trouver les meilleurs "
        "gonfle le résultat, c'est pourquoi aucun aperçu n'est proposé avant la création.",
        "Every rule created counts as one more trial on the target: trying thresholds until the best ones show up inflates the "
        "result, which is why no preview is offered before creation."),
    "ml_rule_apply_hint": _s("La règle est appliquée tout de suite, puis le fonds s'ouvre.", "The rule is applied right away, then the fund opens."),
    "pred_alpha_empty": _s("Aucun modèle alpha entraîné pour l'instant.", "No alpha model trained yet."),
    "pred_alpha_empty_hint": _s(
        "Lance un run avec « Cible : alpha vs benchmark » depuis la page Lancer. Les modèles alpha d'un autre PC apparaissent "
        "après la synchronisation.",
        "Launch a run with \"Target: alpha vs benchmark\" from the Launch page. Alpha models trained on another PC show up "
        "after synchronisation."),
    "m_section_title": _s("Métriques par fold", "Metrics per fold"),
    "m_section_intro": _s(
        "L'AUC puis le F1 d'abord. Chaque ligne est un fold de test (une période jamais vue à l'entraînement) ; la moyenne "
        "est la première ligne. Les 5 premiers folds sont affichés, le reste se déplie.",
        "AUC first, then F1. Each row is a test fold (a period never seen in training); the mean is the first row. The "
        "first 5 folds are shown, the rest unfolds."),
    "metric_AUC_ovr_4cls": _s("AUC : aire sous la courbe ROC, une classe contre les trois autres, moyennée sur les 4 mouvements. 0,5 = hasard.",
                              "AUC: area under the ROC curve, one class against the other three, averaged over the 4 moves. 0.5 = chance."),
    "metric_F1_dir": _s("F1 directionnel : hausse contre baisse, intensité ignorée. Moyenne harmonique de la précision et du rappel.",
                        "Directional F1: up vs down, intensity ignored. Harmonic mean of precision and recall."),
    "metric_F1_4cls": _s("F1 sur les 4 mouvements (baisse forte / faible, hausse faible / forte), moyenne simple.",
                         "F1 over the 4 moves (strong / weak down, weak / strong up), simple average."),
    "metric_Acc_dir": _s("Part des directions (hausse / baisse) correctement devinées.", "Share of directions (up / down) guessed right."),
    "metric_BalAcc_4cls": _s("Exactitude équilibrée : rappel moyen des 4 mouvements (insensible aux classes rares).",
                             "Balanced accuracy: mean recall over the 4 moves (insensitive to rare classes)."),
    "metric_MCC_4cls": _s("Coefficient de Matthews : corrélation entre prédiction et réalité, de -1 à 1, 0 = hasard.",
                          "Matthews coefficient: correlation between prediction and outcome, -1 to 1, 0 = chance."),
    "metric_F1_DOWN_FORT": _s("F1 de la seule classe « baisse forte ».", "F1 of the 'strong down' class alone."),
    "metric_F1_UP_FORT": _s("F1 de la seule classe « hausse forte ».", "F1 of the 'strong up' class alone."),
    "metric_Brier_up": _s("Score de Brier de la probabilité de hausse : plus bas = mieux calibrée (0,25 = pile ou face).",
                          "Brier score of the up probability: lower = better calibrated (0.25 = coin flip)."),
    "metric_ECE_up": _s("Erreur de calibration attendue : écart moyen entre probabilité annoncée et fréquence réelle.",
                        "Expected calibration error: mean gap between announced probability and actual frequency."),
}

PAGES_JS_KEYS: list[str] = ["target_short_history", "target_greyed_count"]
