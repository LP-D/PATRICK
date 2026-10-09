"""Vocabulaire ajouté à la refonte du 2026-10-09 (métriques, p-values, cibles, qualité des données, classes d'actifs) et
classement de TOUS les termes par rubrique pour la page /vocabulary. Fusionné dans `glossary.GLOSSARY` ; chaque terme existe
en FR et en EN. Le jargon financier est expliqué une fois ici, puis réutilisé partout (bulles « ? » et page dédiée)."""
from __future__ import annotations


def _g(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


# Rubriques, dans l'ordre d'affichage : (clé, libellé FR, libellé EN).
CATEGORIES: list[tuple[str, str, str]] = [
    ("targets", "Cibles et mouvements", "Targets and moves"),
    ("metrics", "Métriques de performance", "Performance metrics"),
    ("stats", "p-values et tests statistiques", "p-values and statistical tests"),
    ("validation", "Validation et anti-fuite", "Validation and leak protection"),
    ("data", "Données et qualité", "Data and quality"),
    ("assets", "Classes d'actifs", "Asset classes"),
    ("models", "Modèles et features", "Models and features"),
    ("portfolio", "Portefeuille, fonds et patrimoine", "Portfolio, funds and wealth"),
    ("app", "Suivi et application", "Tracking and application"),
]

EXTRA_GLOSSARY: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ cibles et mouvements
    "target_directional": _g(
        "Cible directionnelle : le modèle prédit le sens et l'intensité du mouvement du prix de l'actif sur l'horizon "
        "choisi. C'est le mode par défaut (« rendement brut »).",
        "Directional target: the model predicts the direction and intensity of the asset's price move over the chosen "
        "horizon. This is the default mode (\"raw return\")."),
    "target_alpha": _g(
        "Cible alpha : le modèle prédit si l'actif fera mieux ou moins bien que son benchmark, c'est-à-dire le rendement de "
        "l'actif moins β × le rendement du benchmark. Elle isole ce que l'actif fait de plus que le marché. Un run alpha "
        "s'appelle « actif__alpha_benchmark » et n'est jamais mélangé aux runs directionnels.",
        "Alpha target: the model predicts whether the asset will beat or lag its benchmark, i.e. the asset return minus "
        "β × the benchmark return. It isolates what the asset does beyond the market. An alpha run is named "
        "\"asset__alpha_benchmark\" and never mixed with directional runs."),
    "benchmark": _g(
        "Benchmark : l'indice de référence auquel on compare un actif (S&P 500 pour une action américaine, CAC 40 ou "
        "Euro Stoxx 50 pour une action européenne). Sert de base à la cible alpha.",
        "Benchmark: the reference index an asset is compared with (S&P 500 for a US stock, CAC 40 or Euro Stoxx 50 for a "
        "European one). It is the basis of the alpha target."),
    "beta": _g(
        "Bêta (β) : sensibilité d'un actif à son benchmark. β = 1,2 : quand le benchmark gagne 1 %, l'actif gagne en moyenne "
        "1,2 %. Estimé sur une fenêtre glissante de 252 jours, jamais sur toute la période (sinon fuite).",
        "Beta (β): sensitivity of an asset to its benchmark. β = 1.2: when the benchmark gains 1%, the asset gains 1.2% on "
        "average. Estimated on a rolling 252-day window, never on the whole period (that would leak)."),
    "four_moves": _g(
        "Les 4 mouvements : baisse forte, baisse faible, hausse faible, hausse forte. Les seuils « fort / faible » sont les "
        "quartiles (25 % / 75 %) des rendements habituels de l'actif, calculés sur la période d'entraînement seulement.",
        "The 4 moves: strong down, weak down, weak up, strong up. The \"strong / weak\" thresholds are the quartiles "
        "(25% / 75%) of the asset's usual returns, computed on the training period only."),
    "direction_vs_intensity": _g(
        "Erreur de direction ou d'intensité : une erreur de direction est un mauvais sens (hausse annoncée, baisse "
        "constatée) ; une erreur d'intensité garde le bon sens mais se trompe d'ampleur (hausse forte annoncée, hausse "
        "faible constatée). La première coûte plus cher.",
        "Direction vs intensity error: a direction error is the wrong way (up announced, down observed); an intensity "
        "error keeps the right direction but misses the size (strong up announced, weak up observed). The first one costs "
        "more."),
    "horizon": _g(
        "Horizon : nombre de séances de bourse entre le moment de la prédiction et celui où le mouvement est mesuré. "
        "Week-ends et jours fériés ne comptent pas. 504 et 756 jours sont descriptifs : hors de la correction de tests "
        "multiples.",
        "Horizon: number of trading sessions between the prediction and the moment the move is measured. Weekends and "
        "holidays do not count. 504 and 756 days are descriptive: outside the multiple-testing correction."),
    "flat_thr": _g(
        "Seuil « plat » : un mouvement plus petit que ce seuil (0,3 % par défaut) est ignoré à l'entraînement, car ce n'est "
        "ni une vraie hausse ni une vraie baisse.",
        "\"Flat\" threshold: a move smaller than this (0.3% by default) is ignored in training, being neither a real up "
        "nor a real down."),
    "persistence_baseline": _g(
        "Baseline de persistance : le prochain mouvement répète le dernier. C'est la référence minimale : un modèle qui ne "
        "la bat pas n'a rien démontré.",
        "Persistence baseline: the next move repeats the last one. It is the minimum benchmark: a model that does not beat "
        "it has shown nothing."),

    # ------------------------------------------------------------------ métriques
    "auc": _g(
        "AUC (aire sous la courbe ROC) : probabilité que le modèle classe un cas positif au-dessus d'un cas négatif. 0,5 = "
        "hasard, 1 = parfait. Ici : une classe contre les trois autres, moyennée sur les 4 mouvements. Sur un marché liquide "
        "une AUC durablement au-dessus de 0,65 est rare ; au-dessus de 0,85, c'est presque toujours une fuite de données.",
        "AUC (area under the ROC curve): probability that the model ranks a positive case above a negative one. 0.5 = "
        "chance, 1 = perfect. Here: one class against the other three, averaged over the 4 moves. On a liquid market an AUC "
        "durably above 0.65 is rare; above 0.85 it is almost always a data leak."),
    "f1": _g(
        "F1 : moyenne harmonique de la précision (parmi les signaux émis, combien sont justes) et du rappel (parmi les "
        "événements réels, combien sont détectés). Va de 0 à 1 ; punit autant les fausses alertes que les oublis.",
        "F1: harmonic mean of precision (of the signals issued, how many are right) and recall (of the real events, how "
        "many are caught). Ranges 0 to 1; punishes false alarms and misses alike."),
    "f1_dir": _g(
        "F1 directionnel (F1_dir) : F1 sur hausse contre baisse, intensité ignorée. C'est la métrique de sélection de PATRICK. "
        "Autour de 0,50 = hasard ; les meilleurs résultats honnêtes observés vont jusqu'à 0,54 sur holdout.",
        "Directional F1 (F1_dir): F1 on up vs down, intensity ignored. It is PATRICK's selection metric. Around 0.50 = "
        "chance; the best honest results observed reach 0.54 on holdout."),
    "acc_dir": _g(
        "Exactitude directionnelle (Acc_dir) : part des directions (hausse / baisse) correctement devinées.",
        "Directional accuracy (Acc_dir): share of directions (up / down) guessed right."),
    "balanced_accuracy": _g(
        "Exactitude équilibrée : moyenne du rappel de chacun des 4 mouvements. Insensible au déséquilibre des classes (un "
        "modèle qui prédit toujours la classe la plus fréquente n'y gagne rien).",
        "Balanced accuracy: mean recall of each of the 4 moves. Insensitive to class imbalance (a model that always "
        "predicts the most frequent class gains nothing)."),
    "mcc": _g(
        "Coefficient de corrélation de Matthews (MCC) : corrélation entre prédictions et réalité, de -1 à 1. 0 = hasard. "
        "Une des rares métriques fiables quand les classes sont déséquilibrées.",
        "Matthews correlation coefficient (MCC): correlation between predictions and reality, -1 to 1. 0 = chance. One of "
        "the few reliable metrics when classes are imbalanced."),
    "brier": _g(
        "Score de Brier : erreur quadratique moyenne entre la probabilité annoncée et le résultat (0 ou 1). Plus bas = mieux. "
        "0,25 correspond à un pile ou face.",
        "Brier score: mean squared error between the announced probability and the outcome (0 or 1). Lower = better. "
        "0.25 matches a coin flip."),
    "ece": _g(
        "Erreur de calibration attendue (ECE) : écart moyen entre la probabilité annoncée (« 70 % de chances de hausse ») et "
        "la fréquence réelle. Un modèle bien calibré a une ECE proche de 0.",
        "Expected calibration error (ECE): mean gap between the announced probability (\"70% chance of up\") and the real "
        "frequency. A well-calibrated model has an ECE near 0."),
    "hit_rate": _g(
        "Taux de réussite live : part de bonnes directions parmi les signaux déjà résolus depuis le lancement du modèle.",
        "Live hit rate: share of right directions among already-resolved signals since the model went live."),

    # ------------------------------------------------------------------ p-values et tests
    "p_value": _g(
        "p-value : probabilité d'observer un résultat au moins aussi bon que celui-ci si le modèle n'avait en réalité aucun "
        "talent (le hasard seul). Petite (< 0,05) : le hasard explique mal le résultat. Grande : on ne peut pas exclure le "
        "hasard. Ce n'est pas la probabilité que le modèle soit bon.",
        "p-value: probability of observing a result at least this good if the model had no real skill (chance alone). Small "
        "(< 0.05): chance explains the result poorly. Large: chance cannot be ruled out. It is not the probability that "
        "the model is good."),
    "p_value_dm": _g(
        "p-value de Diebold-Mariano : teste si les erreurs du modèle sont plus petites que celles de la meilleure baseline "
        "(persistance, tendance...), sur le holdout terminal. Unilatérale : elle ne regarde que « le modèle fait mieux ». "
        "Brute : non corrigée du nombre de modèles testés.",
        "Diebold-Mariano p-value: tests whether the model's errors are smaller than the best baseline's (persistence, "
        "trend...), on the terminal holdout. One-sided: it only looks at \"the model does better\". Raw: not corrected "
        "for the number of models tried."),
    "p_value_adjusted": _g(
        "p-value ajustée (BH) : la p-value brute corrigée du fait qu'on a testé beaucoup de cibles. Plus on teste, plus une "
        "p-value basse arrive par chance ; la correction de Benjamini-Hochberg le compense. C'est elle qu'il faut comparer "
        "au seuil.",
        "Adjusted p-value (BH): the raw p-value corrected for having tested many targets. The more we test, the more a "
        "low p-value happens by chance; the Benjamini-Hochberg correction offsets it. This is the one to compare with the "
        "threshold."),
    "bh_fdr": _g(
        "Correction de Benjamini-Hochberg (FDR, taux de fausses découvertes) : parmi les cibles déclarées significatives, "
        "la part attendue de faux positifs ne dépasse pas α (10 % par défaut). Appliquée par famille d'actifs, jamais sur "
        "les horizons descriptifs.",
        "Benjamini-Hochberg correction (FDR, false discovery rate): among the targets declared significant, the expected "
        "share of false positives does not exceed α (10% by default). Applied per asset family, never on descriptive "
        "horizons."),
    "alpha_level": _g(
        "Seuil de signification α : la p-value en dessous de laquelle on rejette le hasard. 0,05 pour le test de "
        "Diebold-Mariano brut, 0,10 pour la correction FDR. Réglable dans l'URL (?dm_alpha=, ?fdr_alpha=).",
        "Significance level α: the p-value below which chance is rejected. 0.05 for the raw Diebold-Mariano test, 0.10 "
        "for the FDR correction. Adjustable in the URL (?dm_alpha=, ?fdr_alpha=)."),
    "spearman_holdout": _g(
        "Corrélation de Spearman test/holdout : les configurations qui gagnent sur les folds de test gagnent-elles aussi sur "
        "le holdout ? ρ proche de 1 : la sélection se généralise ; proche de 0 : le classement est du bruit. Sa p-value "
        "dit si ρ diffère de 0. Diagnostic en lecture seule.",
        "Spearman test/holdout correlation: do the configurations that win on test folds also win on the holdout? ρ near "
        "1: selection generalises; near 0: the ranking is noise. Its p-value says whether ρ differs from 0. Read-only "
        "diagnostic."),
    "n_trials": _g(
        "Essais cumulés : toutes les configurations déjà testées sur cette cible et cet horizon, tous runs confondus. Plus on "
        "essaie, plus le meilleur résultat est surestimé : c'est ce nombre, pas celui du run, qui sert à déflater les scores.",
        "Cumulative trials: every configuration already tried on this target and horizon, across all runs. The more we try, "
        "the more the best result is overestimated: this number, not the run's own, deflates the scores."),

    # ------------------------------------------------------------------ validation et anti-fuite
    "walk_forward": _g(
        "Validation walk-forward : on entraîne sur le passé, on teste sur la période juste après, puis on avance la fenêtre. "
        "Chaque test porte sur des dates jamais vues à l'entraînement, comme en conditions réelles.",
        "Walk-forward validation: train on the past, test on the period right after, then roll the window forward. Every "
        "test is on dates never seen in training, as in real conditions."),
    "fold": _g(
        "Fold : une des périodes de test successives d'une validation. Les métriques d'un modèle sont détaillées fold par "
        "fold ; leur moyenne est la performance affichée.",
        "Fold: one of the successive test periods of a validation. A model's metrics are detailed fold by fold; their mean "
        "is the displayed performance."),
    "data_leak": _g(
        "Fuite de données : le modèle voit à l'entraînement une information qu'il n'aurait pas eue au moment réel de la "
        "prédiction. Elle produit des scores irréalistes (F1 ou AUC de 0,95 à 1,00). Cause trouvée le 2026-10-09 : une "
        "cible FRED publiée avec un jour de retard dont le label était déjà contenu dans les cours du jour.",
        "Data leak: in training the model sees information it would not have had at the real prediction time. It yields "
        "unrealistic scores (F1 or AUC of 0.95 to 1.00). Cause found on 2026-10-09: a FRED target published one day late "
        "whose label was already in the day's prices."),
    "alignment": _g(
        "Alignement temporel : retarde d'une ou plusieurs barres les séries de marché dont les dates recouvrent déjà la "
        "fenêtre du label (cible FRED publiée en retard, horodatage fournisseur décalé). Décidé une fois par run et rejoué "
        "à l'identique en prédiction live.",
        "Time alignment: delays by one or more bars the market series whose dates already overlap the label window (a late "
        "FRED target, a shifted provider timestamp). Decided once per run and replayed identically in live prediction."),
    "publication_lag": _g(
        "Délai de publication : temps entre la période qu'une statistique décrit et sa publication (1 jour pour un taux du "
        "Trésor, ~20 jours pour l'inflation, ~30 jours pour le PIB). Une donnée n'entre dans le modèle qu'à sa date de "
        "publication, jamais avant.",
        "Publication lag: time between the period a statistic describes and its release (1 day for a Treasury rate, ~20 "
        "days for inflation, ~30 days for GDP). A data point enters the model only on its release date, never before."),
    "vintage": _g(
        "Millésime (vintage) : les statistiques macro sont révisées après leur publication. NFCI, par exemple, réécrit tout son "
        "passé à chaque publication. Utiliser le dernier millésime donne au modèle des valeurs qui n'existaient pas encore ; "
        "seule la voie ALFRED (clé API FRED) restitue les valeurs telles que publiées.",
        "Vintage: macro statistics are revised after release. NFCI, for instance, rewrites its whole past at every "
        "release. Using the latest vintage gives the model values that did not exist yet; only the ALFRED route (FRED API "
        "key) restores the values as first published."),
    "suspect_result": _g(
        "Résultat suspect : F1 directionnel ≥ 0,80 ou AUC ≥ 0,85. Aucun marché liquide ne se prédit à ce niveau : le score est "
        "traité comme une anomalie de données. Un tel modèle ne devient jamais champion.",
        "Suspect result: directional F1 ≥ 0.80 or AUC ≥ 0.85. No liquid market is predictable at that level: the score is "
        "treated as a data anomaly. Such a model never becomes champion."),

    # ------------------------------------------------------------------ données et qualité
    "history_depth": _g(
        "Historique minimum : nombre d'années de données exigé pour entraîner sur une cible. Les cibles plus récentes sont "
        "grisées dans la page Lancer (par défaut 10 ans, réglable de 3 à 40).",
        "Minimum history: number of years of data required to train on a target. More recent targets are greyed out in the "
        "Launch page (10 years by default, adjustable from 3 to 40)."),
    "coverage": _g(
        "Couverture : part des jours ouvrés d'une série effectivement renseignés. Sous 85 %, la série est écartée des "
        "features (cas des cryptos récentes : BTC depuis 2014, ETH depuis 2017).",
        "Coverage: share of a series' business days actually populated. Under 85% the series is dropped from the features "
        "(the case of recent cryptos: BTC since 2014, ETH since 2017)."),
    "frozen_prices": _g(
        "Cours figés : plus de N clôtures identiques d'affilée (4 par défaut). Signe d'une cotation arrêtée, mais aussi, à "
        "tort, de certains ETF obligataires très calmes.",
        "Frozen prices: more than N identical closes in a row (4 by default). A sign of a halted quote, but also, wrongly, "
        "of some very calm bond ETFs."),
    "aberrant_return": _g(
        "Rendement aberrant : variation à plus de 40 écarts robustes du reste de la série, souvent un tick faux. Les séries "
        "FRED en sont dispensées : leurs chocs (COVID, repo 2019) sont réels.",
        "Aberrant return: a change beyond 40 robust deviations from the rest of the series, often a bad tick. FRED series "
        "are exempt: their shocks (COVID, 2019 repo) are real."),
    "training_only": _g(
        "Donnée d'entraînement seulement : série macro utilisée comme feature pour les modèles, jamais proposée comme "
        "cible. Visible dans la page Macro avec un badge, mais pas exposée comme un actif.",
        "Training-only data: a macro series used as a model feature, never offered as a target. Shown on the Macro page "
        "with a badge, but not exposed as an asset."),

    # ------------------------------------------------------------------ classes d'actifs
    "asset_equity": _g(
        "Equity (actions) : titres de propriété d'une entreprise cotée. Une cible equity peut être directionnelle ou alpha "
        "(face à l'indice de sa place de cotation).",
        "Equity (stocks): ownership shares of a listed company. An equity target can be directional or alpha (against the "
        "index of its listing venue)."),
    "asset_index": _g(
        "Indice : panier de titres résumé en un chiffre (S&P 500, CAC 40, Nikkei 225...). Inclut les indices de volatilité "
        "(VIX), qui mesurent l'inquiétude attendue plutôt qu'un prix.",
        "Index: a basket of securities summarised in one number (S&P 500, CAC 40, Nikkei 225...). Includes volatility "
        "indices (VIX), which measure expected anxiety rather than a price."),
    "asset_crypto": _g(
        "Cryptomonnaie : actif numérique coté 24 h sur 24, 7 jours sur 7. Son historique est court (2014 pour le bitcoin) et "
        "ses cours sont datés en UTC.",
        "Cryptocurrency: a digital asset quoted 24/7. Its history is short (2014 for bitcoin) and its prices are dated in "
        "UTC."),
    "asset_fx": _g(
        "Devises (FX) : taux de change entre deux monnaies (EUR/USD) ou indice du dollar (DXY). Marché ouvert 24 h en semaine, "
        "dont l'horodatage varie selon le fournisseur.",
        "Currencies (FX): exchange rate between two currencies (EUR/USD) or the dollar index (DXY). A market open 24 hours on "
        "weekdays, whose timestamps vary by provider."),
    "asset_rates": _g(
        "Taux et crédit : rendements des obligations d'État (Trésor américain 2 à 30 ans), écarts de crédit (spreads), taux "
        "directeurs. Un taux qui monte signifie un prix d'obligation qui baisse.",
        "Rates and credit: government bond yields (US Treasury 2 to 30 years), credit spreads, policy rates. A rising "
        "rate means a falling bond price."),
    "asset_etf": _g(
        "ETF : fonds coté qui réplique un indice ou un panier (secteur, pays, obligations, matières premières) et s'échange "
        "comme une action.",
        "ETF: a listed fund that tracks an index or basket (sector, country, bonds, commodities) and trades like a stock."),
    "asset_commodity": _g(
        "Matières premières : or, pétrole, blé, café... suivies par leurs contrats à terme (futures), dont l'échéance change "
        "et qui peuvent même passer sous zéro (pétrole, avril 2020).",
        "Commodities: gold, oil, wheat, coffee... tracked through their futures contracts, whose expiry rolls over and which "
        "can even fall below zero (oil, April 2020)."),

    # ------------------------------------------------------------------ suivi et application
    "champion": _g(
        "Champion : le modèle en titre pour une cible et un horizon. Un challenger (nouveau run) ne le remplace que s'il "
        "fait strictement mieux en F1 directionnel sur le même holdout ; un champion suspect est remplacé d'office.",
        "Champion: the model in title for a target and horizon. A challenger (new run) replaces it only if it does "
        "strictly better in directional F1 on the same holdout; a suspect champion is replaced outright."),
    "live_tracking": _g(
        "Suivi live : à chaque lancement de l'app, chaque modèle entraîné prédit sur les données du jour. Les prédictions "
        "sont ensuite comparées à la réalité une fois l'horizon écoulé, sans jamais être réécrites.",
        "Live tracking: at each app launch, every trained model predicts on the day's data. The predictions are then "
        "compared with reality once the horizon has elapsed, and never rewritten."),
}

# Rubrique de chaque terme (existants et nouveaux). Un terme absent tombe dans « Suivi et application ».
TERM_CATEGORY: dict[str, str] = {
    **{k: "targets" for k in ("target_directional", "target_alpha", "benchmark", "beta", "four_moves",
                              "direction_vs_intensity", "horizon", "flat_thr", "persistence_baseline", "regime")},
    **{k: "metrics" for k in ("auc", "f1", "f1_dir", "acc_dir", "balanced_accuracy", "mcc", "brier", "ece", "hit_rate",
                              "live_reliability", "calibration")},
    **{k: "stats" for k in ("p_value", "p_value_dm", "p_value_adjusted", "bh_fdr", "alpha_level", "spearman_holdout",
                            "n_trials", "diebold_mariano", "deflated_sharpe", "pbo", "conformal")},
    **{k: "validation" for k in ("walk_forward", "fold", "data_leak", "alignment", "publication_lag", "vintage",
                                 "suspect_result", "holdout", "purge", "embargo_enabled", "scheme", "n_groups",
                                 "k_test_groups", "uniqueness_weights", "track_stability")},
    **{k: "data" for k in ("history_depth", "coverage", "frozen_prices", "aberrant_return", "training_only",
                           "data_freshness", "data_quality_enabled", "equity_universe", "equity_min_history",
                           "equity_feature_exclusions", "equity_fundamentals", "asset_statistics", "asset_bar_windows",
                           "universe", "reduction")},
    **{k: "assets" for k in ("asset_equity", "asset_index", "asset_crypto", "asset_fx", "asset_rates", "asset_etf",
                             "asset_commodity")},
    **{k: "models" for k in ("technical", "interactions", "spike", "vol_models", "macro", "long_cycle", "egarch", "kalman",
                             "hmm", "heston_proxy", "vrp_proxy", "ar", "ma", "arma", "arima", "shap", "rfe", "lasso",
                             "SMOTE", "BorderlineSMOTE", "ADASYN", "SMOTETomek", "SMOTEENN", "XGBoost", "LightGBM",
                             "RandomForest", "GradientBoosting", "CatBoost", "stacking", "regime_detection_enabled",
                             "model_category_global", "model_category_per_regime", "model_category_stacking",
                             "regime_threshold_mode", "tuning_enabled", "optuna_select_top_k_per_horizon",
                             "technical_lookbacks", "staged_screening", "optuna_bounds")},
    **{k: "portfolio" for k in ("hrp", "black_litterman", "ledoit_wolf", "portfolio_contradictions", "portfolio_pairs",
                                "wealth_summary", "wealth_account_rules", "wealth_movements", "wealth_csv_import",
                                "wealth_simulation", "wealth_simulation_trials", "twr", "xirr", "pea", "cto", "dat")},
    **{k: "app" for k in ("champion", "live_tracking", "prediction_overview")},
}
