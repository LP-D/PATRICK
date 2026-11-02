# Chantiers lointains — RL, cible alpha, futures

Statut : cadrage du 2026-09-26. Mise à jour du 2026-10-18 : le RL (§1, page `/rl`) et la cible alpha (§2, `features/alpha_target.py`) sont
implémentés depuis ; seule l'extension futures (§3) reste hors périmètre, faute de courbe de contrats. Classement de la roadmap conservé :
RL expérimental, cible alpha reportée, futures hors périmètre. Pour chacun : ce qui le rendrait défendable,
le prérequis, et le critère d'entrée.

## 1. Apprentissage par renforcement (expérimental)

> **Mesuré le 2026-11-02 (ADR 0015)** : le bandit LinUCB et le Kelly fractionnaire appris ne battent pas les heuristiques de `/simulate` après coûts sur 459 champions à 1 jour (critère d'entrée non atteint). Rapport : `docs/modelisation/mesures-bandit-carry-2026-11-02.md` (reproductible : `scripts/bandit_sizing_bench.py`).

**Ce que ce serait** : un agent qui choisit une allocation (ou une taille de position) à partir de l'état
(features, positions, coûts) pour maximiser une récompense (rendement ajusté du risque net de coûts).

**Pourquoi c'est rarement gagnant ici** :
- l'environnement est un **backtest rejoué** : l'agent n'influence pas les prix, le problème est donc un
  bandit contextuel déguisé ; un RL complet ajoute de la variance sans information ;
- la sélection sur backtest est pire qu'en supervisé : chaque épisode réutilise le même historique, le
  nombre effectif d'essais (DSR, F03) explose ;
- l'échantillon effectif est celui du supervisé (n / h), sans les labels.

**Version défendable** : bandit contextuel ou « policy » de dimensionnement (Kelly fractionnaire appris)
au-dessus des P(hausse) calibrées déjà stockées (`prediction.p_up`), évaluée en walk-forward sur le holdout
avec coûts. **Critère d'entrée** : battre le dimensionnement heuristique de `/simulate` (Kelly/seuil) après
coûts sur le holdout, avec chaque configuration comptée dans `trial_registry`.

## 2. Cible alpha vs benchmark (reportée)

**Ce que ce serait** : prédire la direction du rendement **excédentaire** (actif − β · benchmark, ou actif −
benchmark) au lieu du rendement brut.

**Pourquoi c'est pertinent** : sur les actions, la direction brute est dominée par la direction du marché —
le taux de hausse de base à 252 j est 0,81 sur le S&P 500 (`horizons-longs.md`), et les modèles apprennent
surtout le bêta. Une cible alpha a un taux de base proche de 0,5 et correspond à la décision réelle
(surpondérer/sous-pondérer une ligne du patrimoine face à son indice).

**Prérequis** : β point-in-time (estimé sur fenêtre passée uniquement, sinon fuite), benchmark par actif
(déjà présent pour le patrimoine : `wealth.ledger.DEFAULT_BENCHMARK`), baseline « alpha nul ». **Critère
d'entrée** : DM-HLN sur le holdout contre la persistance de l'alpha, et famille BH séparée des cibles brutes.

## 3. Extension futures (hors périmètre)

> **Précision du 2026-11-02 (ADR 0015)** : le carry de CHANGE ne demande pas de courbe de futures (écart de taux courts, FRED) ; il a été mesuré (`features/fx_carry.py`) : Sharpe 0,17-0,18 sur sept devises, non significatif. Le carry de matières premières reste bloqué par l'absence de courbe d'échéances, comme ci-dessous.

**Ce qui manque** : pas de courbe de futures dans les sources de données — les séries `=F` de Yahoo sont des
contrats **continus** raccordés sans ajustement documenté (sauts de roll), et `LBS=F` a disparu en 2022
(remplacé par `LBR=F`, cf. vérification des tickers). Sans courbe : ni carry (roll yield), ni basis momentum,
ni open interest (familles Guida marquées absentes dans `features/guida.py`).

**Prérequis** : une source de contrats individuels (échéances, OI) et une règle de roll explicite
(back-adjusted ou ratio-adjusted), testée contre les sauts de roll. **Critère d'entrée** : la série continue
reconstruite reproduit la performance d'un roll réel à ±10 pb/an.
