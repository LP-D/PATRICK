"""Minimal internationalization (FR/EN) of the web interface — a string
dict + a cookie to remember the choice, no i18n framework: the site is a
local single-user tool, two languages are enough and one more dependency
(Babel, etc.) would add nothing here. STRINGS dict values ("fr"/"en" pairs)
are UI content, not code documentation, and are intentionally left as-is in
both languages.
"""
from __future__ import annotations

from starlette.requests import Request

LANG_COOKIE = "patrick_lang"
SUPPORTED_LANGS = ("fr", "en")
DEFAULT_LANG = "fr"

STRINGS: dict[str, dict[str, str]] = {
    "tagline": {"fr": "walk-forward · SHAP · Optuna — sans YAML",
                "en": "walk-forward · SHAP · Optuna — no YAML"},
    "banner_fix_errors": {"fr": "Corrige avant de lancer :", "en": "Fix before launching:"},

    "section_settings": {"fr": "Configuration du run", "en": "Run configuration"},

    # Home page: page title (the surface was missing one) and progressive
    # form disclosure.
    "index_title": {"fr": "Poste de lancement", "en": "Launch station"},
    "index_subtitle": {
        "fr": "Configure un run, lance-le, suis-le. Les blocs repliés portent des valeurs par défaut issues de résultats mesurés ; chaque brique de rigueur affiche son état, ON comme OFF, sans qu'il faille les ouvrir.",
        "en": "Configure a run, launch it, follow it. Collapsed blocks carry defaults derived from measured results; every rigor gate shows its state, ON or OFF, without opening them.",
    },
    "adv_state_fields": {"fr": "{n} réglage(s)", "en": "{n} setting(s)"},
    "adv_state_more": {"fr": "+{n}", "en": "+{n}"},
    "adv_state_modified": {"fr": "Modifié depuis le chargement de la page",
                           "en": "Changed since the page was loaded"},
    "recap_horizons": {"fr": "horizons {h}", "en": "horizons {h}"},
    "recap_targets_count": {"fr": "{n} cibles", "en": "{n} targets"},

    # Guards: launch confirmation, config overwrite, validation in the
    # PAGE's language (the browser itself speaks its own). Short names for
    # the rigor gates, for block summaries and the launch recap. Their state
    # is ALWAYS rendered, ON as much as OFF: a missing guarantee is
    # precisely the information that matters.
    "recent_rel_trials": {"fr": "F1_dir, meilleur de {n} essai(s)",
                          "en": "F1_dir, best of {n} trial(s)"},
    "recent_rel_running": {"fr": "essais en cours", "en": "trials in progress"},
    "recent_rel_none": {"fr": "aucun essai enregistré", "en": "no trial recorded"},

    "gate_data_quality_enabled": {"fr": "Qualité", "en": "Quality"},
    "gate_purge": {"fr": "Purge", "en": "Purge"},
    "gate_embargo_enabled": {"fr": "Embargo", "en": "Embargo"},
    "gate_uniqueness_weights": {"fr": "Unicité", "en": "Uniqueness"},
    "gate_calibration": {"fr": "Calibration", "en": "Calibration"},
    "gate_stacking": {"fr": "Stacking", "en": "Stacking"},
    "confirm_line_gates": {"fr": "Rigueur : {g}.", "en": "Rigor: {g}."},

    "btn_confirm_launch": {"fr": "Confirmer le lancement", "en": "Confirm launch"},
    "btn_cancel": {"fr": "Annuler", "en": "Cancel"},
    "confirm_line_target": {"fr": "Cible {t}, horizons {h}, régimes {r}.",
                            "en": "Target {t}, horizons {h}, regimes {r}."},
    "confirm_line_scheme": {"fr": "Schéma {s}.", "en": "Scheme {s}."},
    "confirm_line_combos": {"fr": "{n} combinaisons à évaluer.", "en": "{n} combinations to evaluate."},
    "confirm_line_combos_unknown": {"fr": "Nombre de combinaisons non calculable depuis ce formulaire.",
                                    "en": "Combination count not computable from this form."},
    "confirm_line_queue": {"fr": "{n} run(s) déjà en file : celui-ci démarrera après.",
                           "en": "{n} run(s) already queued: this one starts after them."},
    "confirm_line_queue_free": {"fr": "Aucun run en file : celui-ci démarre immédiatement.",
                                "en": "Nothing queued: this one starts immediately."},
    "glossary_open_aria": {"fr": "Définition : {term}", "en": "Definition: {term}"},
    "validation_required": {"fr": "Ce champ est obligatoire.", "en": "This field is required."},
    "validation_range": {"fr": "Valeur hors des bornes autorisées.", "en": "Value outside the allowed range."},
    "validation_type": {"fr": "Format attendu non respecté.", "en": "Expected format not matched."},

    "movers_pick_hint": {"fr": "Clique un symbole pour en faire la cible du run.",
                         "en": "Click a symbol to make it the run's target."},
    "movers_not_a_target": {"fr": "{s} n'est pas une cible disponible.",
                            "en": "{s} is not an available target."},
    "section_progress": {"fr": "Avancement", "en": "Progress"},
    "section_recent": {"fr": "Derniers runs", "en": "Recent runs"},
    "section_stock": {"fr": "Aperçu marché — cible choisie", "en": "Market overview — chosen target"},
    "no_run_yet": {"fr": "Aucun run pour l'instant — configure et lance à gauche.",
                   "en": "No run yet — configure and launch on the left."},
    "queue_summary": {"fr": "{n} run(s) en attente : {names}", "en": "{n} run(s) queued: {names}"},
    "run_queued_confirm": {"fr": "Run « {name} » mis en file d'attente (position {position}).",
                            "en": "Run “{name}” queued (position {position})."},
    "run_launch_error": {"fr": "Erreur lors du lancement.", "en": "Error launching the run."},

    "movers_title": {"fr": "Plus fortes variations (5 jours)", "en": "Biggest movers (5 days)"},
    "movers_updated_at": {"fr": "Mis à jour à {time}", "en": "Updated at {time}"},
    "movers_computing": {"fr": "Calcul en cours (toutes les 30 min)…", "en": "Computing (every 30 min)…"},
    "movers_gainers": {"fr": "▲ Hausses", "en": "▲ Gainers"},
    "movers_losers": {"fr": "▼ Baisses", "en": "▼ Losers"},

    "section_run": {"fr": "Run", "en": "Run"},
    "field_run_name": {"fr": "Nom du run (généré automatiquement)", "en": "Run name (auto-generated)"},

    "section_objective": {"fr": "Objectif — que prédire ?", "en": "Objective — what to predict?"},
    "field_target": {"fr": "Cible(s)", "en": "Target(s)"},
    "target_multiselect_hint": {
        "fr": "Ctrl/Cmd + clic (ou glisser) pour sélectionner plusieurs cibles — un run est lancé par cible, à la suite.",
        "en": "Ctrl/Cmd + click (or drag) to pick multiple targets — one run launches per target, in sequence.",
    },
    "news_recent": {"fr": "Actualités récentes :", "en": "Recent news:"},
    "field_horizons": {"fr": "Horizons (jours)", "en": "Horizons (days)"},
    "horizons_multiselect_hint": {
        "fr": "Ctrl/Cmd + clic pour sélectionner plusieurs horizons — le pipeline ne traite que ces valeurs.",
        "en": "Ctrl/Cmd + click to pick multiple horizons — the pipeline only processes these values.",
    },
    "field_flat_thr": {"fr": 'Seuil "flat" (mouvement neutre, ex. 0.003 = 0.3%)',
                        "en": 'Flat threshold (neutral move, e.g. 0.003 = 0.3%)'},
    "field_regimes": {"fr": "Régimes (séparés par des virgules, ex. GLOBAL)",
                       "en": "Regimes (comma-separated, e.g. GLOBAL)"},

    "section_universe": {"fr": "Univers — features brutes", "en": "Universe — raw features"},
    "universe_hint": {"fr": ("Toute la base disponible est utilisée automatiquement (tickers yfinance + "
                             "séries FRED), à l'exclusion de la cible choisie ci-dessus."),
                       "en": ("The whole available base is used automatically (yfinance tickers + FRED "
                              "series), excluding the target chosen above.")},
    "field_start_date": {"fr": "Date de début", "en": "Start date"},
    "field_yf_coverage": {"fr": "Couverture minimale yfinance (0-1)", "en": "Minimum yfinance coverage (0-1)"},

    "section_data_quality": {"fr": "Qualité de données (portes à l'ingestion)",
                              "en": "Data quality (ingestion gates)"},
    "data_quality_hint": {"fr": ("Chaque série est contrôlée avant d'entrer dans l'univers de features "
                                 "(prix figés, trous de cotation, rendements aberrants, fin de série "
                                 "précoce, séries FRED absentes) — exclusion motivée et persistée, "
                                 "jamais silencieuse."),
                           "en": ("Every series is checked before entering the feature universe (frozen "
                                  "prices, quote gaps, aberrant returns, early series end, missing FRED "
                                  "series) — exclusions are explicit and persisted, never silent.")},
    "field_data_quality_enabled": {"fr": "Portes de qualité actives",
                                    "en": "Data quality gates active"},
    "field_max_frozen_run": {"fr": "Clôtures identiques consécutives max.",
                              "en": "Max. consecutive identical closes"},
    "field_max_gap_bdays": {"fr": "Trou de cotation max. (jours ouvrés)",
                             "en": "Max. quote gap (business days)"},
    "field_max_robust_z": {"fr": "Rendement aberrant — z robuste max.",
                            "en": "Aberrant return — max. robust z"},
    "field_max_universe_exclusion_frac": {"fr": "Fraction max. de l'univers exclue avant échec",
                                           "en": "Max. excluded universe fraction before failure"},

    "section_features": {"fr": "Familles de features", "en": "Feature families"},
    "vol_models_hint": {"fr": "Modèles de volatilité (famille vol_models) :",
                         "en": "Volatility models (vol_models family):"},
    "field_interact_base": {"fr": "Interactions — base", "en": "Interactions — base"},
    "field_interact_pairs": {"fr": "Interactions — paires", "en": "Interactions — pairs"},
    "field_interact_final": {"fr": "Interactions — final N", "en": "Interactions — final N"},
    "field_pool_prefilter": {"fr": "Pool prefilter", "en": "Pool prefilter"},

    "section_validation": {"fr": "Validation (walk-forward ou CPCV)", "en": "Validation (walk-forward or CPCV)"},
    "field_scheme": {"fr": "Schéma", "en": "Scheme"},
    "field_scheme_walkforward": {"fr": "Walk-forward", "en": "Walk-forward"},
    "field_scheme_cpcv": {"fr": "CPCV (combinatoire purgée)", "en": "CPCV (combinatorial purged)"},
    "field_n_groups": {"fr": "CPCV — nombre de groupes (N)", "en": "CPCV — number of groups (N)"},
    "field_k_test_groups": {"fr": "CPCV — groupes de test par combinaison (k)",
                             "en": "CPCV — test groups per combination (k)"},
    "field_n_wf_folds": {"fr": "Nombre de folds (walk-forward)", "en": "Number of folds (walk-forward)"},
    "field_min_train_frac": {"fr": "Fraction min. d'entraînement", "en": "Min. training fraction"},
    "field_min_train_rows": {"fr": "Lignes min. train", "en": "Min. train rows"},
    "field_min_test_rows": {"fr": "Lignes min. test", "en": "Min. test rows"},
    "field_purge": {"fr": "Purge (retire les lignes proches de la frontière train/test)",
                     "en": "Purge (removes rows near the train/test boundary)"},
    "field_embargo_enabled": {"fr": "Embargo (retire les premières lignes de test après la coupure)",
                               "en": "Embargo (removes the first test rows after the cut)"},
    "field_embargo_bars": {"fr": "Barres d'embargo (vide = horizon)",
                            "en": "Embargo bars (blank = horizon)"},

    "section_selection": {"fr": "Sélection de features", "en": "Feature selection"},
    "field_method": {"fr": "Méthode", "en": "Method"},
    "field_n_features_grid": {"fr": "Grille N (séparée par des virgules, ex. 5,6,7,8 ou 5-15)",
                               "en": "N grid (comma-separated, e.g. 5,6,7,8 or 5-15)"},
    "field_shap_sample": {"fr": "Échantillon SHAP", "en": "SHAP sample"},
    "field_track_stability": {"fr": "Suivre la stabilité de la sélection (Jaccard entre folds)",
                               "en": "Track selection stability (Jaccard across folds)"},

    "section_sampler": {"fr": "Sampler (rééquilibrage des classes)", "en": "Sampler (class rebalancing)"},
    "field_uniqueness_weights": {"fr": "Poids d'unicité / bootstrap séquentiel (horizons chevauchants)",
                                  "en": "Uniqueness weights / sequential bootstrap (overlapping horizons)"},

    "section_models": {"fr": "Modèles", "en": "Models"},
    "field_calibration": {"fr": "Calibration (probabilités)", "en": "Calibration (probabilities)"},
    "field_stacking": {"fr": "Stacking", "en": "Stacking"},

    "section_tuning": {"fr": "Tuning Optuna", "en": "Optuna tuning"},
    "field_enabled": {"fr": "Activé", "en": "Enabled"},
    "field_top_k": {"fr": "Top-K configs affinées", "en": "Top-K refined configs"},
    "field_n_trials": {"fr": "Essais Optuna", "en": "Optuna trials"},
    "field_cv_splits": {"fr": "Folds CV", "en": "CV folds"},
    "field_optuna_select_top_k_per_horizon": {"fr": "Budget Optuna par horizon", "en": "Optuna budget per horizon"},

    "section_output": {"fr": "Sortie", "en": "Output"},
    "field_output_dir": {"fr": "Dossier de sortie", "en": "Output directory"},
    "field_seed": {"fr": "Seed", "en": "Seed"},

    "btn_launch_run": {"fr": "Lancer le run", "en": "Launch run"},

    # app.js (injected via window.I18N)
    "phase_ingestion": {"fr": "Ingestion des données…", "en": "Ingesting data…"},
    "phase_features": {"fr": "Construction des features…", "en": "Building features…"},
    "phase_scan": {"fr": "Grille sélection × sampler × algo…", "en": "Selection × sampler × algo grid…"},
    "phase_tuning": {"fr": "Affinage Optuna des meilleures configs…", "en": "Optuna tuning of the best configs…"},
    "phase_export": {"fr": "Export du modèle final…", "en": "Exporting final model…"},
    "phase_done": {"fr": "Terminé.", "en": "Done."},
    "status_connection_lost": {"fr": "Connexion au serveur perdue — nouvelle tentative…",
                                "en": "Connection to server lost — retrying…"},
    "status_running": {"fr": "{phase} ({pct}%, {elapsed}s écoulées)", "en": "{phase} ({pct}%, {elapsed}s elapsed)"},
    "status_error": {"fr": "Erreur : {error}", "en": "Error: {error}"},
    "status_done": {"fr": "Terminé en {elapsed}s.", "en": "Done in {elapsed}s."},
    "results_title": {"fr": "Résultats", "en": "Results"},
    "results_summary": {"fr": "{n} évaluations{tuned}.", "en": "{n} evaluations{tuned}."},
    "results_summary_tuned": {"fr": " + {n} après tuning", "en": " + {n} after tuning"},
    "results_best_config": {"fr": "Meilleure config", "en": "Best config"},
    "results_leaderboard": {"fr": "Leaderboard (top {n}, triable par colonne)",
                             "en": "Leaderboard (top {n}, sortable by column)"},
    "artifact_leaderboard_csv": {"fr": "Leaderboard (CSV)", "en": "Leaderboard (CSV)"},
    "artifact_leaderboard_xlsx": {"fr": "Leaderboard (Excel)", "en": "Leaderboard (Excel)"},
    "artifact_tuned_csv": {"fr": "Configs affinées (CSV)", "en": "Refined configs (CSV)"},
    "artifact_best_model": {"fr": "Meilleur modèle (joblib)", "en": "Best model (joblib)"},
    "artifact_best_model_meta": {"fr": "Métadonnées (JSON)", "en": "Metadata (JSON)"},
    # Fix report [per-horizon export] : un run multi-horizons exporte
    # désormais un modèle par horizon (`best_model_h<horizon>`, cf.
    # worker.py::_summarize_result) -- {h} substitué dynamiquement, une seule
    # entrée couvre tous les horizons.
    "artifact_best_model_h": {"fr": "Modèle h={h}j (joblib)", "en": "Model h={h}d (joblib)"},
    "artifact_best_model_meta_h": {"fr": "Métadonnées h={h}j (JSON)", "en": "Metadata h={h}d (JSON)"},

    # Phase 2 — statistical validity
    "stat_holdout": {"fr": "Holdout terminal ({n} obs. jamais vues) : F1_dir={f1}",
                      "en": "Terminal holdout ({n} unseen obs.): F1_dir={f1}"},
    "stat_dm_significant": {"fr": "Diebold-Mariano vs {baseline} : p={p} — significatif",
                             "en": "Diebold-Mariano vs {baseline}: p={p} — significant"},
    "stat_dm_not_significant": {"fr": "Diebold-Mariano vs {baseline} : p={p} — non significatif",
                                 "en": "Diebold-Mariano vs {baseline}: p={p} — not significant"},
    "stat_cumulative_trials": {"fr": "{n} essais cumulés sur cette cible/horizon (tout l'historique)",
                                "en": "{n} cumulative trials on this target/horizon (full history)"},
    "stat_pbo": {"fr": "PBO (surapprentissage de backtest) : {pbo} ({n} combinaisons)",
                 "en": "PBO (backtest overfitting): {pbo} ({n} combinations)"},
    "stat_pbo_reliability": {
        "fr": "IC 90% du PBO (bootstrap, {n} combinaisons) : [{lo}, {hi}] — un PBO issu d'un run "
              "unique n'est pas interprétable isolément",
        "en": "PBO 90% CI (bootstrap, {n} combinations): [{lo}, {hi}] — a single-run PBO is not "
              "interpretable in isolation",
    },

    # market.js
    "preview_loading": {"fr": "Chargement…", "en": "Loading…"},
    "preview_no_data": {"fr": "Pas de données pour cette période.", "en": "No data for this period."},
    "preview_unavailable": {"fr": "Indisponible : {error}", "en": "Unavailable: {error}"},
    "preview_load_error": {"fr": "Erreur de chargement.", "en": "Loading error."},
    "news_loading": {"fr": "Chargement…", "en": "Loading…"},
    "news_none": {"fr": "Pas d'actualité disponible pour cette cible.", "en": "No news available for this target."},
    "news_load_error": {"fr": "Erreur de chargement des actualités.", "en": "Error loading news."},
    "movers_no_data": {"fr": "Pas encore de données.", "en": "No data yet."},

    # target group category names (optgroups)
    "group_indices": {"fr": "Indices", "en": "Indices"},
    "group_broad_etfs": {"fr": "ETFs larges & style", "en": "Broad & style ETFs"},
    "group_sector_etfs": {"fr": "ETFs sectoriels & thématiques", "en": "Sector & thematic ETFs"},
    "group_bonds_etfs": {"fr": "Obligataire & taux (ETFs)", "en": "Bonds & rates (ETFs)"},
    "group_commodities_fx_etfs": {"fr": "Matières premières & devises (ETFs)", "en": "Commodities & FX (ETFs)"},
    "group_volatility": {"fr": "Volatilité", "en": "Volatility"},
    "group_crypto": {"fr": "Crypto", "en": "Crypto"},
    "group_international_etfs": {"fr": "International (ETFs pays)", "en": "International (country ETFs)"},
    "group_stocks": {"fr": "Actions individuelles", "en": "Individual stocks"},
    "group_fred_macro": {"fr": "Macro (FRED)", "en": "Macro (FRED)"},

    # Phase 7 — history/universe
    # P8: "/" became the synthesis dashboard, the launcher moved to
    # "/launch" -- nav_home now names the SYNTHESIS page (still the site's
    # "/" landing point, hence reused by every breadcrumb's first link),
    # nav_launch is the new, separate entry for the launcher.
    "nav_home": {"fr": "Synthèse", "en": "Overview"},
    "nav_launch": {"fr": "Lancer", "en": "Launch"},
    "nav_runs": {"fr": "Historique", "en": "History"},
    "nav_universe": {"fr": "Univers", "en": "Universe"},
    # feature/ticker-stats-panel
    "nav_commodities": {"fr": "Matières premières", "en": "Commodities"},
    "nav_macro": {"fr": "Macro (FRED)", "en": "Macro (FRED)"},
    "assetpanel_subtitle": {
        "fr": "Un panneau de statistiques par actif de ce groupe (config/defaults.py::DEFAULT_TARGET_GROUPS) : rendements sur les horizons du pipeline, vue longue période, z-score glissant, moyennes mobiles, volatilité — des lectures directes du cours, jamais une prédiction du modèle. Chargées ci-dessous une par une, par actif.",
        "en": "One stats panel per asset in this group (config/defaults.py::DEFAULT_TARGET_GROUPS): returns over the pipeline's horizons, a longer-window view, rolling z-score, moving averages, volatility — direct reads of the price series, never a model prediction. Loaded below one asset at a time.",
    },
    "assetpanel_bars_hint": {
        "fr": "Fenêtres exprimées en barres de la série (jours de bourse pour ces futures), pas en durée calendaire.",
        "en": "Windows are counted in bars of the series (trading days for these futures), not calendar time.",
    },
    "assetpanel_bars_hint_macro": {
        "fr": "Fenêtres exprimées en barres de la série, pas en durée calendaire — plusieurs séries FRED de ce groupe sont mensuelles ou trimestrielles (CPI, GDP, PAYEMS, RSAFS, UMCSENT, UNRATE), une barre y couvre donc bien plus qu'un jour.",
        "en": "Windows are counted in bars of the series, not calendar time — several FRED series in this group are monthly or quarterly (CPI, GDP, PAYEMS, RSAFS, UMCSENT, UNRATE), so one bar there spans much more than a day.",
    },
    "assetpanel_loading": {"fr": "Chargement…", "en": "Loading…"},
    "assetpanel_error": {"fr": "Indisponible : {error}", "en": "Unavailable: {error}"},
    "assetpanel_insufficient": {
        "fr": "Historique insuffisant pour calculer ces statistiques pour l'instant.",
        "en": "Not enough history to compute these stats yet.",
    },
    "assetpanel_load_error": {"fr": "Erreur de chargement.", "en": "Loading error."},
    "assetpanel_returns": {"fr": "Rendements (horizons du pipeline)", "en": "Returns (pipeline horizons)"},
    "assetpanel_long_window": {"fr": "Vue longue période", "en": "Longer-window view"},
    "assetpanel_zscore": {"fr": "Z-score (60 barres)", "en": "Z-score (60 bars)"},
    "assetpanel_ma": {"fr": "Cours vs moyenne mobile", "en": "Price vs moving average"},
    "assetpanel_vol": {"fr": "Volatilité (proxy Heston, réalisée annualisée)", "en": "Volatility (Heston proxy, annualized realized)"},
    "assetpanel_vol_current": {"fr": "courante (20 barres)", "en": "current (20 bars)"},
    "assetpanel_vol_long_run": {"fr": "long terme (~252 barres)", "en": "long-run (~252 bars)"},
    "assetpanel_bars": {"fr": "{n} barres", "en": "{n} bars"},

    # "Observation station" world — chrome: theme toggle and activity
    # record strip. The theme button names the current STATE, not the
    # action (it's an indicator with a dot): "Day" = currently in light mode.
    "theme_light": {"fr": "Jour", "en": "Day"},
    "theme_dark": {"fr": "Nuit", "en": "Night"},
    "record_aria": {"fr": "Activité des runs dans le temps",
                    "en": "Run activity over time"},
    "record_loading": {"fr": "Lecture de la bande…", "en": "Reading the record…"},
    "record_unavailable": {"fr": "Bande illisible : la base de suivi n'a pas pu être ouverte.",
                           "en": "Record unreadable: the tracking database could not be opened."},
    "record_empty": {"fr": "Aucun run enregistré — la bande se remplira au premier run lancé.",
                     "en": "No run recorded yet — the record fills from the first run launched."},
    "record_runs": {"fr": "runs", "en": "runs"},
    "record_span_range": {"fr": "du {from} au {to}", "en": "from {from} to {to}"},
    # The station's verdict. "What holds" is not colored --ok: the product's
    # stance is that a clearly established "no" is a successful result, so
    # zero survivors is not a bad state.
    "verdict_survivors": {"fr": "CE QUI TIENT", "en": "WHAT HOLDS"},
    "verdict_survivors_rel": {"fr": "cibles dont le signal survit à la correction entre cibles (BH, α={alpha})",
                              "en": "targets whose signal survives the across-target correction (BH, α={alpha})"},
    "verdict_not_computable": {"fr": "aucune cible n'a encore de résultat Diebold-Mariano",
                               "en": "no target has a Diebold-Mariano result yet"},
    "verdict_cost": {"fr": "CE QUE ÇA A COÛTÉ", "en": "WHAT IT COST"},
    "verdict_cost_rel": {"fr": "essais cumulés sur {runs} run(s), {targets} cible(s)",
                         "en": "cumulative trials over {runs} run(s), {targets} target(s)"},

    # Local-scope lines: each dense surface answers ITS OWN question,
    # without repeating the global verdict the banner already carries.
    "scope_universe": {"fr": "CIBLES EXPLORÉES", "en": "TARGETS EXPLORED"},
    "scope_universe_rel": {"fr": "dont {done} avec au moins un run terminé · {never} jamais lancées",
                           "en": "of which {done} with at least one finished run · {never} never launched"},
    "scope_runs": {"fr": "RUNS COMPARÉS AUX BASELINES", "en": "RUNS COMPARED TO BASELINES"},
    "scope_runs_rel": {"fr": "runs affichés ayant produit un résultat Diebold-Mariano",
                       "en": "listed runs that produced a Diebold-Mariano result"},

    "record_span_day": {"fr": "le {d}", "en": "on {d}"},
    "record_hidden": {"fr": "({n} hors champ)", "en": "({n} off-strip)"},
    "record_kbd": {"fr": "Activité des runs — flèches pour parcourir, Entrée pour ouvrir",
                   "en": "Run activity — arrows to browse, Enter to open"},
    "record_scale": {"fr": "hauteur = essais (log, max {max})",
                     "en": "height = trials (log, max {max})"},
    "record_counts": {"fr": "{done} terminés · {running} en cours · {failed} échoués",
                      "en": "{done} done · {running} running · {failed} failed"},
    "record_unknown": {"fr": "{n} sans compte d'essais (hauteur plancher)",
                       "en": "{n} with no trial count (floor height)"},
    "record_trials": {"fr": "essais", "en": "trials"},
    "record_no_trials": {"fr": "essais inconnus", "en": "trial count unknown"},
    "record_tap_again": {"fr": "touche à nouveau pour ouvrir", "en": "tap again to open"},

    # Text equivalents for the canvases. A chart with no replacement text
    # does not exist for a screen reader; these labels are rewritten by
    # `market.js` / `simulate.js` with the real bounds once plotted.
    "preview_aria_empty": {"fr": "Cours de la cible — aucune donnée tracée pour l'instant.",
                           "en": "Target price history — nothing plotted yet."},
    "preview_aria": {"fr": "Cours de {symbol} sur {period} : {n} points, du plus bas {min} au plus haut {max}, dernier point {last}.",
                     "en": "{symbol} price over {period}: {n} points, low {min} to high {max}, last {last}."},
    "sim_aria_equity_empty": {"fr": "Courbe de capital — aucune simulation lancée.",
                              "en": "Equity curve — no simulation run yet."},
    "sim_aria_drawdown_empty": {"fr": "Drawdown — aucune simulation lancée.",
                                "en": "Drawdown — no simulation run yet."},
    "sim_aria_dist_empty": {"fr": "Distribution des rendements par trade — aucune simulation lancée.",
                            "en": "Per-trade return distribution — no simulation run yet."},
    "sim_aria_equity": {"fr": "Courbe de capital sur {n} points : de {first} à {last}, comparée au buy-and-hold qui finit à {bh}.",
                        "en": "Equity curve over {n} points: {first} to {last}, against buy-and-hold ending at {bh}."},
    "sim_aria_drawdown": {"fr": "Drawdown sur {n} points, creux maximal {max}.",
                          "en": "Drawdown over {n} points, deepest {max}."},
    "sim_aria_dist": {"fr": "Distribution de {n} trades : {pos} gagnants, {neg} perdants, du pire {min} au meilleur {max}.",
                      "en": "Distribution of {n} trades: {pos} winning, {neg} losing, worst {min}, best {max}."},

    # Phase 4 — investment simulator
    "nav_simulate": {"fr": "Simulateur", "en": "Simulator"},
    "sim_title": {"fr": "Simulateur d'investissement (mono-actif)", "en": "Investment simulator (single-asset)"},
    "sim_section_config": {"fr": "Configuration de la stratégie", "en": "Strategy configuration"},
    "sim_section_equity": {"fr": "Courbe de capital & drawdown", "en": "Equity curve & drawdown"},
    "sim_section_metrics": {"fr": "Métriques vs buy-and-hold", "en": "Metrics vs buy-and-hold"},
    "sim_section_distribution": {"fr": "Distribution des rendements par trade", "en": "Per-trade return distribution"},
    "sim_section_trades": {"fr": "Journal des trades", "en": "Trade log"},
    "sim_field_run": {"fr": "Run", "en": "Run"},
    "sim_field_trial": {"fr": "Modèle (essai)", "en": "Model (trial)"},
    "sim_field_mode": {"fr": "Mode signal → position", "en": "Signal → position mode"},
    "sim_mode_threshold": {"fr": "Seuil binaire", "en": "Binary threshold"},
    "sim_mode_proportional": {"fr": "Proportionnel", "en": "Proportional"},
    "sim_mode_kelly": {"fr": "Kelly fractionnaire", "en": "Fractional Kelly"},
    "sim_field_threshold": {"fr": "Seuil (proba)", "en": "Threshold (proba)"},
    "sim_field_kelly_fraction": {"fr": "Fraction de Kelly", "en": "Kelly fraction"},
    "sim_field_max_leverage": {"fr": "Levier max", "en": "Max leverage"},
    "sim_field_max_position": {"fr": "Position max", "en": "Max position"},
    "sim_field_short_allowed": {"fr": "Vente à découvert autorisée", "en": "Short selling allowed"},
    "sim_field_overlap_mode": {"fr": "Horizons chevauchants", "en": "Overlapping horizons"},
    "sim_overlap_tranches": {"fr": "Tranches (moyenne des signaux actifs)", "en": "Tranches (average of active signals)"},
    "sim_overlap_renewed": {"fr": "Position unique renouvelée", "en": "Single renewed position"},
    "sim_field_asset_class": {"fr": "Classe d'actif (frictions par défaut)", "en": "Asset class (default frictions)"},
    "sim_field_spread_bps": {"fr": "Spread (bps, aller-retour)", "en": "Spread (bps, round-trip)"},
    "sim_field_commission_bps": {"fr": "Commissions (bps, aller-retour)", "en": "Commissions (bps, round-trip)"},
    "sim_field_carry_bps": {"fr": "Coût de portage (bps/an)", "en": "Carry cost (bps/year)"},
    "sim_run_button": {"fr": "Lancer la simulation", "en": "Run simulation"},
    "sim_no_run_selected": {"fr": "Choisis un run puis un modèle.", "en": "Choose a run then a model."},
    "sim_loading": {"fr": "Simulation en cours…", "en": "Simulating…"},
    "sim_error": {"fr": "Erreur : {error}", "en": "Error: {error}"},
    "sim_kelly_disabled": {"fr": "{message}", "en": "{message}"},
    "sim_overfitting_guard": {"fr": "⚠ {n} configuration(s) de simulation testée(s) sur cette cible — Sharpe déflaté = {dsr}",
                               "en": "⚠ {n} simulation configuration(s) tested on this target — deflated Sharpe = {dsr}"},
    "sim_metric_cagr": {"fr": "CAGR", "en": "CAGR"},
    "sim_metric_vol": {"fr": "Vol. annualisée", "en": "Annualized vol"},
    "sim_metric_sharpe": {"fr": "Sharpe (déflaté)", "en": "Sharpe (deflated)"},
    "sim_metric_sortino": {"fr": "Sortino", "en": "Sortino"},
    "sim_metric_max_dd": {"fr": "Max drawdown (durée)", "en": "Max drawdown (duration)"},
    "sim_metric_turnover": {"fr": "Turnover annuel", "en": "Annual turnover"},
    "sim_metric_hit_rate": {"fr": "Hit rate", "en": "Hit rate"},
    "sim_metric_profit_factor": {"fr": "Profit factor", "en": "Profit factor"},
    "sim_metric_avg_exposure": {"fr": "Exposition moyenne", "en": "Average exposure"},
    "sim_metric_break_even": {"fr": "Coût de rentabilité (break-even)", "en": "Break-even cost"},
    # Simulator empty states at rest. Without them, `/simulate` opens on
    # three blank plotting panels and two header-only tables: the product's
    # least dense surface read as broken rather than waiting.
    "sim_empty_curves": {"fr": "Aucune simulation lancée — choisis un run et un modèle, puis lance la simulation pour tracer la courbe de capital et le drawdown.",
                         "en": "No simulation run yet — pick a run and a model, then launch to plot the equity curve and drawdown."},
    "sim_empty_metrics": {"fr": "Les métriques apparaîtront ici, comparées au buy-and-hold, une fois la simulation lancée.",
                          "en": "Metrics will appear here, compared against buy-and-hold, once the simulation runs."},
    "sim_empty_distribution": {"fr": "La distribution des rendements par trade se calcule à partir des trades simulés — aucun pour l'instant.",
                               "en": "The per-trade return distribution is computed from simulated trades — none yet."},
    "sim_empty_trades": {"fr": "Aucun trade simulé. Le journal complet, exportable en CSV, s'affiche après le lancement.",
                         "en": "No simulated trades. The full log, exportable as CSV, appears after launching."},
    "sim_col_strategy": {"fr": "Stratégie", "en": "Strategy"},
    "sim_col_buy_hold": {"fr": "Buy & hold", "en": "Buy & hold"},
    "sim_trades_download": {"fr": "Exporter en CSV", "en": "Export as CSV"},
    "sim_trades_none": {"fr": "Aucun trade.", "en": "No trades."},

    # Phase 5 — exploratory surfaces (explorer, history, details)
    # Shared columns
    "col_run": {"fr": "Run", "en": "Run"},
    "col_target": {"fr": "Cible", "en": "Target"},
    "col_horizon": {"fr": "Horizon", "en": "Horizon"},
    "col_scheme": {"fr": "Schéma", "en": "Scheme"},
    "col_status": {"fr": "Statut", "en": "Status"},
    "col_started": {"fr": "Lancé", "en": "Started"},
    "col_trials": {"fr": "Essais", "en": "Trials"},
    "col_best_f1": {"fr": "F1_dir", "en": "F1_dir"},
    "col_dm_p": {"fr": "p-value DM", "en": "DM p-value"},

    # Shared helpers
    "h_horizon_unit": {"fr": "{h}j", "en": "{h}d"},
    "h_significant": {"fr": "significatif (p < 0.05)", "en": "significant (p < 0.05)"},
    "h_not_significant": {"fr": "non significatif (p ≥ 0.05)", "en": "not significant (p ≥ 0.05)"},
    "h_not_computed": {"fr": "non calculé", "en": "not computed"},
    "h_not_computable": {"fr": "non calculable", "en": "not computable"},
    "h_ci90": {"fr": "IC 90%", "en": "90% CI"},
    "h_table_empty": {"fr": "Aucune donnée.", "en": "No data."},

    # Runs explorer (rl_*)
    "rl_title": {"fr": "Historique des runs", "en": "Runs history"},
    "rl_subtitle": {"fr": "Tous les runs exécutés depuis le démarrage du serveur (entièrement lu de la base SQLite), ordonnés par date décroissante. Chaque ligne montre la cible, l'horizon, le statut, la date de lancement et le nombre d'essais.", "en": "All runs executed since server startup (fully read from SQLite database), sorted by decreasing date. Each row shows the target, horizon, status, launch date, and number of trials."},
    "rl_filter_all_f": {"fr": "toutes", "en": "all"},
    "rl_filter_all_m": {"fr": "tous", "en": "all"},
    "rl_filter_submit": {"fr": "Filtrer", "en": "Filter"},
    "rl_footer_count": {"fr": "run(s)", "en": "run(s)"},
    "rl_footer_target": {"fr": "cibles uniques", "en": "unique targets"},
    "rl_footer_status": {"fr": "statuts", "en": "statuses"},
    "rl_footer_scheme": {"fr": "schémas", "en": "schemes"},
    "rl_footer_note": {"fr": "Phase 5 : explorateur des runs avec filtrage et métriques détaillées à venir.", "en": "Phase 5: runs explorer with filtering and detailed metrics coming soon."},
    "rl_empty": {"fr": "Aucun run.", "en": "No runs."},
    "rl_empty_hint": {"fr": "Lance un run depuis l'onglet Configuration pour en créer un.", "en": "Launch a run from the Configuration tab to create one."},

    # Universe explorer (un_*)
    "un_title": {"fr": "Univers de cibles", "en": "Targets universe"},
    "un_subtitle": {"fr": "Toutes les cibles configurables (mêmes groupes que le formulaire de lancement), croisées avec l'historique réel de runs — aucune donnée nouvelle, juste la jointure des deux.", "en": "All configurable targets (same groups as the launch form), crossed with actual run history — no new data, just the join of the two."},
    "un_col_symbol": {"fr": "Symbole", "en": "Symbol"},
    "un_col_label": {"fr": "Libellé", "en": "Label"},
    "un_col_source": {"fr": "Source", "en": "Source"},
    "un_col_history": {"fr": "Historique", "en": "History"},
    "un_col_last_run": {"fr": "Dernier run", "en": "Last run"},
    "un_state_done": {"fr": "{n} run(s) terminé(s)", "en": "{n} run(s) done"},
    "un_state_running": {"fr": "{n} run(s) en cours", "en": "{n} run(s) running"},
    "un_state_never": {"fr": "jamais lancée", "en": "never launched"},
    "un_footer": {"fr": "{n} cible(s) · {d} avec au moins un run terminé · {v} jamais lancée(s)", "en": "{n} target(s) · {d} with at least one completed run · {v} never launched"},

    # Targets explorer (tg_*)
    "tg_subtitle": {"fr": "Agrégation sur cette cible : tous les runs, tous les horizons. Métriques cumulées et historique des runs.", "en": "Aggregation for this target: all runs, all horizons. Cumulative metrics and runs history."},
    "tg_empty": {"fr": "Aucun run pour cette cible.", "en": "No runs for this target."},
    "tg_empty_hint": {"fr": "Aucun run n'a été exécuté sur cette cible — lance-en un depuis Configuration.", "en": "No run has been executed on this target — launch one from Configuration."},
    "tg_metric_cumulative": {"fr": "Essais cumulés", "en": "Cumulative trials"},
    "tg_rel_cumulative": {"fr": "Toutes les configurations testées sur cette cible, tout run confondu.", "en": "All configurations tested on this target, across all runs."},
    "tg_metric_runs": {"fr": "Nombre de runs", "en": "Number of runs"},
    "tg_rel_runs": {"fr": "Runs complètement exécutés sur cette cible.", "en": "Completed runs on this target."},
    "tg_section_runs": {"fr": "Historique des runs", "en": "Runs history"},
    "tg_runs_footer": {"fr": "run(s) complètement exécutés sur cette cible", "en": "run(s) completed on this target"},
    "tg_section_pbo": {"fr": "Analyse PBO", "en": "PBO analysis"},
    "tg_pbo_hint": {"fr": "Nombre de blocs satisfont le diagnostic de fiabilité pour PBO sur cette cible.", "en": "Number of blocks satisfy the reliability diagnostic for PBO on this target."},
    "tg_col_nblocks": {"fr": "Blocs", "en": "Blocks"},
    "tg_col_reliability": {"fr": "Fiabilité", "en": "Reliability"},
    "tg_pbo_empty": {"fr": "Pas d'analyse PBO disponible.", "en": "No PBO analysis available."},
    "tg_pbo_footer": {"fr": "Chaque ligne représente un horizon différent.", "en": "Each row represents a different horizon."},

    # Run detail (rd_*)
    "rd_title": {"fr": "Détails du run", "en": "Run details"},
    "rd_ctx_target": {"fr": "cible", "en": "target"},
    "rd_ctx_snapshot": {"fr": "snapshot", "en": "snapshot"},
    "rd_ctx_config": {"fr": "config", "en": "config"},
    "rd_ctx_git": {"fr": "git", "en": "git"},
    "rd_ctx_seed": {"fr": "seed", "en": "seed"},
    "rd_horizon": {"fr": "horizon", "en": "horizon"},
    "rd_started": {"fr": "lancé", "en": "started"},
    "rd_finished": {"fr": "terminé", "en": "finished"},
    "rd_sections": {"fr": "Sections", "en": "Sections"},
    "rd_sections_aria": {"fr": "Sections de la page", "en": "Page sections"},
    "rd_section_summary": {"fr": "Résumé", "en": "Summary"},
    "rd_section_trials": {"fr": "Essais", "en": "Trials"},
    "rd_section_config": {"fr": "Configuration", "en": "Configuration"},

    # Scope lines (shared)
    "scope_universe": {"fr": "Portée de l'univers", "en": "Universe scope"},
    "scope_universe_rel": {"fr": "{done} avec un run complètement exécuté, {never} jamais lancée(s)", "en": "{done} with a completed run, {never} never launched"},
    # Phase 5: improved empty states for hardening
    "empty_runs_title": {"fr": "Aucun run pour l'instant.", "en": "No run yet."},
    "empty_runs_hint": {"fr": "Configure et lance un run depuis le poste de lancement.", "en": "Configure and launch a run from the launch station."},
}


def get_lang(request: Request) -> str:
    lang = request.query_params.get("lang") or request.cookies.get(LANG_COOKIE)
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def translator(lang: str):
    def t(key: str, **kwargs) -> str:
        entry = STRINGS.get(key)
        if entry is None:
            return key
        text = entry.get(lang) or entry.get(DEFAULT_LANG) or key
        return text.format(**kwargs) if kwargs else text
    return t


def js_strings(lang: str) -> dict[str, str]:
    """Sous-ensemble des chaînes nécessaires côté JS (app.js/market.js),
    aplati sur la langue courante — évite d'embarquer les deux langues."""
    keys = [
        "phase_ingestion", "phase_features", "phase_scan", "phase_tuning", "phase_export", "phase_done",
        "status_connection_lost", "status_running", "status_error", "status_done",
        "results_title", "results_summary", "results_summary_tuned", "results_best_config",
        "results_leaderboard", "artifact_leaderboard_csv", "artifact_leaderboard_xlsx",
        "artifact_tuned_csv", "artifact_best_model", "artifact_best_model_meta",
        "artifact_best_model_h", "artifact_best_model_meta_h",
        "preview_loading", "preview_no_data", "preview_unavailable", "preview_load_error",
        "news_loading", "news_none", "news_load_error", "movers_no_data",
        "movers_updated_at", "movers_computing",
        "queue_summary", "run_queued_confirm", "run_launch_error", "banner_fix_errors",
        "stat_holdout", "stat_dm_significant", "stat_dm_not_significant",
        "stat_cumulative_trials", "stat_pbo",
        "sim_no_run_selected", "sim_loading", "sim_error", "sim_kelly_disabled",
        "sim_overfitting_guard", "sim_trades_none",
        "sim_metric_cagr", "sim_metric_vol", "sim_metric_sharpe", "sim_metric_sortino",
        "sim_metric_max_dd", "sim_metric_turnover", "sim_metric_hit_rate",
        "sim_metric_profit_factor", "sim_metric_avg_exposure", "sim_metric_break_even",
        "sim_col_strategy", "sim_col_buy_hold",
        "record_unavailable", "record_empty", "record_runs", "record_span",
        "record_scale", "record_counts", "record_unknown", "record_trials",
        "record_no_trials", "record_tap_again", "record_span_range", "record_span_day", "record_hidden",
        "preview_aria_empty", "preview_aria",
        "sim_aria_equity_empty", "sim_aria_drawdown_empty", "sim_aria_dist_empty",
        "sim_aria_equity", "sim_aria_drawdown", "sim_aria_dist",
        "btn_confirm_launch", "btn_cancel", "confirm_line_target", "confirm_line_scheme",
        "confirm_line_combos", "confirm_line_combos_unknown", "confirm_line_queue",
        "confirm_line_gates",
        "gate_data_quality_enabled", "gate_purge", "gate_embargo_enabled",
        "gate_uniqueness_weights", "gate_calibration", "gate_stacking",
        "confirm_line_queue_free",
        "validation_required", "validation_range", "validation_type",
        "adv_state_fields", "adv_state_more", "adv_state_modified",
        "recap_horizons", "recap_targets_count", "movers_not_a_target",
        # feature/ticker-stats-panel (asset_stats.js)
        "assetpanel_loading", "assetpanel_error", "assetpanel_insufficient",
        "assetpanel_load_error", "assetpanel_returns", "assetpanel_long_window",
        "assetpanel_zscore", "assetpanel_ma", "assetpanel_vol",
        "assetpanel_vol_current", "assetpanel_vol_long_run", "assetpanel_bars",
    ]
    t = translator(lang)
    return {k: t(k) for k in keys}


# Translated labels for target groups (DEFAULT_TARGET_GROUPS' internal keys
# stay in French — logic sentinels in config/defaults.py — only the display
# changes).
TARGET_GROUP_LABEL_KEYS = {
    "Indices": "group_indices",
    "ETFs larges & style": "group_broad_etfs",
    "ETFs sectoriels & thématiques": "group_sector_etfs",
    "Obligataire & taux (ETFs)": "group_bonds_etfs",
    "Matières premières & devises (ETFs)": "group_commodities_fx_etfs",
    "Volatilité": "group_volatility",
    "Crypto": "group_crypto",
    "International (ETFs pays)": "group_international_etfs",
    "Actions individuelles": "group_stocks",
    "Macro (FRED)": "group_fred_macro",
}
