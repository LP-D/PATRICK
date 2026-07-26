"""Explications courtes (jargon financier/ML expliqué au moins une fois) affichées
dans l'interface web via un petit encart cliquable — pas de logique métier ici,
juste du texte, gardé à part de `forms.py` pour rester lisible. Bilingue (FR/EN),
résolu à la langue courante dans `app.py` avant d'être envoyé au template.
"""
from __future__ import annotations

GLOSSARY: dict[str, dict[str, str]] = {
    # Familles de features
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
               "série (EGARCH, Kalman, HMM, AR/MA/ARMA/ARIMA...) — voir le "
               "détail de chacun ci-dessous."),
        "en": ("Volatility/time-dynamics models applied to every series (EGARCH, "
               "Kalman, HMM, AR/MA/ARMA/ARIMA...) — see each one's detail below."),
    },
    "macro": {
        "fr": ("Jointures des séries macroéconomiques FRED (taux, spreads, "
               "conditions financières) alignées sur le calendrier de marché."),
        "en": ("Joins of FRED macroeconomic series (rates, spreads, financial "
               "conditions) aligned on the market calendar."),
    },

    # Modèles de la famille vol_models
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
               "régime de plus forte variance (proxy de \"stress\" de marché)."),
        "en": ("HMM (Hidden Markov Model) with 2 gaussian regimes: estimates, "
               "causally at each point in time, the probability of being in the "
               "highest-variance regime (a \"market stress\" proxy)."),
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
        "fr": ("AR (AutoRégressif) : modélise un rendement comme combinaison linéaire de "
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

    # Méthodes de sélection de features
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

    # Samplers (rééquilibrage des classes)
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

    # Algorithmes de classification
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

    # Autres options du pipeline
    "purge": {
        "fr": ("Purge (walk-forward) : retire les lignes d'entraînement trop proches "
               "de la frontière train/test, pour éviter qu'une fuite d'information "
               "liée à l'horizon de prédiction ne biaise l'évaluation."),
        "en": ("Purge (walk-forward): removes training rows too close to the "
               "train/test boundary, to avoid a prediction-horizon information "
               "leak biasing the evaluation."),
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
    "tuning_enabled": {
        "fr": ("Tuning Optuna : affine automatiquement les hyperparamètres "
               "des meilleures configs trouvées par la grille, via une "
               "recherche bayésienne (Optuna), avant l'export final."),
        "en": ("Optuna tuning: automatically refines the hyperparameters of the "
               "best configs found by the grid, via a Bayesian search (Optuna), "
               "before the final export."),
    },
}
