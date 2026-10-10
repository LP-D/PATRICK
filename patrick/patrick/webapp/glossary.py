"""Short explanations (finance/ML jargon explained at least once) displayed
in the web interface via a small clickable popover — no business logic here,
just text, kept apart from `forms.py` to stay readable. Bilingual (FR/EN),
resolved to the current language in `app.py` before being sent to the
template. Glossary entry text itself (the "fr"/"en" dict values below) is
UI content, not code documentation, and is intentionally left as-is in both
languages.
"""
from __future__ import annotations

# Human-readable name for a glossary term, when the technical key isn't one.
# Without this table, the footnote marker would announce itself as
# "data_quality_enabled, button" to a screen reader and title its popover in
# UPPER_SNAKE_CASE — the glossary exists precisely to translate these keys,
# it could not be the one place that leaves them raw. Terms absent from here
# already carry their own name (`technical`, `XGBoost`, `SMOTE`…): their key
# IS the visible label, and aligning them is enough.
TERM_LABEL_KEYS: dict[str, str] = {
    "data_quality_enabled": "field_data_quality_enabled",
    "scheme": "field_scheme",
    "n_groups": "field_n_groups",
    "k_test_groups": "field_k_test_groups",
    "purge": "field_purge",
    "embargo_enabled": "field_embargo_enabled",
    "track_stability": "field_track_stability",
    "uniqueness_weights": "field_uniqueness_weights",
    "calibration": "field_calibration",
    "stacking": "field_stacking",
    "regime_detection_enabled": "field_regime_detection_enabled",
    "regime_threshold_mode": "field_regime_threshold_mode",
    "tuning_enabled": "field_enabled",
    "optuna_select_top_k_per_horizon": "field_optuna_select_top_k_per_horizon",
    "universe": "field_universe_scope",
    "reduction": "field_reduction_corr_threshold",
    "technical_lookbacks": "section_technical_lookbacks",
    "staged_screening": "field_staged_screening",
    "optuna_bounds": "section_optuna_bounds",
}

GLOSSARY: dict[str, dict[str, str]] = {
    # Feature families
    "technical": {
        "fr": ("Indicateurs techniques classiques (moyennes mobiles, RSI, MACD, "
               "bandes de Bollinger...) calculés sur chaque série de l'univers, "
               "plus les estimateurs de volatilité réalisée OHLC de la cible."),
        "en": ("Classic technical indicators (moving averages, RSI, MACD, Bollinger "
               "bands...) computed on every series in the universe, plus OHLC "
               "realized-volatility estimators for the target."),
    },
    "interactions": {
        "fr": ("Croisements automatiques entre les features les plus utiles "
               "(ratios, différences, produits) découverts une fois sur un "
               "fold pilote, puis appliqués à tout l'historique."),
        "en": ("Automatic crossings between the most useful features (ratios, "
               "differences, products) discovered once on a pilot fold, then "
               "applied to the whole history."),
    },
    "spike": {
        "fr": ("Features orientées détection de sauts/chocs : exposant de Hurst, "
               "semi-variance, skewness glissante, filtre particulaire — cherchent "
               "des signes de rupture de régime plutôt que le niveau ou la tendance."),
        "en": ("Shock/jump-detection features: Hurst exponent, semi-variance, "
               "rolling skewness, particle filter — look for signs of a regime "
               "break rather than level or trend."),
    },
    "vol_models": {
        "fr": ("Modèles de volatilité/dynamique temporelle appliqués à chaque "
               "série (EGARCH, Kalman, AR/MA/ARMA/ARIMA...) — voir le détail de "
               "chacun ci-dessous. Le HMM n'en fait plus partie : il sert aux "
               "modèles par régime et à l'état du marché de la synthèse."),
        "en": ("Volatility/time-dynamics models applied to every series (EGARCH, "
               "Kalman, AR/MA/ARMA/ARIMA...) — see each one's detail below. The HMM "
               "is no longer one of them: it serves per-regime models and the "
               "synthesis page's market state."),
    },
    "macro": {
        "fr": ("Jointures des séries macroéconomiques FRED (taux, spreads, "
               "conditions financières) alignées sur le calendrier de marché."),
        "en": ("Joins of FRED macroeconomic series (rates, spreads, financial "
               "conditions) aligned on the market calendar."),
    },
    "long_cycle": {
        "fr": ("Features de long cycle pour les horizons 252/504/756 j : rendements "
               "à 1, 2 et 3 ans (retournement de long terme), momentum 12-1 mois, "
               "z-score et position dans la fourchette 1 an / 3 ans, drawdown depuis "
               "le plus haut, ratio de volatilité 21 j / 252 j. Désactivée par "
               "défaut. Limite : à 756 j, les labels se chevauchent et il ne reste "
               "qu'environ une observation indépendante tous les 3 ans."),
        "en": ("Long-cycle features for the 252/504/756-day horizons: 1-, 2- and "
               "3-year returns (long-term reversal), 12-1 momentum, 1-/3-year "
               "z-score and range position, drawdown from the running high, "
               "21-/252-day volatility ratio. Off by default. Caveat: at 756 days "
               "labels overlap and only about one independent observation per "
               "3 years remains."),
    },

    # Models in the vol_models family
    "egarch": {
        "fr": ("EGARCH (Exponential GARCH) : modèle de volatilité conditionnelle qui "
               "capture le fait que les chocs négatifs augmentent souvent plus la "
               "volatilité future que les chocs positifs de même taille (effet de "
               "levier). Ajusté une fois sur tout l'historique des rendements."),
        "en": ("EGARCH (Exponential GARCH): conditional-volatility model that "
               "captures how negative shocks often raise future volatility more "
               "than same-size positive shocks (leverage effect). Fit once on the "
               "whole return history."),
    },
    "kalman": {
        "fr": ("Filtre de Kalman (niveau local) : lisse une série en estimant, à "
               "chaque instant, un \"niveau caché\" à partir des seules observations "
               "passées (passe forward causale) — utile pour extraire une tendance "
               "sans utiliser le futur."),
        "en": ("Kalman filter (local level): smooths a series by estimating, at "
               "each point in time, a \"hidden level\" from past observations only "
               "(causal forward pass) — useful to extract a trend without using "
               "the future."),
    },
    "hmm": {
        "fr": ("HMM (Hidden Markov Model) à 2 régimes gaussiens : estime, instant "
               "par instant et de façon causale, la probabilité d'être dans le "
               "régime de plus forte variance (proxy de \"stress\" de marché). "
               "Plus proposé comme feature depuis le 2026-09-26 (64 % du temps de "
               "calcul pour aucune feature retenue) : réservé aux régimes et à "
               "l'analyse de l'état du marché."),
        "en": ("HMM (Hidden Markov Model) with 2 gaussian regimes: estimates, "
               "causally at each point in time, the probability of being in the "
               "highest-variance regime (a \"market stress\" proxy). No longer "
               "offered as a feature since 2026-09-26 (64 % of the build time for "
               "no feature kept): reserved for regimes and market-state analysis."),
    },
    "heston_proxy": {
        "fr": ("Proxy inspiré du modèle de Heston : mesure l'écart entre la "
               "variance réalisée courante et sa moyenne de long terme (retour "
               "à la moyenne de la volatilité) — construit sur la volatilité "
               "réalisée, pas sur des données d'options."),
        "en": ("Proxy inspired by the Heston model: measures the gap between "
               "current realized variance and its long-term mean (volatility "
               "mean-reversion) — built on realized volatility, not options data."),
    },
    "vrp_proxy": {
        "fr": ("Proxy de prime de risque de variance (VRP) : écart relatif entre "
               "volatilité réalisée court terme et long terme, tronqué — approxime "
               "(sans options) la prime que le marché paie pour se couvrir contre "
               "la volatilité."),
        "en": ("Variance risk premium (VRP) proxy: truncated relative gap between "
               "short-term and long-term realized volatility — approximates "
               "(without options) the premium the market pays to hedge volatility."),
    },
    "ar": {
        "fr": ("AR (Autorégressif) : modélise un rendement comme combinaison linéaire de "
               "ses valeurs passées. La feature retenue est le résidu (la part du "
               "rendement que ce modèle linéaire simple n'explique pas)."),
        "en": ("AR (AutoRegressive): models a return as a linear combination of "
               "its own past values. The feature kept is the residual (the part "
               "of the return this simple linear model does not explain)."),
    },
    "ma": {
        "fr": ("MA (Moyenne mobile, au sens statistique — modèle de série temporelle, pas "
               "l'indicateur technique du même nom) : modélise un rendement comme "
               "combinaison de chocs aléatoires passés. Feature = résidu du modèle."),
        "en": ("MA (Moving Average, in the statistical time-series sense — not the "
               "technical indicator of the same name): models a return as a "
               "combination of past random shocks. Feature = the model's residual."),
    },
    "arma": {
        "fr": ("ARMA : combine AR et MA (autorégressif + moyenne mobile statistique) "
               "en un seul modèle. Feature = résidu, c.-à-d. la surprise non expliquée "
               "par cette dynamique linéaire combinée."),
        "en": ("ARMA: combines AR and MA (autoregressive + statistical moving "
               "average) into one model. Feature = residual, i.e. the surprise "
               "not explained by this combined linear dynamic."),
    },
    "arima": {
        "fr": ("ARIMA : ARMA appliqué après une différenciation (I = Intégré) pour "
               "traiter les séries non stationnaires. Feature = résidu du modèle."),
        "en": ("ARIMA: ARMA applied after differencing (I = Integrated) to handle "
               "non-stationary series. Feature = the model's residual."),
    },

    # Feature selection methods
    "shap": {
        "fr": ("SHAP (SHapley Additive exPlanations) : mesure la contribution de "
               "chaque feature aux prédictions d'un modèle déjà entraîné (théorie des "
               "jeux coopératifs) ; la méthode de sélection par défaut ici — bat RFE "
               "et LASSO dans les tests de ce projet."),
        "en": ("SHAP (SHapley Additive exPlanations): measures each feature's "
               "contribution to an already-trained model's predictions "
               "(cooperative game theory); the default selection method here — "
               "beats RFE and LASSO in this project's tests."),
    },
    "rfe": {
        "fr": ("RFE (Recursive Feature Elimination) : entraîne le modèle, retire la "
               "feature la moins importante, répète — une élimination récursive jusqu'à "
               "atteindre le nombre de features souhaité."),
        "en": ("RFE (Recursive Feature Elimination): trains the model, drops the "
               "least important feature, repeats — a recursive elimination down "
               "to the desired number of features."),
    },
    "lasso": {
        "fr": ("LASSO : régression linéaire avec pénalité qui pousse les coefficients "
               "des features les moins utiles exactement à zéro — une sélection "
               "\"embarquée\" dans l'entraînement plutôt qu'une étape séparée."),
        "en": ("LASSO: linear regression with a penalty that pushes the least "
               "useful features' coefficients exactly to zero — an \"embedded\" "
               "selection inside training rather than a separate step."),
    },

    # Samplers (class rebalancing)
    "SMOTE": {
        "fr": ("SMOTE (Synthetic Minority Over-sampling) : génère des exemples "
               "synthétiques de la classe minoritaire (interpolés entre voisins "
               "réels) pour rééquilibrer l'entraînement — le sampler par défaut ici."),
        "en": ("SMOTE (Synthetic Minority Over-sampling): generates synthetic "
               "minority-class examples (interpolated between real neighbors) to "
               "rebalance training — the default sampler here."),
    },
    "BorderlineSMOTE": {
        "fr": ("Variante de SMOTE qui ne génère des exemples synthétiques "
               "qu'autour des points proches de la frontière de décision "
               "entre classes, jugés plus informatifs."),
        "en": ("A SMOTE variant that only generates synthetic examples around "
               "points near the decision boundary between classes, deemed more "
               "informative."),
    },
    "ADASYN": {
        "fr": ("Adaptive Synthetic Sampling : comme SMOTE, mais génère davantage "
               "d'exemples synthétiques là où la classe minoritaire est la plus "
               "difficile à apprendre."),
        "en": ("Adaptive Synthetic Sampling: like SMOTE, but generates more "
               "synthetic examples where the minority class is hardest to learn."),
    },
    "SMOTETomek": {
        "fr": ("SMOTE suivi d'un nettoyage \"Tomek links\" : supprime les paires "
               "d'exemples de classes opposées trop proches l'une de l'autre "
               "après la génération synthétique, pour des frontières plus nettes."),
        "en": ("SMOTE followed by \"Tomek links\" cleaning: removes pairs of "
               "opposite-class examples that are too close to each other after "
               "synthetic generation, for cleaner boundaries."),
    },
    "SMOTEENN": {
        "fr": ("SMOTE suivi d'un nettoyage ENN (Edited Nearest Neighbours) : "
               "supprime les exemples mal classés par leurs plus proches voisins "
               "après la génération synthétique."),
        "en": ("SMOTE followed by ENN (Edited Nearest Neighbours) cleaning: "
               "removes examples misclassified by their nearest neighbors after "
               "synthetic generation."),
    },

    # Classification algorithms
    "XGBoost": {
        "fr": ("Gradient boosting sur arbres de décision, implémentation "
               "optimisée pour la vitesse et la régularisation — un des algos de "
               "référence sur données tabulaires."),
        "en": ("Gradient boosting on decision trees, an implementation optimized "
               "for speed and regularization — one of the reference algorithms "
               "on tabular data."),
    },
    "LightGBM": {
        "fr": ("Gradient boosting sur arbres, avec une croissance \"leaf-wise\" "
               "(par feuille) plutôt que niveau par niveau — généralement plus "
               "rapide que XGBoost sur de gros volumes."),
        "en": ("Gradient boosting on trees, with \"leaf-wise\" growth rather than "
               "level-wise — generally faster than XGBoost on large volumes."),
    },
    "RandomForest": {
        "fr": ("Forêt d'arbres de décision entraînés indépendamment sur des "
               "échantillons bootstrap, moyennés — robuste, moins sujet au "
               "surapprentissage que d'autres méthodes."),
        "en": ("A forest of decision trees trained independently on bootstrap "
               "samples and averaged — robust, less prone to overfitting than "
               "other methods."),
    },
    "GradientBoosting": {
        "fr": ("Gradient boosting \"classique\" (implémentation "
               "scikit-learn) : chaque arbre corrige les erreurs des "
               "précédents, ajoutés séquentiellement."),
        "en": ("\"Classic\" gradient boosting (scikit-learn implementation): "
               "each tree corrects the previous ones' errors, added sequentially."),
    },
    "CatBoost": {
        "fr": ("Gradient boosting conçu pour bien gérer nativement les variables "
               "catégorielles et limiter le surapprentissage via un boosting "
               "\"ordonné\"."),
        "en": ("Gradient boosting designed to natively handle categorical "
               "variables well and limit overfitting via \"ordered\" boosting."),
    },

    # Other pipeline options
    "purge": {
        "fr": ("Purge (walk-forward) : retire les lignes d'entraînement trop proches "
               "de la frontière train/test, pour éviter qu'une fuite d'information "
               "liée à l'horizon de prédiction ne biaise l'évaluation."),
        "en": ("Purge (walk-forward): removes training rows too close to the "
               "train/test boundary, to avoid a prediction-horizon information "
               "leak biasing the evaluation."),
    },
    "embargo_enabled": {
        "fr": ("Embargo (walk-forward) : retire les premières barres de test qui "
               "suivent la coupure train/test — des features à fenêtre glissante "
               "calculées juste après la coupure incluent encore des observations "
               "du train, donc restent corrélées avec lui même une fois la purge "
               "appliquée. Distinct de la purge (qui agit côté train)."),
        "en": ("Embargo (walk-forward): removes the first test bars right after "
               "the train/test cut — rolling-window features computed just after "
               "the cut still include train observations, so remain correlated "
               "with it even after purging. Distinct from purge (which acts on "
               "the train side)."),
    },
    "scheme": {
        "fr": ("Schéma de validation. Walk-forward : une seule frontière train/test "
               "qui avance dans le temps. CPCV (Phase 6.1, López de Prado ch. 12) : "
               "l'historique est découpé en N groupes contigus ; chaque combinaison "
               "de k groupes de test est évaluée avec purge/embargo à CHAQUE "
               "frontière de groupe de test (pas une seule), et les combinaisons "
               "se recollent en plusieurs chemins de backtest indépendants — la "
               "performance est alors rapportée comme une distribution (médiane, "
               "quantiles), jamais un point unique. Alternative au walk-forward, "
               "jamais un remplacement : pas de holdout terminal, pas d'affinage "
               "Optuna, pas de Diebold-Mariano en mode CPCV (limites assumées, "
               "cf. METHODOLOGY.md)."),
        "en": ("Validation scheme. Walk-forward: a single train/test boundary "
               "moving forward in time. CPCV (Phase 6.1, López de Prado ch. 12): "
               "history is split into N contiguous groups; every combination of "
               "k test groups is evaluated with purge/embargo at EACH test-group "
               "boundary (not just one), and combinations are reassembled into "
               "several independent backtest paths — performance is then reported "
               "as a distribution (median, quantiles), never a single point. An "
               "alternative to walk-forward, never a replacement: no terminal "
               "holdout, no Optuna tuning, no Diebold-Mariano in CPCV mode "
               "(assumed limitations, cf. METHODOLOGY.md)."),
    },
    "n_groups": {
        "fr": ("CPCV : nombre de groupes contigus dans lesquels l'historique est "
               "découpé. Avec k_test_groups groupes de test par combinaison, "
               "le nombre de chemins de backtest reconstruits vaut C(N-1, k-1) "
               "(formule combinatoire). Défaut (7) choisi comme le plus petit N "
               "donnant au moins 6 chemins avec k=2 — 6 est le seuil minimal de "
               "fiabilité du PBO (garde C5)."),
        "en": ("CPCV: number of contiguous groups the history is split into. "
               "With k_test_groups test groups per combination, the number of "
               "reconstructed backtest paths is C(N-1, k-1) (combinatorial "
               "formula). Default (7) chosen as the smallest N giving at least "
               "6 paths with k=2 — 6 is the minimal PBO reliability threshold "
               "(C5 guard)."),
    },
    "k_test_groups": {
        "fr": ("CPCV : nombre de groupes de test par combinaison. Avec n_groups "
               "groupes au total, chaque groupe sert de train dans certaines "
               "combinaisons et de test dans d'autres — k_test_groups=2 (défaut) "
               "avec n_groups=7 donne exactement 6 chemins de backtest."),
        "en": ("CPCV: number of test groups per combination. With n_groups "
               "groups total, each group is used as train in some combinations "
               "and as test in others — k_test_groups=2 (default) with "
               "n_groups=7 gives exactly 6 backtest paths."),
    },
    "data_quality_enabled": {
        "fr": ("Portes de qualité de données (Phase 6.5) : chaque série candidate "
               "est contrôlée avant d'entrer dans l'univers de features (prix figés, "
               "trous de cotation, rendements aberrants au-delà d'un z robuste, fin "
               "de série précoce probablement delistée, séries FRED absentes ou "
               "discontinuées). Une série qui échoue un contrôle est exclue avec un "
               "motif explicite, persisté (jamais un avertissement perdu dans les "
               "logs). L'ingestion échoue si trop de l'univers demandé est exclu."),
        "en": ("Data quality gates (Phase 6.5): every candidate series is checked "
               "before entering the feature universe (frozen prices, quote gaps, "
               "aberrant returns beyond a robust z-score, an early series end likely "
               "meaning delisting, missing or discontinued FRED series). A series "
               "that fails a check is excluded with an explicit, persisted reason "
               "(never a warning lost in the logs). Ingestion fails if too much of "
               "the requested universe is excluded."),
    },
    "track_stability": {
        "fr": ("Stabilité de la sélection de features (Phase 6.3) : calcule "
               "l'indice de Jaccard des ensembles de features retenues entre "
               "chaque paire de folds (config gagnante de l'horizon), et la "
               "fréquence de sélection de chaque feature. Un Jaccard moyen bas "
               "signale une sélection qui change presque entièrement d'un fold "
               "à l'autre — le signal identifié n'est pas démontré reproductible."),
        "en": ("Feature selection stability (Phase 6.3): computes the Jaccard "
               "index of the selected feature sets between each pair of folds "
               "(the horizon's winning config), and each feature's selection "
               "frequency. A low mean Jaccard signals a selection that changes "
               "almost entirely from fold to fold — the identified signal is "
               "not shown to be reproducible."),
    },
    "uniqueness_weights": {
        "fr": ("Poids d'unicité et bootstrap séquentiel (Phase 6.2, López de "
               "Prado ch. 4) : avec un horizon &gt; 1, les fenêtres de label se "
               "chevauchent -- les observations d'entraînement ne sont pas "
               "indépendantes. Calcule l'unicité moyenne de chaque observation "
               "(inverse de sa concurrence avec les autres), l'utilise comme "
               "sample_weight, et pour RandomForest, tire chaque arbre par "
               "bootstrap séquentiel (favorise les observations les moins "
               "concurrentes) plutôt qu'un bootstrap uniforme. Ne s'applique "
               "concrètement que si le sampler est \"none\" (SMOTE synthétise "
               "des observations sans span réel). La taille d'échantillon "
               "effective (somme des unicités) est toujours rapportée à côté "
               "de n -- c'est souvent une fraction surprenamment faible."),
        "en": ("Uniqueness weights and sequential bootstrap (Phase 6.2, López "
               "de Prado ch. 4): with horizon &gt; 1, label windows overlap -- "
               "training observations aren't independent. Computes each "
               "observation's average uniqueness (inverse of its concurrency "
               "with others), uses it as sample_weight, and for RandomForest, "
               "draws each tree via sequential bootstrap (favors the least "
               "concurrent observations) instead of uniform bootstrap. Only "
               "actually applies when the sampler is \"none\" (SMOTE "
               "synthesizes observations with no real span). The effective "
               "sample size (sum of uniquenesses) is always reported next to "
               "n -- often a surprisingly small fraction of it."),
    },
    "calibration": {
        "fr": ("Calibration des probabilités prédites (ex. Platt scaling / "
               "isotonic), pour que les scores du modèle reflètent mieux de "
               "vraies probabilités avant d'appliquer un seuil de décision."),
        "en": ("Calibration of predicted probabilities (e.g. Platt scaling / "
               "isotonic), so the model's scores better reflect true "
               "probabilities before applying a decision threshold."),
    },
    "stacking": {
        "fr": ("Stacking : combine les prédictions de plusieurs modèles via un "
               "méta-modèle entraîné par-dessus, au lieu de garder le meilleur "
               "modèle individuel."),
        "en": ("Stacking: combines several models' predictions via a meta-model "
               "trained on top, instead of keeping the best individual model."),
    },
    "regime_detection_enabled": {
        "fr": ("Détecte le régime de volatilité courant (calme/normal/stress) via un "
               "HMM causal (filtre en avant seulement, jamais lissé avec le futur). "
               "Le nombre d'états internes est choisi automatiquement par BIC/AIC."),
        "en": ("Detects the current volatility regime (calm/normal/stress) via a "
               "causal HMM (forward-only filter, never smoothed with the future). "
               "The internal number of states is auto-selected via BIC/AIC."),
    },
    # CHANTIER B (feature/model-categories-comparison) -- contenu pret pour
    # la table de comparaison a 3 categories, dont l'affichage web depend de
    # l'integration reelle dans pipeline/engine.py (hors scope de ce
    # chantier, voir tracking/model_categories.py). Definitions gardees ici
    # pour eviter de les re-ecrire quand cette integration sera faite.
    "model_category_global": {
        "fr": "Global : le pipeline actuel, un seul modele entraine sur tout l'historique du ticker, sans distinction de regime.",
        "en": "Global: the current pipeline, a single model trained on the ticker's whole history, regime-agnostic.",
    },
    "model_category_per_regime": {
        "fr": ("Par-regime : un modele distinct entraine par regime de volatilite "
               "(calme/normal/stress, detection HMM causale) plutot qu'un seul modele "
               "global -- soumis au meme garde-fou de fragmentation que la detection de regime."),
        "en": ("Per-regime: a separate model trained per volatility regime "
               "(calm/normal/stress, causal HMM detection) instead of one global model -- "
               "subject to the same fragmentation guardrail as regime detection."),
    },
    "model_category_stacking": {
        "fr": ("Stacking : combine les predictions de PLUSIEURS modeles (global + par-regime, "
               "voire plusieurs algorithmes) via un meta-modele entraine par-dessus -- different "
               "du modele « global », qui reste un modele individuel unique."),
        "en": ("Stacking: combines predictions from SEVERAL models (global + per-regime, or "
               "several algorithms) via a meta-model trained on top -- different from the "
               "\"global\" category, which stays a single individual model."),
    },
    "regime_threshold_mode": {
        "fr": ("Comment la probabilité filtrée de régime est convertie en 3 "
               "catégories : « quantile » utilise des coupures relatives à "
               "l'historique d'entraînement (ex. 33e/67e percentile) ; « valeur "
               "fixe » utilise directement les 2 valeurs saisies ci-dessous, "
               "quelle que soit la distribution observée."),
        "en": ("How the filtered regime probability is converted into 3 "
               "categories: \"quantile\" uses cutoffs relative to the training "
               "history (e.g. 33rd/67th percentile); \"fixed value\" uses the 2 "
               "values entered below directly, regardless of the observed "
               "distribution."),
    },
    "tuning_enabled": {
        "fr": ("Tuning Optuna : affine automatiquement les hyperparamètres "
               "des meilleures configs trouvées par la grille, via une "
               "recherche bayésienne (Optuna), avant l'export final."),
        "en": ("Optuna tuning: automatically refines the hyperparameters of the "
               "best configs found by the grid, via a Bayesian search (Optuna), "
               "before the final export."),
    },
    "optuna_select_top_k_per_horizon": {
        "fr": ("Coché (recommandé) : chaque horizon reçoit son propre budget "
               "Top-K/essais Optuna, indépendamment des autres horizons. "
               "Top-K vaut 1 par défaut : seul le meilleur candidat du scan "
               "est affiné pour chaque horizon ; augmente-le pour explorer "
               "plusieurs finalistes. "
               "Décoché : le Top-K est sélectionné globalement tous horizons "
               "confondus -- un horizon dont les meilleures configs dominent "
               "peut alors capter tout le budget Optuna, laissant les autres "
               "horizons sans aucun essai de tuning."),
        "en": ("Checked (recommended): each horizon gets its own Top-K/Optuna "
               "trial budget, independently of the other horizons. Top-K "
               "defaults to 1, tuning only the best scan candidate per horizon; "
               "raise it to explore more finalists. Unchecked: Top-K is selected "
               "globally across all horizons -- a horizon whose best configs "
               "dominate can then capture the entire Optuna budget, leaving the "
               "other horizons with zero tuning trials."),
    },
    # Portfolio / statistics surfaces (roadmap bloc 4: tooltips on regime/HRP/BL)
    "hrp": {
        "fr": ("Hierarchical Risk Parity (López de Prado, 2016) : regroupe les actifs par "
               "similarité de corrélation, puis répartit le risque entre groupes par "
               "bissection récursive, en inverse de la variance. N'utilise aucun rendement "
               "espéré et n'inverse jamais la matrice de covariance — robuste là où Markowitz "
               "concentre tout sur quelques actifs."),
        "en": ("Hierarchical Risk Parity (López de Prado, 2016): clusters assets by "
               "correlation similarity, then splits risk between clusters by recursive "
               "bisection, inverse-variance. Uses no expected return and never inverts the "
               "covariance matrix — robust where Markowitz concentrates on a few assets."),
    },
    "universe": {
        "fr": ("Les séries disponibles (tickers yfinance et séries FRED) sont utilisées comme "
               "features, à l'exception de la cible sélectionnée."),
        "en": ("Available series (yfinance tickers and FRED series) are used as features, "
               "excluding the selected target."),
    },
    "reduction": {
        "fr": ("Regroupe les séries candidates corrélées et en conserve une par groupe. "
               "La décision est prise séparément dans chaque fold avec les seules données "
               "d'entraînement. Un seuil inférieur à 0,8 est considéré agressif."),
        "en": ("Clusters correlated candidate series and keeps one per group. The decision "
               "is made separately in each fold using training data only. A threshold below "
               "0.8 is considered aggressive."),
    },
    "technical_lookbacks": {
        "fr": ("Fenêtres roulantes, en barres, utilisées par les indicateurs techniques. "
               "Saisir une liste d'entiers (ex. 10,20,60) ou un intervalle (ex. 5-15). "
               "Les valeurs par défaut conservent le comportement existant."),
        "en": ("Rolling windows, in bars, used by technical indicators. Enter comma-separated "
               "integers (e.g. 10,20,60) or a range (e.g. 5-15). Defaults preserve existing behavior."),
    },
    "staged_screening": {
        "fr": ("Entraîne chaque candidat une seule fois et le note d'un coup sur toute la période "
               "hors-échantillon (la fenêtre totale), puis ne passe que les meilleurs de chaque horizon "
               "au walk-forward complet (tous les découpages) et à Optuna. Le mode exhaustif reste "
               "disponible : chaque candidat est alors évalué sur tous les découpages."),
        "en": ("Fits each candidate once and scores it in one go on the whole out-of-sample period "
               "(the total window), then only the best of each horizon go through the full "
               "walk-forward (every fold) and Optuna. Exhaustive mode remains available: every "
               "candidate is then evaluated on all folds."),
    },
    "optuna_bounds": {
        "fr": ("Ces bornes définissent les intervalles dans lesquels Optuna explore les "
               "hyperparamètres. Elles ne changent rien si le réglage Optuna est désactivé."),
        "en": ("These bounds define the intervals Optuna searches for each hyperparameter. "
               "They have no effect when Optuna tuning is disabled."),
    },
    "asset_statistics": {
        "fr": ("Statistiques calculées directement depuis les cours de chaque actif : "
               "rendements, tendance, z-score et volatilité. Ce ne sont pas des prédictions "
               "du modèle."),
        "en": ("Statistics computed directly from each asset's prices: returns, trend, z-score, "
               "and volatility. These are not model predictions."),
    },
    "asset_bar_windows": {
        "fr": ("Les fenêtres sont comptées en observations de la série, pas en jours calendaires. "
               "Pour les séries macro mensuelles ou trimestrielles, une barre représente un mois "
               "ou un trimestre."),
        "en": ("Windows are counted in observations, not calendar days. For monthly or quarterly "
               "macro series, one bar represents a month or quarter."),
    },
    "data_freshness": {
        "fr": ("Données lues dans le cache local, sans téléchargement depuis cette page. "
               "« Jamais mis en cache » signifie qu'aucun run n'a encore chargé cette série."),
        "en": ("Data is read from the local cache; this page does not download anything. "
               "\"Never cached\" means no run has loaded the series yet."),
    },
    "equity_universe": {
        "fr": ("Univers actions séparé des features des autres classes. Chaque titre peut être "
               "choisi comme cible d'un run, mais n'est pas injecté dans les autres modèles."),
        "en": ("The equity universe is separate from other asset-class features. Each stock can "
               "be selected as a run target but is not injected into other models."),
    },
    "equity_min_history": {
        "fr": ("Le badge indique si l'historique disponible atteint le seuil minimal pour "
               "envisager un entraînement. Les prix et fondamentaux restent consultables "
               "en dessous de ce seuil."),
        "en": ("The badge indicates whether available history reaches the minimum threshold "
               "to consider training. Prices and fundamentals remain viewable below it."),
    },
    "equity_feature_exclusions": {
        "fr": ("Certaines familles de features ne s'appliquent pas aux actions individuelles. "
               "Chaque exclusion est listée avec son motif."),
        "en": ("Some feature families do not apply to individual equities. Each exclusion is "
               "listed with its reason."),
    },
    "equity_fundamentals": {
        "fr": ("Données collectées hors pipeline ML. Les valeurs fondamentales peuvent être "
               "révisées et leur date réelle de publication n'est pas vérifiée."),
        "en": ("Collected outside the ML pipeline. Fundamentals may be revised, and their "
               "actual publication date is not verified."),
    },
    "prediction_overview": {
        "fr": ("Affiche le dernier signal enregistré par cible et horizon, ainsi que sa "
               "significativité. Vue en lecture seule : aucun modèle n'est recalculé."),
        "en": ("Shows the latest recorded signal by target and horizon, with its significance. "
               "Read-only view: no model is recalculated."),
    },
    "live_reliability": {
        "fr": ("Taux de réussite des prédictions live dont l'issue est connue, distinct du "
               "backtest. Une alerte n'apparaît qu'après au moins 10 résultats observés."),
        "en": ("Hit rate for live predictions whose outcome is known, separate from the backtest. "
               "A warning appears only after at least 10 observed outcomes."),
    },
    "portfolio_contradictions": {
        "fr": ("Signale des paires historiquement corrélées dont les derniers signaux, au même "
               "horizon, ne respectent pas le sens de corrélation attendu."),
        "en": ("Flags historically correlated pairs whose latest signals at the same horizon "
               "do not match the expected correlation direction."),
    },
    "portfolio_pairs": {
        "fr": ("Une paire par ligne au format symbole_A:symbole_B:sens, avec positive ou "
               "negative comme sens. Un champ vide restaure les paires par défaut."),
        "en": ("One pair per line in symbol_A:symbol_B:direction format, using positive or "
               "negative. An empty field restores the default pairs."),
    },
    "wealth_summary": {
        "fr": ("Les soldes et positions sont calculés depuis les mouvements. Les comptes "
               "fictifs restent séparés du patrimoine réel ; glisse un mouvement vers un "
               "compte fictif pour le copier."),
        "en": ("Balances and positions are calculated from movements. Fictive accounts stay "
               "separate from real wealth; drag a movement to a fictive account to copy it."),
    },
    "wealth_account_rules": {
        "fr": ("Pour un PEA, la date d'ouverture sert au contrôle des 5 ans. Les indices par "
               "défaut sont Euro Stoxx 50 pour PEA, MSCI World (URTH) pour CTO/AV, aucun pour "
               "livret et dépôt à terme."),
        "en": ("For a PEA, the opening date is used for the 5-year rule. Default benchmarks are "
               "Euro Stoxx 50 for PEA, MSCI World (URTH) for CTO/AV, and none for savings or term deposits."),
    },
    "wealth_movements": {
        "fr": ("Glisser une ligne vers un compte réel la déplace, vers un compte fictif la copie ; "
               "un transfert vers un compte réel depuis un compte fictif est refusé. Les CSV "
               "peuvent être déposés sur un compte pour prévisualisation avant import."),
        "en": ("Drag a row to a real account to move it or to a fictive account to copy it; "
               "transfers from fictive to real accounts are rejected. CSV files can be dropped "
               "on an account for preview before import."),
    },
    "wealth_csv_import": {
        "fr": ("Les colonnes françaises et anglaises sont reconnues. Les types de mouvements "
               "sont déduits des libellés ; frais, taxes, ISIN et cryptomonnaies sont pris en charge. "
               "L'aperçu permet de contrôler les lignes avant l'enregistrement et évite les doublons."),
        "en": ("French and English columns are recognized. Movement types are inferred from labels; "
               "fees, taxes, ISINs, and cryptocurrencies are supported. Preview rows before saving; "
               "re-imports do not create duplicates."),
    },
    "wealth_simulation": {
        "fr": ("Rejoue les prédictions déjà enregistrées sur les positions dont le symbole a été "
               "une cible de run. Le résultat suit les pondérations actuelles et n'entraîne aucun modèle."),
        "en": ("Replays saved predictions for positions whose symbols have been run targets. Results "
               "use current position weights and do not train any models."),
    },
    "wealth_simulation_trials": {
        "fr": ("Chaque actif simulé est enregistré comme une simulation et contribue au Sharpe "
               "déflaté des essais futurs sur cette cible."),
        "en": ("Each simulated asset is recorded as a simulation and contributes to the deflated "
               "Sharpe ratio of future trials on that target."),
    },
    "black_litterman": {
        "fr": ("Black-Litterman : part des rendements implicites d'équilibre (ceux qui "
               "justifient les poids de marché) et les ajuste par des vues (ici les signaux "
               "des modèles), pondérées par leur incertitude. Une vue peu fiable déplace peu "
               "l'allocation."),
        "en": ("Black-Litterman: starts from equilibrium implied returns (those that justify "
               "market weights) and tilts them with views (here, model signals) weighted by "
               "their uncertainty. An unreliable view barely moves the allocation."),
    },
    "ledoit_wolf": {
        "fr": ("Covariance Ledoit-Wolf : moyenne pondérée de la covariance empirique et d'une "
               "cible structurée ; l'intensité δ ∈ [0, 1] est estimée pour minimiser l'erreur "
               "quadratique. Indispensable quand le nombre d'actifs approche le nombre "
               "d'observations."),
        "en": ("Ledoit-Wolf covariance: weighted average of the sample covariance and a "
               "structured target; the intensity δ ∈ [0, 1] is estimated to minimise the "
               "squared error. Needed when the number of assets nears the number of "
               "observations."),
    },
    "regime": {
        "fr": ("Régime de marché : état (calme, normal, stress) déduit par un HMM (modèle "
               "de Markov caché) des rendements quotidiens — terciles de la probabilité "
               "d'être dans l'état le plus volatil. Un modèle « par régime » n'est entraîné "
               "que sur les dates du même régime — plus spécialisé, mais sur moins de données."),
        "en": ("Market regime: state (calm, normal, stress) inferred by an HMM (hidden "
               "Markov model) from daily returns — terciles of the probability of being in "
               "the most volatile state. A per-regime model is trained only on dates of the "
               "same regime — more specialised, on less data."),
    },
    "diebold_mariano": {
        "fr": ("Test de Diebold-Mariano (correction Harvey-Leybourne-Newbold) : le modèle "
               "se trompe-t-il moins souvent que la baseline, au-delà du hasard ? Calculé sur "
               "le holdout terminal, jamais sur les données qui ont servi à choisir le modèle."),
        "en": ("Diebold-Mariano test (Harvey-Leybourne-Newbold correction): does the model "
               "err less often than the baseline, beyond chance? Computed on the terminal "
               "holdout, never on the data used to choose the model."),
    },
    "holdout": {
        "fr": ("Holdout terminal : dernière période de l'historique, mise de côté avant tout "
               "calcul et jamais utilisée pour choisir une configuration. Seule mesure hors "
               "échantillon honnête d'un modèle déjà choisi."),
        "en": ("Terminal holdout: the last period of history, set aside before any "
               "computation and never used to choose a configuration. The only honest "
               "out-of-sample measure of an already chosen model."),
    },
    "deflated_sharpe": {
        "fr": ("Sharpe déflaté (Bailey & López de Prado) : probabilité que le vrai Sharpe soit "
               "positif, compte tenu du nombre d'essais réalisés sur la cible, de la longueur "
               "de l'historique et de l'asymétrie/aplatissement des rendements."),
        "en": ("Deflated Sharpe (Bailey & López de Prado): probability that the true Sharpe "
               "is positive, given the number of trials run on the target, the sample length "
               "and the returns' skewness/kurtosis."),
    },
    "pbo": {
        "fr": ("Probabilité de sur-sélection de backtest (PBO) : part des découpages où la "
               "configuration la meilleure en échantillon finit sous la médiane hors "
               "échantillon. Au-delà de 0,5, la sélection ne vaut pas mieux que le hasard."),
        "en": ("Probability of backtest overfitting (PBO): share of splits where the best "
               "in-sample configuration ends below the out-of-sample median. Above 0.5, "
               "selection is no better than chance."),
    },
    "conformal": {
        "fr": ("Prédiction conforme : au lieu d'une direction, un ensemble ({hausse}, {baisse} ou les deux) "
               "construit pour contenir la réalisation avec une probabilité visée 1 − α. Un ensemble à deux "
               "directions signifie « pas d'avis ». La garantie suppose des données échangeables ; la variante "
               "adaptative (ACI) la rétablit en moyenne de long terme sous dérive."),
        "en": ("Conformal prediction: instead of one direction, a set ({up}, {down} or both) built to contain the "
               "outcome with target probability 1 − α. A two-direction set means 'no call'. The guarantee assumes "
               "exchangeable data; the adaptive variant (ACI) restores it on the long-run average under drift."),
    },
    "twr": {
        "fr": ("Rendement pondéré par le temps (TWR) : performance de la gestion, neutralisée "
               "des apports et retraits — c'est elle qui se compare à un indice de référence."),
        "en": ("Time-weighted return (TWR): performance of the management itself, neutral to "
               "deposits and withdrawals — the one to compare with a benchmark index."),
    },
    "xirr": {
        "fr": ("Rendement pondéré par les capitaux (TRI / XIRR) : taux annuel qui annule la "
               "valeur actuelle de tous les flux (apports, retraits, valeur finale). Mesure "
               "l'expérience de l'investisseur, timing des apports inclus."),
        "en": ("Money-weighted return (IRR / XIRR): annual rate that zeroes the present value "
               "of all flows (deposits, withdrawals, final value). Measures the investor's "
               "experience, including the timing of deposits."),
    },
    "pea": {
        "fr": ("PEA : enveloppe fiscale française réservée aux actions européennes (et fonds "
               "éligibles), versements plafonnés à 150 000 € ; tout retrait avant 5 ans clôture "
               "le plan (sauf exceptions légales). Plafond et règles à vérifier auprès de la "
               "source officielle (service-public.fr)."),
        "en": ("PEA: French tax wrapper restricted to European equities (and eligible funds), "
               "deposits capped at €150,000; any withdrawal before 5 years closes the plan "
               "(legal exceptions aside). Check the cap and rules against the official source."),
    },
    "cto": {
        "fr": "Compte-titres ordinaire : aucun plafond ni restriction d'actifs, fiscalité de droit commun.",
        "en": "Ordinary securities account: no cap or asset restriction, standard taxation.",
    },
    "dat": {
        "fr": ("Dépôt à terme : capital bloqué à taux fixe jusqu'à l'échéance. Aucun historique "
               "de prix : valorisé par capitalisation du taux (intérêts simples au prorata) et "
               "traité comme un actif sans risque de marché (variance et covariances nulles)."),
        "en": ("Term deposit: capital locked at a fixed rate until maturity. No price history: "
               "valued by accruing the rate (simple interest, pro rata) and treated as an asset "
               "with no market risk (zero variance and covariances)."),
    },
}


# Vocabulaire ajouté à la refonte du 2026-10-09 (métriques, p-values, cibles, qualité des données, classes d'actifs).
from patrick.webapp.glossary_extra import EXTRA_GLOSSARY

GLOSSARY.update(EXTRA_GLOSSARY)


# Pages Exploration, Deep learning et Reinforcement learning (webapp/glossary_models.py).
from patrick.webapp import glossary_extra as _glossary_extra  # noqa: E402
from patrick.webapp import glossary_models as _glossary_models  # noqa: E402

GLOSSARY.update(_glossary_models.GLOSSARY_MODELS)
GLOSSARY.update(_glossary_models.GLOSSARY_DL)
TERM_LABEL_KEYS.update(_glossary_models.LABELS)
TERM_LABEL_KEYS.update(_glossary_models.LABELS_DL)
_glossary_extra.TERM_CATEGORY.update(_glossary_models.CATEGORY)
_glossary_extra.TERM_CATEGORY.update(_glossary_models.CATEGORY_DL)
