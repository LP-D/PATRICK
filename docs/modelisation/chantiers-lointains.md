# Chantiers lointains — RL, cible alpha, futures

Statut : cadrage, rien n'est implémenté. Date : 2026-09-26. Classement de la roadmap conservé :
RL expérimental, cible alpha reportée, futures hors périmètre. Pour chacun : ce qui le rendrait défendable,
le prérequis, et le critère d'entrée.

## 1. Apprentissage par renforcement (expérimental)

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

**Ce qui manque** : pas de courbe de futures dans les sources de données — les séries `=F` de Yahoo sont des
contrats **continus** raccordés sans ajustement documenté (sauts de roll), et `LBS=F` a disparu en 2022
(remplacé par `LBR=F`, cf. vérification des tickers). Sans courbe : ni carry (roll yield), ni basis momentum,
ni open interest (familles Guida marquées absentes dans `features/guida.py`).

**Prérequis** : une source de contrats individuels (échéances, OI) et une règle de roll explicite
(back-adjusted ou ratio-adjusted), testée contre les sauts de roll. **Critère d'entrée** : la série continue
reconstruite reproduit la performance d'un roll réel à ±10 pb/an.
