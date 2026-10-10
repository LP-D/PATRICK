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


# ---------------------------------------------------------------------------------------------------------------------------------
# Reinforcement learning (page /rl). Rubrique « models » ; les noms d'algorithmes sont leur propre libellé.
# ---------------------------------------------------------------------------------------------------------------------------------
GLOSSARY_RL: dict[str, dict[str, str]] = {
    "rl_agent": _g(
        "Reinforcement learning (apprentissage par renforcement) : un agent choisit une action (ici une POSITION : vendre à découvert, "
        "rester à plat, acheter), reçoit une récompense (le gain ou la perte de la période, frais déduits) et ajuste sa façon de décider "
        "pour en accumuler davantage. Contrairement à un modèle de classification, il n'apprend pas à prédire un mouvement mais à AGIR, "
        "en tenant compte des coûts de ses propres décisions.",
        "Reinforcement learning: an agent chooses an action (here a POSITION: short, flat, long), receives a reward (the period's gain or "
        "loss, net of fees) and adjusts how it decides to accumulate more. Unlike a classification model it does not learn to predict a "
        "move but to ACT, accounting for the cost of its own decisions."),
    "PPO": _g(
        "PPO (Proximal Policy Optimization) : l'algorithme de référence, stable et polyvalent. Il apprend une politique (probabilités "
        "d'agir) par petites mises à jour bornées, sur des paquets d'expérience récente. Actions discrètes ou continues.",
        "PPO (Proximal Policy Optimization): the reference algorithm, stable and versatile. It learns a policy (action probabilities) by "
        "small bounded updates on batches of recent experience. Discrete or continuous actions."),
    "A2C": _g(
        "A2C (Advantage Actor-Critic) : un acteur (la politique) et un critique (l'estimation de valeur) mis à jour ensemble sur de "
        "courts paquets d'expérience. Plus simple et plus rapide que PPO, plus bruité.",
        "A2C (Advantage Actor-Critic): an actor (the policy) and a critic (the value estimate) updated together on short batches of "
        "experience. Simpler and faster than PPO, noisier."),
    "DQN": _g(
        "DQN (Deep Q-Network) : apprend la valeur future attendue de chaque action discrète et prend la meilleure ; réutilise des "
        "expériences passées (tampon). Actions discrètes seulement.",
        "DQN (Deep Q-Network): learns the expected future value of each discrete action and takes the best; reuses past experience "
        "(buffer). Discrete actions only."),
    "SAC": _g(
        "SAC (Soft Actor-Critic) : apprend une position CONTINUE (une fraction de capital) en maximisant récompense et entropie "
        "(curiosité), avec un tampon d'expériences. Action continue seulement.",
        "SAC (Soft Actor-Critic): learns a CONTINUOUS position (a fraction of capital) by maximizing reward and entropy (curiosity), "
        "with an experience buffer. Continuous action only."),
    "rl_reward": _g(
        "Récompense : le signal qui guide l'apprentissage. « Croissance du capital (log) » : le logarithme du rendement net, ce qui compte "
        "composé dans le temps. « P&L net » : le gain brut moins les frais. « Sharpe différentiel » : la variation instantanée du ratio de "
        "Sharpe (Moody & Saffell), qui récompense la RÉGULARITÉ du rendement et pas seulement son niveau.",
        "Reward: the signal that guides learning. \"Capital growth (log)\": the log of the net return, which is what compounds over time. "
        "\"Net P&L\": gross gain minus fees. \"Differential Sharpe\": the instantaneous change of the Sharpe ratio (Moody & Saffell), "
        "rewarding the REGULARITY of return rather than just its level."),
    "rl_action_space": _g(
        "Actions : « discrètes » = l'agent choisit parmi quelques niveaux de position (par exemple −1, 0, +1) ; « continue » = il choisit "
        "n'importe quelle fraction de capital entre −1 et +1. DQN exige du discret, SAC du continu ; PPO et A2C font les deux.",
        "Actions: \"discrete\" = the agent picks among a few position levels (e.g. −1, 0, +1); \"continuous\" = it picks any capital "
        "fraction between −1 and +1. DQN needs discrete, SAC continuous; PPO and A2C do both."),
    "rl_cost": _g(
        "Frais et glissement : coût de chaque changement de position, en points de base (1 point de base = 0,01 %) du montant échangé. "
        "Passer de long à vendeur coûte deux fois le coût unitaire. Sans coûts réalistes, un agent apprend à s'agiter.",
        "Fees and slippage: cost of each position change, in basis points (1 basis point = 0.01%) of the amount traded. Going from long "
        "to short costs twice the unit cost. Without realistic costs an agent learns to churn."),
    "rl_leverage": _g(
        "Levier maximal : plafond de la position, en multiple du capital. 1 = capital investi une fois ; 2 = on peut détenir deux fois le "
        "capital (les gains, pertes et frais sont doublés aussi).",
        "Max leverage: cap on the position, as a multiple of capital. 1 = capital invested once; 2 = one can hold twice the capital "
        "(gains, losses and fees double too)."),
    "rl_risk_aversion": _g(
        "Aversion au risque : pénalité proportionnelle au carré du rendement de la période, retirée à la récompense. Plus elle est élevée, "
        "plus l'agent préfère des positions qui limitent les grands mouvements.",
        "Risk aversion: a penalty proportional to the square of the period's return, subtracted from the reward. The higher it is, the "
        "more the agent prefers positions that limit large moves."),
    "rl_dsr_eta": _g(
        "Oubli du Sharpe différentiel : vitesse à laquelle la moyenne et la variance de référence oublient le passé. 0,01 = mémoire "
        "d'environ 100 périodes. Utilisé seulement par la récompense « Sharpe différentiel ».",
        "Differential Sharpe decay: speed at which the reference mean and variance forget the past. 0.01 = memory of about 100 periods. "
        "Used only by the \"Differential Sharpe\" reward."),
    "rl_obs_lookback": _g(
        "Lignes empilées : nombre de dates de variables (la dernière et les précédentes) présentées à l'agent. 1 = seulement aujourd'hui ; "
        "20 = les 20 dernières dates, pour qu'il perçoive une dynamique. Aucune ne dépasse la date de décision.",
        "Stacked rows: number of feature dates (the latest and earlier ones) shown to the agent. 1 = today only; 20 = the last 20 dates, "
        "so it can perceive a dynamic. None goes past the decision date."),
    "rl_episode": _g(
        "Épisode : un passage de l'agent sur un segment d'historique pendant l'entraînement. « Longueur d'épisode » = nombre de dates "
        "par passage (0 = tout le segment) ; avec un départ aléatoire, l'agent rejoue des périodes variées plutôt que toujours la même.",
        "Episode: one pass of the agent over a history segment during training. \"Episode length\" = number of dates per pass (0 = the "
        "whole segment); with a random start the agent replays varied periods rather than always the same one."),
    "rl_features": _g(
        "Variables observées : les mêmes variables causales que les pages machine learning (techniques, pics, macro, long cycle), "
        "calculées avec des fenêtres glissantes. EGARCH, HMM et interactions sont exclus : ajustés sur un échantillon, ils laisseraient "
        "passer de l'avenir. Les variables retenues sont choisies par pli sur l'entraînement seul.",
        "Observed features: the same causal features as the machine-learning pages (technical, spike, macro, long cycle), computed with "
        "rolling windows. EGARCH, HMM and interactions are excluded: fitted on a sample, they would let the future through. The features "
        "kept are chosen per fold on training data only."),
    "rl_policy": _g(
        "Réseau de l'agent : le petit réseau de neurones qui transforme l'observation en décision. Couches et neurones plus nombreux = "
        "plus de capacité, mais davantage de risque de surapprendre le passé.",
        "Agent network: the small neural network turning the observation into a decision. More layers and units = more capacity, but more "
        "risk of overfitting the past."),
    "rl_learning_rate": _g(
        "Taux d'apprentissage : taille de chaque mise à jour du réseau. Trop grand, l'apprentissage diverge ; trop petit, il stagne. "
        "Valeurs usuelles : 0,0001 à 0,001.",
        "Learning rate: size of each network update. Too large, learning diverges; too small, it stalls. Usual values: 0.0001 to 0.001."),
    "rl_gamma": _g(
        "Gamma (facteur d'actualisation) : poids des récompenses futures par rapport aux immédiates. 0,99 = l'agent se soucie des "
        "~100 prochaines périodes ; 0 = il ne regarde que la période suivante.",
        "Gamma (discount factor): weight of future rewards relative to immediate ones. 0.99 = the agent cares about the next ~100 "
        "periods; 0 = it only looks at the next period."),
    "rl_timesteps": _g(
        "Pas d'entraînement : nombre total de décisions simulées pendant l'entraînement d'UN agent sur UN pli. Plus il y en a, plus "
        "l'agent a vu de situations (et plus le run est long) ; trop peu et il n'a pas appris.",
        "Training steps: total number of simulated decisions while training ONE agent on ONE fold. The more there are, the more situations "
        "the agent has seen (and the longer the run); too few and it has not learned."),
    "rl_n_steps": _g(
        "Pas par mise à jour (PPO, A2C) : nombre de décisions collectées avant chaque mise à jour du réseau. La taille de lot de PPO "
        "ne peut pas la dépasser.",
        "Steps per update (PPO, A2C): number of decisions collected before each network update. PPO's batch size cannot exceed it."),
    "rl_ent_coef": _g(
        "Coefficient d'entropie (PPO, A2C) : récompense la diversité des actions pour que l'agent continue d'explorer. 0 = aucune "
        "incitation à explorer ; une valeur trop haute rend la politique aléatoire.",
        "Entropy coefficient (PPO, A2C): rewards action diversity so the agent keeps exploring. 0 = no incentive to explore; too high "
        "makes the policy random."),
    "rl_clip_range": _g(
        "Plage de coupure (PPO) : limite de combien la politique peut changer en une mise à jour. 0,2 = ±20 %. Garde l'apprentissage stable.",
        "Clip range (PPO): limit on how much the policy may change in one update. 0.2 = ±20%. Keeps learning stable."),
    "rl_gae_lambda": _g(
        "Lambda GAE (PPO, A2C) : compromis entre biais et bruit dans l'estimation de l'avantage d'une action. 0,95 est le choix usuel.",
        "GAE lambda (PPO, A2C): trade-off between bias and noise in estimating an action's advantage. 0.95 is the usual choice."),
    "rl_buffer": _g(
        "Tampon d'expériences (DQN, SAC) : mémoire des décisions passées, rejouées pour apprendre. « Pas avant apprentissage » = nombre "
        "d'expériences accumulées avant la première mise à jour ; « fréquence d'entraînement » = une mise à jour toutes les N décisions.",
        "Experience buffer (DQN, SAC): memory of past decisions, replayed to learn. \"Steps before learning\" = experiences gathered "
        "before the first update; \"training frequency\" = one update every N decisions."),
    "rl_exploration": _g(
        "Part d'exploration (DQN) : fraction de l'entraînement pendant laquelle la probabilité d'essayer une action au hasard diminue "
        "de 100 % à 5 %. Tau (SAC) : vitesse de recopie du réseau cible, 0,005 = très lente et stable.",
        "Exploration fraction (DQN): share of training over which the probability of trying a random action falls from 100% to 5%. Tau "
        "(SAC): speed of copying to the target network, 0.005 = very slow and stable."),
    "rl_seeds": _g(
        "Agents moyennés : nombre d'agents entraînés avec des graines différentes ; la position de l'ensemble est la MOYENNE de leurs "
        "positions. Réduit la part de hasard de l'initialisation, au prix d'un coût multiplié.",
        "Averaged agents: number of agents trained with different seeds; the ensemble's position is the MEAN of their positions. Reduces "
        "initialization luck, at the cost of multiplying the run time."),
    "rl_walkforward": _g(
        "Validation walk-forward du RL : l'agent s'entraîne sur le passé, joue la période suivante sans jamais l'avoir vue, puis on "
        "avance. Les périodes jouées sont recollées en une seule courbe hors échantillon. Un jour d'écart sépare l'entraînement du test, "
        "et la position tenue en fin de pli est reportée au pli suivant.",
        "RL walk-forward validation: the agent trains on the past, plays the next period without ever having seen it, then we move "
        "forward. The periods played are stitched into one out-of-sample curve. One day separates training from test, and the position "
        "held at the end of a fold is carried into the next."),
    "rl_retrain": _g(
        "Fenêtre d'entraînement : « élargie » = tout le passé disponible à chaque pli ; « glissante » = seulement les N dernières dates "
        "(oublie le très ancien, s'adapte plus vite, voit moins de données).",
        "Training window: \"expanding\" = all the available past at each fold; \"rolling\" = only the last N dates (forgets the very "
        "old, adapts faster, sees less data)."),
    "rl_bootstrap": _g(
        "Bootstrap : on tire au hasard, par blocs de dates consécutives, de nombreuses versions de la période test et on recalcule l'écart "
        "de Sharpe entre l'agent et la référence à chaque fois. La dispersion donne l'intervalle d'incertitude ; la part des tirages où "
        "l'agent ne fait pas mieux est la p-value unilatérale.",
        "Bootstrap: many versions of the test period are drawn at random, in blocks of consecutive dates, and the Sharpe gap between the "
        "agent and the benchmark is recomputed each time. The spread gives the uncertainty interval; the share of draws where the agent "
        "does not do better is the one-sided p-value."),
    "rl_psr": _g(
        "Probabilité que le Sharpe vrai soit positif (PSR, Bailey & López de Prado) : tient compte de la longueur de la période et de la "
        "forme des rendements (asymétrie, queues épaisses). Le Sharpe déflaté la corrige en plus du nombre de configurations essayées "
        "sur la cible.",
        "Probability that the true Sharpe is positive (PSR, Bailey & López de Prado): accounts for the length of the period and the "
        "shape of returns (skew, fat tails). The deflated Sharpe further corrects it for the number of configurations tried on the target."),
    "rl_turnover": _g(
        "Rotation : part du capital échangée par an (somme des changements de position, annualisée). Une rotation de 50 = l'agent "
        "renouvelle 50 fois son capital par an : les frais comptent beaucoup.",
        "Turnover: share of capital traded per year (sum of position changes, annualized). A turnover of 50 = the agent turns its capital "
        "over 50 times a year: fees matter a lot."),
    "rl_baselines": _g(
        "Références : « acheter et garder » (position 1 en permanence, sans frais), « momentum 20 j » (long si l'actif a monté sur les 20 "
        "derniers jours, vendeur sinon, mêmes frais que l'agent) et « à plat » (jamais investi). Un agent qui ne bat pas ces règles "
        "simples n'apporte rien.",
        "Baselines: \"buy and hold\" (position 1 permanently, no fees), \"20-day momentum\" (long if the asset rose over the last 20 "
        "days, short otherwise, same fees as the agent) and \"flat\" (never invested). An agent that does not beat these simple rules "
        "adds nothing."),
}

CATEGORY_RL: dict[str, str] = {k: "models" for k in GLOSSARY_RL}
LABELS_RL: dict[str, str] = {
    "rl_agent": "rlp_title", "PPO": "", "A2C": "", "DQN": "", "SAC": "",
    "rl_reward": "rlp_f_reward", "rl_action_space": "rlp_f_action_space", "rl_cost": "rlp_f_cost_bps", "rl_leverage": "rlp_f_max_leverage",
    "rl_risk_aversion": "rlp_f_risk_aversion", "rl_dsr_eta": "rlp_f_dsr_eta", "rl_obs_lookback": "rlp_f_obs_lookback",
    "rl_episode": "rlp_f_episode_length", "rl_features": "rlp_sec_features", "rl_policy": "rlp_sec_policy",
    "rl_learning_rate": "rlp_f_learning_rate", "rl_gamma": "rlp_f_gamma", "rl_timesteps": "rlp_f_total_timesteps",
    "rl_n_steps": "rlp_f_n_steps", "rl_ent_coef": "rlp_f_ent_coef", "rl_clip_range": "rlp_f_clip_range", "rl_gae_lambda": "rlp_f_gae_lambda",
    "rl_buffer": "rlp_f_buffer_size", "rl_exploration": "rlp_f_exploration_fraction", "rl_seeds": "rlp_f_n_seeds",
    "rl_walkforward": "rlp_sec_validation", "rl_retrain": "rlp_f_retrain", "rl_bootstrap": "rlp_f_bootstrap_samples",
    "rl_psr": "rlp_stat_psr", "rl_turnover": "rlp_k_turnover", "rl_baselines": "rlp_leg_buy_hold",
}
LABELS_RL = {k: v for k, v in LABELS_RL.items() if v}      # PPO, A2C, DQN, SAC : le terme est son propre libellé


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
