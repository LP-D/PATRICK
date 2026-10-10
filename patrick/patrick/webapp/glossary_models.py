"""Vocabulaire des pages Exploration, Deep learning et Reinforcement learning (bulles « ? » et page /vocabulary).

Même forme que `glossary_extra` : FR/EN pour chaque terme, une rubrique (`CATEGORY`), un libellé affiché (`LABELS`, chaînes FR/EN
fusionnées dans `i18n.STRINGS`). Fusionné dans `glossary.GLOSSARY` / `TERM_LABEL_KEYS` / `glossary_extra.TERM_CATEGORY`."""
from __future__ import annotations


def _g(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


GLOSSARY_MODELS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ Exploration
    "exp_rolling_corr": _g(
        "Corrélation glissante : corrélation recalculée sur une fenêtre qui avance. Elle montre si le lien entre deux actifs est "
        "stable ou change de régime. Une fenêtre de n observations fait fluctuer le résultat d'environ ±1/√n même si le vrai lien ne bouge pas.",
        "Rolling correlation: correlation recomputed on a moving window. It shows whether the link between two assets is stable or "
        "changes regime. A window of n observations makes the result fluctuate by about ±1/√n even when the true link is fixed."),
    "exp_stationarity": _g(
        "Stationnarité : une série est stationnaire quand sa moyenne et sa variance ne dérivent pas dans le temps. Un prix ne l'est "
        "presque jamais (il erre, c'est une racine unitaire) ; son rendement l'est presque toujours. La plupart des modèles statistiques "
        "supposent des variables stationnaires.",
        "Stationarity: a series is stationary when its mean and variance do not drift over time. A price almost never is (it wanders: "
        "a unit root); its return almost always is. Most statistical models assume stationary variables."),
    "exp_adf": _g(
        "ADF (Dickey-Fuller augmenté) : test dont l'hypothèse de départ est une racine unitaire (série non stationnaire). Une p-value "
        "inférieure à 5 % rejette cette hypothèse : la série est stationnaire.",
        "ADF (augmented Dickey-Fuller): a test whose starting hypothesis is a unit root (non-stationary series). A p-value below 5% "
        "rejects it: the series is stationary."),
    "exp_kpss": _g(
        "KPSS : test dont l'hypothèse de départ est la stationnarité, à l'inverse de l'ADF. Une p-value inférieure à 5 % la rejette : "
        "la série n'est pas stationnaire. On croise ADF et KPSS pour éviter de conclure sur un seul.",
        "KPSS: a test whose starting hypothesis is stationarity, the opposite of ADF. A p-value below 5% rejects it: the series is not "
        "stationary. ADF and KPSS are crossed so that no conclusion rests on one alone."),
    "exp_hurst": _g(
        "Exposant de Hurst : mesure la mémoire d'une série. Environ 0,5 : marche aléatoire (aucune mémoire exploitable). Moins de 0,45 : "
        "retour à la moyenne (les écarts se corrigent). Plus de 0,55 : tendance persistante (les mouvements se prolongent).",
        "Hurst exponent: measures a series' memory. About 0.5: random walk (no usable memory). Below 0.45: mean reversion (gaps "
        "correct themselves). Above 0.55: persistent trend (moves tend to continue)."),
    "exp_acf": _g(
        "Autocorrélation (ACF) : corrélation d'une série avec elle-même décalée de k périodes. Hors de la bande ±1,96/√n, le décalage "
        "est significatif isolément. La PACF retire l'effet des décalages intermédiaires. Test de Ljung-Box : teste tous les décalages "
        "d'un coup ; ARCH-LM : teste les grappes de volatilité (les gros mouvements se suivent).",
        "Autocorrelation (ACF): correlation of a series with itself shifted by k periods. Outside the ±1.96/√n band the lag is "
        "individually significant. PACF removes the effect of intermediate lags. Ljung-Box test: tests all lags at once; ARCH-LM: tests "
        "volatility clustering (big moves follow each other)."),
    "exp_xcorr": _g(
        "Corrélation croisée : corrélation entre un actif et un autre décalé de k périodes. Elle révèle qui précède qui : si B décalé de "
        "3 jours corrèle fortement avec A, le passé de B éclaire A trois jours plus tard.",
        "Cross-correlation: correlation between one asset and another shifted by k periods. It reveals who leads whom: if B shifted by "
        "3 days correlates strongly with A, B's past informs A three days later."),
    "exp_granger": _g(
        "Causalité de Granger : le passé de X aide-t-il à prédire Y au-delà du passé de Y lui-même ? Un pouvoir prédictif linéaire, "
        "jamais la preuve d'une cause économique : deux actifs réagissant à une même nouvelle à des vitesses différentes la déclenchent.",
        "Granger causality: does X's past help predict Y beyond Y's own past? Linear predictive power, never proof of an economic "
        "cause: two assets reacting to the same news at different speeds will trigger it."),
    "exp_coint": _g(
        "Cointégration : deux séries non stationnaires sont cointégrées si une combinaison linéaire de leurs log-prix est stationnaire : "
        "elles peuvent s'éloigner mais reviennent l'une vers l'autre. Base du trading de paires. Test d'Engle-Granger ; demi-vie = temps "
        "moyen pour combler la moitié de l'écart.",
        "Cointegration: two non-stationary series are cointegrated if a linear combination of their log prices is stationary: they can "
        "drift apart but revert toward each other. Basis of pairs trading. Engle-Granger test; half-life = average time to close half "
        "of the gap."),
    "exp_tail": _g(
        "Dépendance de queue : probabilité que deux actifs soient ensemble dans leurs pires (ou meilleurs) jours. La corrélation moyenne "
        "peut être modérée alors que les krachs sont communs ; c'est le risque que la diversification ne protège pas.",
        "Tail dependence: probability that two assets are together in their worst (or best) days. Average correlation can be moderate "
        "while crashes are shared; it is the risk that diversification does not cover."),
    "exp_pca": _g(
        "Analyse en composantes principales (ACP) : décompose les mouvements d'un ensemble d'actifs en facteurs indépendants classés par "
        "variance expliquée. Si le premier facteur domine (souvent « le marché »), les actifs bougent surtout ensemble.",
        "Principal component analysis (PCA): decomposes the movements of a set of assets into independent factors ranked by explained "
        "variance. If the first factor dominates (often \"the market\"), the assets mostly move together."),
    "exp_var_es": _g(
        "VaR (valeur à risque) et ES (perte moyenne au-delà) : la VaR à 95 % est la perte qui n'est dépassée que dans 5 % des périodes ; "
        "l'ES est la perte moyenne quand elle l'est. L'ES dit la gravité de la queue, que la VaR ignore.",
        "VaR (value at risk) and ES (expected shortfall): 95% VaR is the loss exceeded in only 5% of periods; ES is the average loss "
        "when it is exceeded. ES conveys the tail's severity, which VaR ignores."),
}

# ---------------------------------------------------------------------------------------------------------------------------------
# Deep learning (page /dl) : réseaux et réglages. Rubrique « models ». Les termes des architectures sont leur propre libellé.
# ---------------------------------------------------------------------------------------------------------------------------------
GLOSSARY_DL: dict[str, dict[str, str]] = {
    "dl_networks": _g(
        "Réseaux de neurones : modèles composés de couches de calcul empilées, dont les poids sont appris par descente de gradient. Dans "
        "PATRICK ils sont des algorithmes de plus : mêmes folds walk-forward, mêmes sélection de variables et tuning que les arbres. Sur des "
        "données de marché bruitées, les arbres font souvent aussi bien : rien ne garantit qu'un réseau fasse mieux, le classement le dira.",
        "Neural networks: models made of stacked computation layers whose weights are learned by gradient descent. In PATRICK they are "
        "extra algorithms: same walk-forward folds, same feature selection and tuning as trees. On noisy market data trees often do as "
        "well: nothing guarantees a network does better, the leaderboard will tell."),
    "MLP": _g(
        "MLP (perceptron multicouche) : le réseau de base, des couches de neurones qui lisent UNE ligne de variables à la fois. Rapide, il "
        "n'a aucune notion d'ordre des jours.",
        "MLP (multilayer perceptron): the basic network, layers of neurons reading ONE row of features at a time. Fast, with no notion of "
        "the order of days."),
    "GRU": _g(
        "GRU (unité récurrente à porte) : réseau récurrent qui lit une fenêtre de jours consécutifs et garde une mémoire de ce qu'il a vu. "
        "Plus léger que le LSTM, souvent aussi bon.",
        "GRU (gated recurrent unit): a recurrent network that reads a window of consecutive days and keeps a memory of what it has seen. "
        "Lighter than LSTM, often as good."),
    "LSTM": _g(
        "LSTM (mémoire longue à court terme) : réseau récurrent à mémoire plus fine que le GRU, plus lent à entraîner ; conçu pour garder une "
        "information utile sur de longues fenêtres.",
        "LSTM (long short-term memory): a recurrent network with finer memory than GRU, slower to train; designed to keep useful "
        "information over long windows."),
    "CNN1D": _g(
        "CNN1D : réseau à convolutions causales (un filtre glisse sur la fenêtre sans jamais regarder vers l'avenir). Détecte des motifs "
        "locaux dans la séquence, très rapide à entraîner.",
        "CNN1D: a network with causal convolutions (a filter slides over the window without ever looking ahead). Detects local patterns in "
        "the sequence, very fast to train."),
    "Transformer": _g(
        "Transformer : réseau à attention, où chaque jour de la fenêtre pondère tous les autres. Le plus expressif et le plus gourmand en "
        "données : à réserver aux cibles avec un long historique, sinon il surapprend.",
        "Transformer: an attention network where each day of the window weighs all the others. The most expressive and the most "
        "data-hungry: keep it for targets with a long history, otherwise it overfits."),
    "dl_hidden_size": _g(
        "Taille cachée : nombre de neurones par couche (ou taille de l'état de mémoire d'un GRU/LSTM). Plus grand = plus de capacité, mais "
        "plus de risque de surapprendre le bruit.",
        "Hidden size: number of neurons per layer (or size of a GRU/LSTM memory state). Larger = more capacity, but more risk of fitting noise."),
    "dl_n_layers": _g(
        "Couches : profondeur du réseau. Une ou deux couches suffisent presque toujours sur des données de marché ; au-delà, l'entraînement "
        "devient instable et le surapprentissage plus probable.",
        "Layers: depth of the network. One or two layers almost always suffice on market data; beyond that training gets unstable and "
        "overfitting more likely."),
    "dl_dropout": _g(
        "Dropout : à chaque pas d'entraînement, une fraction des neurones est éteinte au hasard. Force le réseau à ne pas dépendre d'un seul "
        "chemin : c'est une régularisation contre le surapprentissage. 0,2 = 20 % des neurones éteints.",
        "Dropout: at each training step a fraction of neurons is randomly switched off. Forces the network not to rely on a single path: "
        "a regularization against overfitting. 0.2 = 20% of neurons switched off."),
    "dl_lookback": _g(
        "Fenêtre (lookback) : nombre de lignes consécutives (barres) lues par un réseau séquentiel pour prédire une date. 20 = les 20 "
        "dernières barres. N'a pas d'effet sur le MLP.",
        "Window (lookback): number of consecutive rows (bars) a sequence network reads to predict a date. 20 = the last 20 bars. No effect "
        "on the MLP."),
    "dl_n_heads": _g(
        "Têtes d'attention : nombre de façons parallèles dont le Transformer regarde la fenêtre. La taille cachée est arrondie à un "
        "multiple de ce nombre.",
        "Attention heads: number of parallel ways the Transformer looks at the window. Hidden size is rounded to a multiple of it."),
    "dl_kernel_size": _g(
        "Noyau (CNN1D) : largeur du filtre de convolution, en barres. Les dilatations successives (1, 2, 4...) élargissent le champ de vue.",
        "Kernel (CNN1D): width of the convolution filter, in bars. Successive dilations (1, 2, 4...) widen the field of view."),
    "dl_epochs": _g(
        "Époques maximum : nombre de passages complets sur les données d'entraînement. C'est un plafond : l'arrêt anticipé interrompt "
        "l'entraînement dès que la validation ne progresse plus.",
        "Max epochs: number of full passes over the training data. A ceiling: early stopping ends training as soon as validation stops "
        "improving."),
    "dl_batch_size": _g(
        "Taille de lot : nombre de lignes vues avant chaque mise à jour des poids. Petit = mises à jour bruitées mais fréquentes ; grand = "
        "stables mais moins nombreuses.",
        "Batch size: number of rows seen before each weight update. Small = noisy but frequent updates; large = stable but fewer."),
    "dl_learning_rate": _g(
        "Taux d'apprentissage : taille du pas de chaque mise à jour des poids. Trop grand, l'entraînement diverge ; trop petit, il stagne. "
        "Valeurs usuelles : 0,0003 à 0,003.",
        "Learning rate: size of each weight update step. Too large, training diverges; too small, it stalls. Usual values: 0.0003 to 0.003."),
    "dl_weight_decay": _g(
        "Décroissance des poids : pénalité qui ramène les poids vers zéro à chaque pas. Régularisation douce contre le surapprentissage.",
        "Weight decay: a penalty pulling weights toward zero at each step. A soft regularization against overfitting."),
    "dl_patience": _g(
        "Patience (arrêt anticipé) : nombre d'époques sans amélioration de la validation avant d'arrêter l'entraînement. Les meilleurs poids "
        "sont restaurés. 0 = pas d'arrêt anticipé. La validation est la fin TEMPORELLE de l'entraînement, jamais un tirage au hasard.",
        "Patience (early stopping): number of epochs without validation improvement before training stops. The best weights are restored. "
        "0 = no early stopping. Validation is the TEMPORAL end of the training set, never a random draw."),
    "dl_val_fraction": _g(
        "Fraction de validation : part finale (dans le temps) des lignes d'entraînement réservée à l'arrêt anticipé. Ignorée si la patience "
        "est 0 ou si les lignes sont trop peu nombreuses.",
        "Validation fraction: final (in time) share of the training rows kept for early stopping. Ignored if patience is 0 or rows are "
        "too few."),
    "dl_grad_clip": _g(
        "Coupure du gradient : plafonne la norme du gradient à chaque pas pour éviter qu'un lot aberrant ne casse l'entraînement. 0 = désactivée.",
        "Gradient clipping: caps the gradient norm at each step so an outlier batch cannot wreck training. 0 = off."),
    "dl_class_weight": _g(
        "Pondération des classes : « équilibrée » donne plus de poids aux classes rares (forte baisse, forte hausse) pour que le réseau "
        "ne les ignore pas ; « aucune » laisse les fréquences brutes.",
        "Class weighting: \"balanced\" gives more weight to rare classes (strong fall, strong rise) so the network does not ignore them; "
        "\"none\" keeps raw frequencies."),
    "dl_n_seeds": _g(
        "Réseaux moyennés : nombre de réseaux entraînés avec des graines différentes dont on moyenne les probabilités. Réduit la part de "
        "hasard de l'initialisation ; coût multiplié d'autant.",
        "Averaged networks: number of networks trained with different seeds whose probabilities are averaged. Reduces initialization "
        "luck; cost multiplied accordingly."),
    "dl_device": _g(
        "Appareil : « automatique » utilise la carte graphique (CUDA) si elle est disponible, sinon le processeur. Sur de petits réseaux, "
        "le processeur est souvent aussi rapide.",
        "Device: \"automatic\" uses the graphics card (CUDA) when available, otherwise the CPU. On small networks the CPU is often just as fast."),
    "dl_threads": _g(
        "Fils de calcul : nombre de fils utilisés par PyTorch dans le processus d'entraînement. 1 par défaut, comme les autres modèles du "
        "pipeline, pour ne pas se disputer le processeur avec les workers parallèles.",
        "Compute threads: number of threads PyTorch uses in the training process. 1 by default, like the pipeline's other models, so as "
        "not to fight over the CPU with parallel workers."),
}

CATEGORY_DL: dict[str, str] = {k: "models" for k in GLOSSARY_DL}
LABELS_DL: dict[str, str] = {
    **{k: f"dl_f_{k[3:]}" for k in GLOSSARY_DL if k.startswith("dl_") and k != "dl_networks"},
    "dl_networks": "dl_sec_networks",
}


CATEGORY: dict[str, str] = {k: "stats" for k in GLOSSARY_MODELS}

# Libellé affiché (page /vocabulary, titre des bulles) : clé i18n -> FR/EN.
LABELS: dict[str, str] = {k: f"exp_gl_{k[4:]}" for k in GLOSSARY_MODELS}

LABEL_STRINGS: dict[str, dict[str, str]] = {
    "exp_gl_rolling_corr": _g("Corrélation glissante", "Rolling correlation"),
    "exp_gl_stationarity": _g("Stationnarité", "Stationarity"),
    "exp_gl_adf": _g("ADF (Dickey-Fuller augmenté)", "ADF (augmented Dickey-Fuller)"),
    "exp_gl_kpss": _g("KPSS", "KPSS"),
    "exp_gl_hurst": _g("Exposant de Hurst", "Hurst exponent"),
    "exp_gl_acf": _g("Autocorrélation (ACF, PACF)", "Autocorrelation (ACF, PACF)"),
    "exp_gl_xcorr": _g("Corrélation croisée", "Cross-correlation"),
    "exp_gl_granger": _g("Causalité de Granger", "Granger causality"),
    "exp_gl_coint": _g("Cointégration", "Cointegration"),
    "exp_gl_tail": _g("Dépendance de queue", "Tail dependence"),
    "exp_gl_pca": _g("Analyse en composantes principales", "Principal component analysis"),
    "exp_gl_var_es": _g("VaR et ES", "VaR and ES"),
}
