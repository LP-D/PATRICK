"""Minimal internationalization (FR/EN) of the web interface — a string
dict + a cookie to remember the choice, no i18n framework: the site is a
local single-user tool, two languages are enough and one more dependency
(Babel, etc.) would add nothing here. STRINGS dict values ("fr"/"en" pairs)
are UI content, not code documentation, and are intentionally left as-is in
both languages.
"""
from __future__ import annotations

from starlette.requests import Request

from patrick.webapp.i18n_analysis import ANALYSIS_JS_KEYS, ANALYSIS_STRINGS
from patrick.webapp.i18n_fund import FUND_JS_KEYS, FUND_STRINGS
from patrick.webapp.i18n_legacy import LEGACY_STRINGS
from patrick.webapp.i18n_models import MODELS_JS_KEYS, MODELS_STRINGS, PAGE_JS_KEYS
from patrick.webapp.i18n_pages import PAGES_JS_KEYS, PAGES_STRINGS
from patrick.webapp.i18n_settings import SETTINGS_JS_KEYS, SETTINGS_STRINGS
from patrick.webapp.i18n_text import TEXT_JS_KEYS, TEXT_STRINGS

LANG_COOKIE = "patrick_lang"
SUPPORTED_LANGS = ("fr", "en")
DEFAULT_LANG = "fr"

STRINGS: dict[str, dict[str, str]] = {
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
    "confirm_line_combos": {"fr": "{n} combinaisons à évaluer par cible.", "en": "{n} scan combinations per target."},
    "confirm_line_staged": {
        "fr": "Dépistage par étapes : les {n} candidats de chaque horizon sont entraînés une fois et notés sur toute la période hors-échantillon ; seuls les {f} meilleur(s) passent au walk-forward complet.",
        "en": "Staged screening: the {n} candidates of each horizon are fitted once and scored on the whole out-of-sample period; only the best {f} go through the full walk-forward.",
    },
    "confirm_line_exhaustive": {
        "fr": "Exploration exhaustive : chaque candidat est évalué sur tous les folds.",
        "en": "Exhaustive exploration: every candidate is evaluated on all folds.",
    },
    "confirm_line_topk": {
        "fr": "Optuna affinera les {k} meilleure(s) configuration(s) de chaque horizon.",
        "en": "Optuna will tune the best {k} configuration(s) of each horizon.",
    },
    "confirm_line_combos_unknown": {"fr": "Nombre de combinaisons non calculable depuis ce formulaire.",
                                    "en": "Combination count not computable from this form."},
    "confirm_line_models": {
        "fr": "Modèles : {models}. Runs cibles en file : {targets}.",
        "en": "Models: {models}. Target runs to queue: {targets}.",
    },
    "confirm_line_tuning": {
        "fr": "Le tuning Optuna est activé et ajoutera des calculs après le scan.",
        "en": "Optuna tuning is enabled and adds work after scanning.",
    },
    "confirm_line_tuning_off": {"fr": "Le tuning Optuna est désactivé.", "en": "Optuna tuning is disabled."},
    "confirm_line_large": {
        "fr": "Espace de recherche important : vérifie si toutes les grilles et tous les modèles sont utiles.",
        "en": "Large search space: consider whether every selected grid/model is needed.",
    },
    "confirm_line_queue": {"fr": "{n} run(s) déjà en file : celui-ci démarrera après.",
                           "en": "{n} run(s) already queued: this one starts after them."},
    "confirm_line_queue_free": {"fr": "Aucun run en file : celui-ci démarre immédiatement.",
                                "en": "Nothing queued: this one starts immediately."},
    "glossary_open_aria": {"fr": "Définition : {term}", "en": "Definition: {term}"},
    "glossary_search_label": {"fr": "Rechercher dans le glossaire", "en": "Search glossary"},
    "glossary_search_placeholder": {"fr": "Terme ou définition", "en": "Term or definition"},
    "glossary_search_results": {"fr": "Résultats du glossaire", "en": "Glossary search results"},
    "glossary_search_count": {"fr": "{count} résultat(s)", "en": "{count} result(s)"},
    "glossary_search_empty": {"fr": "Aucun terme correspondant.", "en": "No matching terms."},
    "validation_required": {"fr": "Ce champ est obligatoire.", "en": "This field is required."},
    "validation_range": {"fr": "Valeur hors des bornes autorisées.", "en": "Value outside the allowed range."},
    "validation_type": {"fr": "Format attendu non respecté.", "en": "Expected format not matched."},

    "section_progress": {"fr": "Avancement", "en": "Progress"},
    "section_recent": {"fr": "Derniers runs", "en": "Recent runs"},
    "section_stock": {"fr": "Aperçu marché — cible choisie", "en": "Market overview — chosen target"},
    "no_run_yet": {"fr": "Aucun run pour l'instant — configure et lance à gauche.",
                   "en": "No run yet — configure and launch on the left."},
    "queue_summary": {"fr": "{n} run(s) en attente · prochain : {next}",
                      "en": "{n} run(s) queued · next: {next}"},
    "queue_clear": {"fr": "Vider la file", "en": "Clear queue"},
    "queue_remove": {"fr": "Supprimer", "en": "Remove"},
    "queue_move_top": {"fr": "Placer en tête", "en": "Move to top"},
    "queue_move_up": {"fr": "Monter", "en": "Move up"},
    "queue_move_down": {"fr": "Descendre", "en": "Move down"},
    "queue_drag": {"fr": "Glisser pour changer l'ordre d'exécution", "en": "Drag to change the execution order"},
    "run_pause": {"fr": "Mettre en pause", "en": "Pause"},
    "run_resume": {"fr": "Reprendre", "en": "Resume"},
    "run_stop": {"fr": "Arrêter le run", "en": "Stop run"},
    "run_paused": {"fr": "En pause — reprise possible à tout moment.", "en": "Paused — resume any time."},
    "run_control_error": {"fr": "Impossible d'appliquer cette action.", "en": "Could not apply this action."},
    "run_queued_confirm": {"fr": "Run « {name} » mis en file d'attente (position {position}).",
                            "en": "Run “{name}” queued (position {position})."},
    "run_launch_error": {"fr": "Erreur lors du lancement.", "en": "Error launching the run."},

    "movers_title": {"fr": "Plus fortes variations (5 jours)", "en": "Biggest movers (5 days)"},
    "movers_updated_at": {"fr": "Mis à jour à {time}", "en": "Updated at {time}"},
    "log_raw_title": {"fr": "Journal technique", "en": "Technical log"},

    "section_run": {"fr": "Run", "en": "Run"},
    "settings_mode_simple_title": {"fr": "Réglages essentiels", "en": "Essential settings"},
    "settings_mode_simple_hint": {
        "fr": "Les réglages avancés sont masqués ; leurs valeurs actuelles restent conservées.",
        "en": "Advanced controls are hidden; their current values are preserved.",
    },
    "settings_mode_expert_hint": {
        "fr": "Toutes les options d’exploration sont disponibles ci-dessous.",
        "en": "All exploratory options are available below.",
    },
    "settings_mode_show_expert": {"fr": "Afficher les réglages avancés", "en": "Show advanced settings"},
    "settings_mode_hide_expert": {"fr": "Masquer les réglages avancés", "en": "Hide advanced settings"},
    "field_run_name": {"fr": "Nom du run (généré automatiquement)", "en": "Run name (auto-generated)"},
    "profile_name": {"fr": "Nom du profil", "en": "Profile name"},
    "profile_save": {"fr": "Enregistrer le profil", "en": "Save profile"},
    "profile_saved": {"fr": "Profils enregistrés", "en": "Saved profiles"},
    "profile_choose": {"fr": "Choisir un profil", "en": "Choose a profile"},
    "profile_load": {"fr": "Charger", "en": "Load"},
    "profile_delete": {"fr": "Supprimer", "en": "Delete"},
    "profile_name_required": {"fr": "Saisis un nom pour ce profil.", "en": "Enter a name for this profile."},
    "profile_saved_notice": {"fr": "Profil enregistré dans ce navigateur.", "en": "Profile saved in this browser."},
    "profile_loaded": {"fr": "Profil chargé. Vérifie les réglages avant le lancement.", "en": "Profile loaded. Review it before launching."},
    "profile_deleted": {"fr": "Profil supprimé.", "en": "Profile deleted."},
    "profile_read_error": {"fr": "Impossible de lire les profils enregistrés.", "en": "Saved profiles could not be read."},
    "profile_save_error": {"fr": "Impossible d'enregistrer le profil dans ce navigateur.", "en": "The profile could not be saved in this browser."},
    "profile_delete_error": {"fr": "Impossible de supprimer le profil.", "en": "The profile could not be deleted."},
    "profile_missing": {"fr": "Choisis un profil encore disponible.", "en": "Select a profile that still exists."},
    "duplicate_run_loaded": {
        "fr": "Configuration de {run_id} chargée comme base : ajuste les réglages puis lance un nouveau run.",
        "en": "Configuration from {run_id} loaded as a starting point: adjust settings and launch a new run.",
    },
    "compare_runs_selection": {
        "fr": "{count} sélectionné(s). Choisis 2 à 4 runs terminés.",
        "en": "{count} selected. Choose 2 to 4 completed runs.",
    },

    "section_objective": {"fr": "Objectif — que prédire ?", "en": "Objective — what to predict?"},
    "field_target": {"fr": "Cible(s)", "en": "Target(s)"},
    "field_target_kind": {"fr": "Type de cible", "en": "Target type"},
    "target_kind_raw": {"fr": "Rendement brut de la cible", "en": "Raw return of the target"},
    "target_kind_alpha": {"fr": "Alpha : rendement excédentaire vs benchmark", "en": "Alpha: excess return vs benchmark"},
    "target_kind_hint": {
        "fr": "Alpha : le modèle prédit si la cible fait mieux ou moins bien que son benchmark (rendement − β × benchmark, β estimé sans regarder le futur). Le taux de hausse de base est proche de 0,5 au lieu de dépendre du marché. Les runs alpha ont leur propre historique, champion et registre d'essais.",
        "en": "Alpha: the model predicts whether the target beats or lags its benchmark (return − β × benchmark, β estimated without looking ahead). The base up-rate is close to 0.5 instead of following the market. Alpha runs have their own history, champion and trial registry.",
    },
    "field_benchmark": {"fr": "Benchmark", "en": "Benchmark"},
    "benchmark_auto_placeholder": {"fr": "vide = déterminé automatiquement", "en": "empty = chosen automatically"},
    "benchmark_hint": {
        "fr": "Laisser vide pour un benchmark choisi d'après la classe d'actif et la région (action US → ^GSPC, zone euro → ^STOXX50E, crypto → BTC-USD...), ou saisir un ticker Yahoo. Un seul benchmark saisi s'applique à toutes les cibles sélectionnées.",
        "en": "Leave empty for a benchmark chosen from the asset class and region (US stock → ^GSPC, euro area → ^STOXX50E, crypto → BTC-USD...), or type a Yahoo ticker. A typed benchmark applies to every selected target.",
    },
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
    "field_start_date": {"fr": "Date de début", "en": "Start date"},
    "field_yf_coverage": {"fr": "Couverture minimale yfinance (0-1)", "en": "Minimum yfinance coverage (0-1)"},
    "field_universe_scope": {"fr": "Univers candidat", "en": "Candidate universe"},
    "universe_scope_default": {"fr": "Standard (univers par défaut)", "en": "Standard (default universe)"},
    "universe_scope_extended": {"fr": "Étendu (+ indices, taux, FX, ETF sectoriels/obligataires…)",
                                "en": "Extended (+ indices, rates, FX, sector/bond ETFs…)"},
    "field_reduction_corr_threshold": {
        "fr": "Seuil de réduction |corr| (vide = désactivé)",
        "en": "Reduction |corr| threshold (empty = disabled)"},

    "section_data_quality": {"fr": "Qualité de données (portes à l'ingestion)",
                              "en": "Data quality (ingestion gates)"},
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

    # Phase 3 (feature/hyperparams-lookbacks): rolling-window lookbacks for
    # `features/technical.py`, previously fixed function defaults with no
    # configuration surface at all.
    "section_technical_lookbacks": {"fr": "Lookbacks technical (fenêtres roulantes)",
                                     "en": "Technical lookbacks (rolling windows)"},

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
    # flexibility-gaps Gap 7: validation.holdout_months, YAML-only until now.
    "field_holdout_months": {"fr": "Holdout terminal (mois, 12-24)", "en": "Terminal holdout (months, 12-24)"},
    "field_purge": {"fr": "Purge (retire les lignes proches de la frontière train/test)",
                     "en": "Purge (removes rows near the train/test boundary)"},
    "field_embargo_enabled": {"fr": "Embargo (retire les premières lignes de test après la coupure)",
                               "en": "Embargo (removes the first test rows after the cut)"},
    "field_embargo_bars": {"fr": "Barres d'embargo (vide = horizon)",
                            "en": "Embargo bars (blank = horizon)"},
    # CHANTIER A (feature/regime-detection-hmm)
    "field_regime_detection_enabled": {"fr": "Détection de régime (HMM)", "en": "Regime detection (HMM)"},
    "field_regime_threshold_mode": {"fr": "Mode de seuillage du régime", "en": "Regime threshold mode"},
    "regime_threshold_mode_quantile": {"fr": "Quantile (relatif à l'historique)", "en": "Quantile (relative to history)"},
    "regime_threshold_mode_fixed": {"fr": "Valeur fixe (absolue)", "en": "Fixed value (absolute)"},
    "field_regime_threshold_lo": {"fr": "Seuil bas (calme / normal)", "en": "Low threshold (calm / normal)"},
    "field_regime_threshold_hi": {"fr": "Seuil haut (normal / stress)", "en": "High threshold (normal / stress)"},

    "section_selection": {"fr": "Sélection de features", "en": "Feature selection"},
    "field_method": {"fr": "Méthode", "en": "Method"},
    "field_n_features_grid": {"fr": "Grille N (séparée par des virgules, ex. 5,6,7,8 ou 5-15)",
                               "en": "N grid (comma-separated, e.g. 5,6,7,8 or 5-15)"},
    "field_shap_sample": {"fr": "Échantillon SHAP", "en": "SHAP sample"},
    "field_track_stability": {"fr": "Suivre la stabilité de la sélection (Jaccard entre folds)",
                               "en": "Track selection stability (Jaccard across folds)"},
    "field_staged_screening": {"fr": "Présélection progressive (fenêtre totale, puis walk-forward du meilleur)",
                               "en": "Staged screening (total window, then walk-forward of the best)"},
    "field_screening_finalists": {"fr": "Finalistes par horizon et régime", "en": "Finalists per horizon and regime"},

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

    # Phase 1 (feature/hyperparams-ui): search-space bounds per algo/hyperparameter,
    # previously fixed in code with no configuration surface at all.
    "section_optuna_bounds": {"fr": "Bornes de recherche Optuna", "en": "Optuna search bounds"},
    "optuna_bound_low": {"fr": "min", "en": "min"},
    "optuna_bound_high": {"fr": "max", "en": "max"},

    "section_output": {"fr": "Sortie", "en": "Output"},
    "field_output_dir": {"fr": "Dossier de sortie", "en": "Output directory"},
    "field_seed": {"fr": "Seed", "en": "Seed"},

    "btn_launch_run": {"fr": "Lancer le run", "en": "Launch run"},
    "section_performance": {"fr": "Performance (cette machine)", "en": "Performance (this machine)"},
    "field_parametric_jobs": {"fr": "Workers du pool paramétrique", "en": "Parametric pool workers"},
    "hint_parametric_jobs": {
        "fr": "1 = séquentiel (comportement d'origine). Plus de workers accélère la construction des features "
              "paramétriques sans changer les résultats. Le nombre réel est plafonné selon CPU et mémoire disponible. "
              "S'applique aux prochains runs.",
        "en": "1 = sequential (original behaviour). More workers speed up parametric feature building without "
              "changing results. The effective count is capped by CPU and available memory. Applies to the next runs."},
    "field_scan_jobs": {"fr": "Workers de calcul des modèles (sélection + entraînements)",
                        "en": "Model compute workers (selection + training)"},
    "hint_scan_jobs": {
        "fr": "1 = séquentiel. Plus de workers entraîne plusieurs modèles en parallèle (un cœur chacun) sans changer "
              "les résultats. Le nombre réel est plafonné selon CPU et mémoire disponible. S'applique aux prochains runs.",
        "en": "1 = sequential. More workers train several models in parallel (one core each) without changing results, "
              "with the effective count capped by CPU and available memory. Applies to the next runs."},
    "btn_save_setting": {"fr": "Enregistrer", "en": "Save"},
    "setting_saved": {"fr": "Enregistré.", "en": "Saved."},
    "setting_env_override": {"fr": "Une variable d'environnement (PATRICK_PARAMETRIC_JOBS / PATRICK_SCAN_JOBS) est définie et prime sur ce réglage.",
                             "en": "An environment variable (PATRICK_PARAMETRIC_JOBS / PATRICK_SCAN_JOBS) is set and overrides this setting."},

    # app.js (injected via window.I18N)
    "phase_ingestion": {"fr": "Téléchargement des données", "en": "Downloading data"},
    "phase_features": {"fr": "Construction des variables explicatives", "en": "Building explanatory variables"},
    "phase_scan": {"fr": "Test des combinaisons (variables × rééquilibrage × algorithme)",
                   "en": "Testing combinations (variables × rebalancing × algorithm)"},
    "phase_tuning": {"fr": "Réglage fin des meilleures configurations", "en": "Fine-tuning the best configurations"},
    "phase_export": {"fr": "Sauvegarde du modèle final", "en": "Saving the final model"},
    "phase_done": {"fr": "Terminé.", "en": "Done."},
    "phase_other": {"fr": "Calcul en cours", "en": "Computing"},
    "status_connection_lost": {"fr": "Connexion au serveur perdue — nouvelle tentative…",
                                "en": "Connection to server lost — retrying…"},
    "status_progress_units": {"fr": "{done} évaluations sur {total}", "en": "{done} of {total} evaluations"},
    "status_running": {"fr": "{phase} — {pct} % · écoulé : {elapsed}", "en": "{phase} — {pct}% · elapsed: {elapsed}"},
    "status_running_progress": {
        "fr": "{phase} — {pct} % ({progress}) · écoulé : {elapsed}",
        "en": "{phase} — {pct}% ({progress}) · elapsed: {elapsed}",
    },
    "status_running_eta": {
        "fr": "{phase} — {pct} % ({progress}) · écoulé : {elapsed} · reste environ {remaining} (estimation {confidence})",
        "en": "{phase} — {pct}% ({progress}) · elapsed: {elapsed} · about {remaining} left ({confidence} estimate)",
    },
    "duration_s": {"fr": "{s} s", "en": "{s}s"},
    "duration_min": {"fr": "{m} min {s} s", "en": "{m} min {s}s"},
    "duration_h": {"fr": "{h} h {m} min", "en": "{h} h {m} min"},
    "eta_confidence_low": {"fr": "préliminaire", "en": "preliminary"},
    "eta_confidence_moderate": {"fr": "approximative", "en": "rough"},
    "status_progress_stalled": {
        "fr": "Aucune nouvelle évaluation depuis 10 min : consulte le journal technique. Un calcul long peut être normal.",
        "en": "No new evaluation for 10 minutes; check the technical log. A long computation may be normal.",
    },
    "status_error": {"fr": "Erreur : {error}", "en": "Error: {error}"},
    "status_done": {"fr": "Terminé en {elapsed}.", "en": "Done in {elapsed}."},
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

    # target group category names (optgroups)
    "group_indices": {"fr": "Indices", "en": "Indices"},
    "group_currencies": {"fr": "Devises", "en": "Currencies"},
    "group_commodities_futures": {"fr": "Matières premières (futures)", "en": "Commodities (futures)"},
    "group_broad_etfs": {"fr": "ETFs larges & style", "en": "Broad & style ETFs"},
    "group_sector_etfs": {"fr": "ETFs sectoriels & thématiques", "en": "Sector & thematic ETFs"},
    "group_bonds_etfs": {"fr": "Obligataire & taux (ETFs)", "en": "Bonds & rates (ETFs)"},
    "group_commodities_fx_etfs": {"fr": "Matières premières & devises (ETFs)", "en": "Commodities & FX (ETFs)"},
    "group_volatility": {"fr": "Volatilité", "en": "Volatility"},
    "group_crypto": {"fr": "Crypto", "en": "Crypto"},
    "group_international_etfs": {"fr": "International (ETFs pays)", "en": "International (country ETFs)"},
    "group_stocks": {"fr": "Actions individuelles", "en": "Individual stocks"},
    "group_fred_macro": {"fr": "Macro (FRED)", "en": "Macro (FRED)"},
    "group_world_indices": {"fr": "Indices mondiaux", "en": "World indices"},
    "group_us_megacaps": {"fr": "Actions US (méga-capitalisations)", "en": "US stocks (mega caps)"},
    "group_fr_cac40": {"fr": "Actions France (CAC 40)", "en": "French stocks (CAC 40)"},
    "group_fx_majors": {"fr": "Devises (majeures)", "en": "Currencies (majors)"},
    "group_crypto_majors": {"fr": "Crypto (majeures)", "en": "Crypto (majors)"},
    "group_us_rates_indices": {"fr": "Taux US (indices CBOE)", "en": "US rates (CBOE indices)"},
    "group_us_rates_futures": {"fr": "Taux US (futures)", "en": "US rates (futures)"},
    "group_commodities_extra": {"fr": "Matières premières (compléments)", "en": "Commodities (additional)"},
    "group_us_largecaps": {"fr": "Actions US (grandes capitalisations)", "en": "US stocks (large caps)"},
    "group_fr_other": {"fr": "Actions France (autres valeurs)", "en": "French stocks (other)"},
    "group_germany_stocks": {"fr": "Actions Allemagne", "en": "German stocks"},
    "group_uk_stocks": {"fr": "Actions Royaume-Uni", "en": "UK stocks"},
    "group_eu_other_stocks": {"fr": "Actions Europe (autres pays)", "en": "European stocks (other countries)"},
    "group_asia_stocks": {"fr": "Actions Asie (locales & ADR)", "en": "Asian stocks (local & ADRs)"},

    # Phase 7 — history/universe
    # P8: "/" became the synthesis dashboard, the launcher moved to
    # "/launch" -- nav_home now names the SYNTHESIS page (still the site's
    # "/" landing point, hence reused by every breadcrumb's first link),
    # nav_launch is the new, separate entry for the launcher.
    "nav_home": {"fr": "Synthèse", "en": "Overview"},
    # feature/nav-categories-registry -- en-tetes de section de la sidebar
    # (webapp/nav_registry.py::CATEGORIES), deja en capitales.
    "nav_cat_pilotage": {"fr": "PILOTAGE", "en": "CONTROL"},
    "nav_cat_classes_actifs": {"fr": "CLASSES D'ACTIFS", "en": "ASSET CLASSES"},
    "nav_cat_simulation": {"fr": "SIMULATION", "en": "SIMULATION"},
    "nav_cat_patrimoine": {"fr": "PATRIMOINE", "en": "WEALTH"},
    "nav_launch": {"fr": "Lancer", "en": "Launch"},
    # Design system v3 shell (base_v2.html / static/shell.js).
    "skip_to_content": {"fr": "Aller au contenu", "en": "Skip to content"},
    "brand_tagline": {"fr": "Station de recherche quantitative", "en": "Quant research station"},
    "sidebar_toggle": {"fr": "Réduire / déplier la navigation", "en": "Collapse / expand navigation"},
    "nav_open": {"fr": "Ouvrir la navigation", "en": "Open navigation"},
    "theme_toggle": {"fr": "Basculer thème clair / sombre", "en": "Toggle light / dark theme"},
    "cmdk_title": {"fr": "Navigation rapide", "en": "Quick navigation"},
    # Boîte de confirmation partagée (base_v2.html / static/confirm.js) : remplace window.confirm.
    "confirm_title": {"fr": "Confirmation", "en": "Confirmation"},
    "confirm_cancel": {"fr": "Annuler", "en": "Cancel"},
    "confirm_ok": {"fr": "Confirmer", "en": "Confirm"},
    "cmdk_placeholder": {"fr": "Rechercher une page…", "en": "Search pages…"},
    "cmdk_move": {"fr": "naviguer", "en": "move"},
    "cmdk_open": {"fr": "ouvrir", "en": "open"},
    "cmdk_empty": {"fr": "Aucun résultat", "en": "No results"},
    "nav_runs": {"fr": "Historique", "en": "History"},
    "nav_universe": {"fr": "Univers", "en": "Universe"},
    "nav_data_freshness": {"fr": "Fraîcheur", "en": "Freshness"},
    # feature/ticker-stats-panel
    "nav_commodities": {"fr": "Matières premières", "en": "Commodities"},
    "nav_macro": {"fr": "Macro (FRED)", "en": "Macro (FRED)"},
    # /macro page: sections by domain, most important first
    "macro_sections_hint": {
        "fr": "Triées par importance : les indicateurs clés d'abord, puis chaque domaine. Les séries marquées « entraînement » nourrissent les modèles mais ne sont jamais des cibles.",
        "en": "Sorted by importance: key indicators first, then each domain. Series tagged “training” feed the models but are never targets.",
    },
    "macro_training_only": {"fr": "entraînement", "en": "training"},
    "macro_section_key": {"fr": "Indicateurs clés", "en": "Key indicators"},
    "macro_section_growth": {"fr": "Croissance et activité", "en": "Growth and activity"},
    "macro_section_labor": {"fr": "Emploi", "en": "Labor market"},
    "macro_section_inflation": {"fr": "Inflation et prix", "en": "Inflation and prices"},
    "macro_section_policy": {"fr": "Politique monétaire et taux courts", "en": "Monetary policy and short rates"},
    "macro_section_curve": {"fr": "Courbe des taux", "en": "Yield curve"},
    "macro_section_credit": {"fr": "Crédit et stress financier", "en": "Credit and financial stress"},
    "macro_section_consumption": {"fr": "Consommation et revenus", "en": "Consumption and income"},
    "macro_section_housing": {"fr": "Immobilier", "en": "Housing"},
    "macro_section_liquidity": {"fr": "Liquidité et monnaie", "en": "Liquidity and money"},
    "macro_section_markets": {"fr": "Marchés actions et volatilité", "en": "Equity markets and volatility"},
    "macro_section_commodities": {"fr": "Énergie et matières premières", "en": "Energy and commodities"},
    "macro_section_international": {"fr": "International : devises et taux étrangers",
                                    "en": "International: currencies and foreign yields"},
    "nav_equities": {"fr": "Actions individuelles", "en": "Individual stocks"},
    "group_fred_training": {"fr": "Séries FRED d'entraînement", "en": "FRED training series"},
    "nav_predictions": {"fr": "Prédictions", "en": "Predictions"},
    # Phase 8 (feature/portfolio-view)
    "nav_portfolio": {"fr": "Portefeuille", "en": "Portfolio"},
    # Roadmap bloc 4 -- PATRIMOINE
    "nav_patrimoine": {"fr": "Comptes", "en": "Accounts"},
    "nav_mouvements": {"fr": "Mouvements", "en": "Movements"},
    "nav_patrimoine_simulation": {"fr": "Simulateur patrimoine", "en": "Wealth simulator"},
    "wealth_title": {"fr": "Patrimoine", "en": "Wealth"},
    "wealth_new_account": {"fr": "Nouveau compte", "en": "New account"},
    "wealth_mode_real": {"fr": "Réel", "en": "Real"},
    "wealth_mode_fictive": {"fr": "Fictif", "en": "Fictive"},
    "wealth_drop_csv": {"fr": "Dépose un relevé CSV ici, ou clique pour choisir un fichier", "en": "Drop a CSV statement here, or click to choose a file"},
    "wealth_import_preview": {"fr": "{n} mouvement(s) valide(s), {e} ligne(s) en erreur — rien n'est enregistré avant confirmation.", "en": "{n} valid movement(s), {e} line(s) in error — nothing is saved before confirmation."},
    "wealth_import_done": {"fr": "{n} mouvement(s) enregistré(s).", "en": "{n} movement(s) saved."},
    "wealth_transfer_moved": {"fr": "Mouvement déplacé.", "en": "Movement moved."},
    "wealth_transfer_copied": {"fr": "Mouvement copié dans le compte fictif.", "en": "Movement copied into the fictive account."},
    "portfolio_signals_title": {"fr": "Signaux par catégorie", "en": "Signals by category"},
    "portfolio_contradictions_title": {"fr": "Signaux contradictoires", "en": "Contradictory signals"},
    "portfolio_no_contradiction": {
        "fr": "Aucune contradiction détectée pour l'instant sur les paires suivies.",
        "en": "No contradiction detected so far on the tracked pairs.",
    },
    # flexibility-gaps Gap 6: /portfolio's ?pairs= override form.
    "portfolio_pairs_label": {
        "fr": "Paires corrélées (une par ligne, symbol_a:symbol_b:sens)",
        "en": "Correlated pairs (one per line, symbol_a:symbol_b:sens)",
    },
    "portfolio_pairs_apply": {"fr": "Appliquer", "en": "Apply"},
    "assetpanel_help_label": {"fr": "Statistiques par actif", "en": "Per-asset statistics"},
    "assetpanel_bars_help_label": {"fr": "Fenêtres de calcul", "en": "Calculation windows"},
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
    "assetpanel_vol_current": {"fr": "courante (20 barres)", "en": "current (20 bars)"},
    "assetpanel_vol_long_run": {"fr": "long terme (~252 barres)", "en": "long-run (~252 bars)"},

    # "Observation station" world — chrome: theme toggle and activity
    # record strip. The theme button names the current STATE, not the
    # action (it's an indicator with a dot): "Day" = currently in light mode.
    # The station's verdict. "What holds" is not colored --ok: the product's
    # stance is that a clearly established "no" is a successful result, so
    # zero survivors is not a bad state.
    "verdict_survivors": {"fr": "Signaux qui tiennent", "en": "Signals that hold"},
    "verdict_survivors_rel": {"fr": "cibles dont le signal survit à la correction entre cibles (BH, α={alpha})",
                              "en": "targets whose signal survives the across-target correction (BH, α={alpha})"},
    "verdict_not_computable": {"fr": "aucune cible n'a encore de résultat Diebold-Mariano",
                               "en": "no target has a Diebold-Mariano result yet"},
    "verdict_cost": {"fr": "Coût en essais", "en": "Trial cost"},
    "verdict_cost_rel": {"fr": "essais cumulés sur {runs} run(s), {targets} cible(s)",
                         "en": "cumulative trials over {runs} run(s), {targets} target(s)"},

    # Local-scope lines: each dense surface answers ITS OWN question,
    # without repeating the global verdict the banner already carries.
    "scope_runs": {"fr": "RUNS COMPARÉS AUX BASELINES", "en": "RUNS COMPARED TO BASELINES"},
    "scope_runs_rel": {"fr": "runs affichés ayant produit un résultat Diebold-Mariano",
                       "en": "listed runs that produced a Diebold-Mariano result"},


    # Text equivalents for the canvases. A chart with no replacement text
    # does not exist for a screen reader; these labels are rewritten by
    # `market.js` / `simulate.js` with the real bounds once plotted.
    "preview_aria_empty": {"fr": "Cours de la cible — aucune donnée tracée pour l'instant.",
                           "en": "Target price history — nothing plotted yet."},
    "preview_aria": {"fr": "Cours de {symbol} sur {period} : {n} points, du plus bas {min} au plus haut {max}, dernier point {last}.",
                     "en": "{symbol} price over {period}: {n} points, low {min} to high {max}, last {last}."},

    # Phase 4 — investment simulator
    "nav_simulate": {"fr": "Simulateur", "en": "Simulator"},
    # Ex-"Kelly fractionnaire" : l'API n'accepte plus que `heuristic_leverage`
    # (ce n'est pas la formule de Kelly, cf. simulate/engine.py).
    # Simulator empty states at rest. Without them, `/simulate` opens on
    # three blank plotting panels and two header-only tables: the product's
    # least dense surface read as broken rather than waiting.

    # Phase 5 — exploratory surfaces (explorer, history, details)
    # Shared columns
    "col_run": {"fr": "Run", "en": "Run"},
    "col_target": {"fr": "Cible", "en": "Target"},
    "col_horizon": {"fr": "Horizon", "en": "Horizon"},
    "col_scheme": {"fr": "Schéma", "en": "Scheme"},
    "col_status": {"fr": "Statut", "en": "Status"},
    "col_trials": {"fr": "Essais", "en": "Trials"},
    "col_dm_p": {"fr": "p-value DM", "en": "DM p-value"},

    # Shared helpers
    "h_horizon_unit": {"fr": "{h}j", "en": "{h}d"},

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
    "tg_empty": {"fr": "Aucun run pour cette cible.", "en": "No runs for this target."},

    # Run detail (rd_*)
    "rd_ctx_target": {"fr": "cible", "en": "target"},
    "rd_horizon": {"fr": "horizon", "en": "horizon"},
    "rd_sections": {"fr": "Sections", "en": "Sections"},
    "rd_sections_aria": {"fr": "Sections de la page", "en": "Page sections"},
    "rd_section_summary": {"fr": "Résumé", "en": "Summary"},
    "rd_section_trials": {"fr": "Essais", "en": "Trials"},
    "rd_section_config": {"fr": "Configuration", "en": "Configuration"},

    # Scope lines (shared)
    "scope_universe": {"fr": "Portée de l'univers", "en": "Universe scope"},
    "scope_universe_rel": {"fr": "{done} avec un run complètement exécuté, {never} jamais lancée(s)", "en": "{done} with a completed run, {never} never launched"},
    # Phase 5: improved empty states for hardening
    "empty_runs_hint": {"fr": "Configure et lance un run depuis la page", "en": "Configure and launch a run from the page"},

    # Phase 7 -- SHAP waterfall (feature/shap-waterfall), /targets/{ticker}
    "shap_section_title": {"fr": "Explication de la dernière prédiction (SHAP)",
                           "en": "Explaining the most recent prediction (SHAP)"},
    "shap_section_hint": {
        "fr": ("Décompose la prédiction la plus récemment enregistrée pour un horizon donné, feature par "
               "feature, via SHAP (contribution de chaque feature à la prédiction d'un modèle déjà entraîné — "
               "voir glossaire). Calculé à la demande sur le modèle réellement exporté, jamais sur celui, "
               "jetable, utilisé pendant la sélection de features."),
        "en": ("Breaks down the most recently recorded prediction for a given horizon, feature by feature, "
               "via SHAP (each feature's contribution to an already-trained model's prediction — see "
               "glossary). Computed on demand on the actually exported model, never on the throwaway one "
               "used during feature selection."),
    },
    "shap_select_horizon": {"fr": "Horizon :", "en": "Horizon:"},
    "shap_btn_generate": {"fr": "Générer l'explication", "en": "Generate explanation"},
    "shap_no_model": {"fr": "Aucun run terminé pour cette cible — pas de modèle exporté à expliquer.",
                      "en": "No completed run for this target — no exported model to explain."},
    "shap_loading": {"fr": "Calcul en cours…", "en": "Computing…"},
    "shap_load_error": {"fr": "Erreur de chargement.", "en": "Loading error."},
    "shap_unavailable": {"fr": "Aucune explication disponible pour cet horizon.",
                         "en": "No explanation available for this horizon."},
    "shap_caption": {
        "fr": "{date} · prédiction : {label} (confiance {proba}) · {n} features · échantillon {split}",
        "en": "{date} · predicted: {label} (confidence {proba}) · {n} features · {split} sample",
    },
    "shap_units_hint": {
        "fr": ("Les barres représentent le score brut du modèle par classe (pas une probabilité) : la "
               "garantie d'additivité de SHAP tient dans cet espace pour un ensemble d'arbres multiclasse, "
               "pas après la fonction softmax."),
        "en": ("Bars are the model's raw per-class score (not a probability): SHAP's additive guarantee "
               "holds in that space for a multiclass tree ensemble, not after the softmax."),
    },
    "shap_units_hint_probability": {
        "fr": ("Les barres sont les contributions à la probabilité de la classe prédite (modèle neuronal) : valeurs de Shapley estimées, "
               "par rapport à la ligne moyenne de l'entraînement."),
        "en": ("Bars are contributions to the probability of the predicted class (neural model): estimated Shapley values against the "
               "average training row."),
    },
    "shap_class_0": {"fr": "Forte baisse", "en": "Strong down"},
    "shap_class_1": {"fr": "Légère baisse", "en": "Slight down"},
    "shap_class_2": {"fr": "Légère hausse", "en": "Slight up"},
    "shap_class_3": {"fr": "Forte hausse", "en": "Strong up"},
}


# Pages Simulation et Fonds (webapp/i18n_fund.py) ; leurs chaînes écrasent la clé homonyme nav_simulate.
STRINGS.update(FUND_STRINGS)
# Page Réglages (webapp/i18n_settings.py).
STRINGS.update(SETTINGS_STRINGS)
# Pages de la refonte du 2026-10-09 (webapp/i18n_pages.py).
STRINGS.update(PAGES_STRINGS)
# Gabarits historiques convertis (webapp/i18n_legacy.py).
STRINGS.update(LEGACY_STRINGS)
# Pages Modèles (ML, DL, RL) et Exploration (webapp/i18n_models.py).
STRINGS.update(MODELS_STRINGS)
# Black-Litterman de /portfolio et page /news (webapp/i18n_text.py).
STRINGS.update(TEXT_STRINGS)
# Pages d'analyse des entraînements (webapp/i18n_analysis.py).
STRINGS.update(ANALYSIS_STRINGS)


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


def js_strings(lang: str, path: str = "") -> dict[str, str]:
    """Sous-ensemble des chaînes nécessaires côté JS (app.js/market.js),
    aplati sur la langue courante — évite d'embarquer les deux langues."""
    keys = [
        "cmdk_empty", *FUND_JS_KEYS, *SETTINGS_JS_KEYS, *PAGES_JS_KEYS, *MODELS_JS_KEYS, "wealth_import_preview", "wealth_import_done", "wealth_transfer_moved", "wealth_transfer_copied",
        "phase_ingestion", "phase_features", "phase_scan", "phase_tuning", "phase_export", "phase_done", "phase_other",
        "status_connection_lost", "status_running", "status_progress_units", "status_running_progress",
        "status_running_eta", "eta_confidence_low", "eta_confidence_moderate", "status_progress_stalled",
        "status_error", "status_done", "duration_s", "duration_min", "duration_h",
        "settings_mode_show_expert", "settings_mode_hide_expert", "settings_mode_simple_hint", "settings_mode_expert_hint",
        "profile_choose", "profile_name_required", "profile_saved_notice", "profile_loaded",
        "profile_deleted", "profile_read_error", "profile_save_error", "profile_delete_error", "profile_missing",
        "compare_runs_selection",
        "glossary_search_count", "glossary_search_empty", "glossary_open_aria",
        "confirm_line_combos", "confirm_line_combos_unknown", "confirm_line_models",
        "confirm_line_staged", "confirm_line_exhaustive", "confirm_line_topk",
        "confirm_line_tuning", "confirm_line_tuning_off", "confirm_line_large",
        "results_title", "results_summary", "results_summary_tuned", "results_best_config",
        "results_leaderboard", "artifact_leaderboard_csv", "artifact_leaderboard_xlsx",
        "artifact_tuned_csv", "artifact_best_model", "artifact_best_model_meta",
        "artifact_best_model_h", "artifact_best_model_meta_h",
        "preview_loading", "preview_no_data", "preview_unavailable", "preview_load_error",
        "news_loading", "news_none", "news_load_error",
        "movers_updated_at",
        "queue_summary", "run_queued_confirm", "run_launch_error", "banner_fix_errors",
        "queue_clear", "queue_remove", "queue_move_top", "queue_move_up", "queue_move_down", "queue_drag",
        "run_pause", "run_resume", "run_stop", "run_paused", "run_control_error",
        "stat_holdout", "stat_dm_significant", "stat_dm_not_significant",
        "stat_cumulative_trials", "stat_pbo",
        "preview_aria_empty", "preview_aria",
        "btn_confirm_launch", "btn_cancel", "confirm_line_target", "confirm_line_scheme",
        "confirm_line_combos", "confirm_line_combos_unknown", "confirm_line_queue",
        "confirm_line_gates",
        "gate_data_quality_enabled", "gate_purge", "gate_embargo_enabled",
        "gate_uniqueness_weights", "gate_calibration", "gate_stacking",
        "confirm_line_queue_free",
        "validation_required", "validation_range", "validation_type",
        "adv_state_fields", "adv_state_more", "adv_state_modified",
        "recap_horizons", "recap_targets_count",
        # feature/ticker-stats-panel (asset_stats.js)
        "assetpanel_error", "assetpanel_insufficient",
        "assetpanel_load_error", "assetpanel_returns", "assetpanel_long_window",
        "assetpanel_zscore", "assetpanel_ma", "assetpanel_vol_current", "assetpanel_vol_long_run", # feature/shap-waterfall (shap_waterfall.js)
        "shap_loading", "shap_load_error", "shap_unavailable", "shap_caption",
        "shap_units_hint", "shap_units_hint_probability", "shap_class_0", "shap_class_1", "shap_class_2", "shap_class_3",
    ]
    keys = [*keys, *PAGE_JS_KEYS.get(path, ()), *(TEXT_JS_KEYS if path == "/news" else ())]
    if path.startswith(("/analyses", "/garde-fous", "/variables", "/derive", "/modeles", "/journal", "/carnet", "/diagnostics", "/risque", "/donnees")) or (path.startswith("/runs/") and path.endswith("/analyse")):
        keys = [*keys, *ANALYSIS_JS_KEYS]
    t = translator(lang)
    return {k: t(k) for k in keys}


# Translated labels for target groups (DEFAULT_TARGET_GROUPS' internal keys
# stay in French — logic sentinels in config/defaults.py — only the display
# changes).
TARGET_GROUP_LABEL_KEYS = {
    "Indices": "group_indices",
    "Devises": "group_currencies",
    "Matières premières (futures)": "group_commodities_futures",
    "ETFs larges & style": "group_broad_etfs",
    "ETFs sectoriels & thématiques": "group_sector_etfs",
    "Obligataire & taux (ETFs)": "group_bonds_etfs",
    "Matières premières & devises (ETFs)": "group_commodities_fx_etfs",
    "Volatilité": "group_volatility",
    "Crypto": "group_crypto",
    "International (ETFs pays)": "group_international_etfs",
    "Actions individuelles": "group_stocks",
    "Macro (FRED)": "group_fred_macro",
    "Séries FRED d'entraînement": "group_fred_training",
    # Roadmap bloc 4 -- groupes de l'univers etendu (config/universe_extension.py)
    "Indices mondiaux": "group_world_indices",
    "Actions US (méga-capitalisations)": "group_us_megacaps",
    "Actions France (CAC 40)": "group_fr_cac40",
    "Devises (majeures)": "group_fx_majors",
    "Crypto (majeures)": "group_crypto_majors",
    "Taux US (indices CBOE)": "group_us_rates_indices",
    "Taux US (futures)": "group_us_rates_futures",
    "Matières premières (compléments)": "group_commodities_extra",
    "Actions US (grandes capitalisations)": "group_us_largecaps",
    "Actions France (autres valeurs)": "group_fr_other",
    "Actions Allemagne": "group_germany_stocks",
    "Actions Royaume-Uni": "group_uk_stocks",
    "Actions Europe (autres pays)": "group_eu_other_stocks",
    "Actions Asie (locales & ADR)": "group_asia_stocks",
}
