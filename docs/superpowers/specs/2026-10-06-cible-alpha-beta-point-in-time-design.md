# Cible alpha vs benchmark — β point-in-time (jalon 1)

Cadrage : `docs/modelisation/chantiers-lointains.md` §2 (« Cible alpha vs benchmark, reportée »). Ce document fixe le
premier jalon, la brique statistique pure; le branchement au pipeline est le jalon 2.

## 1. Pourquoi

Sur les actions, la direction brute est dominée par la direction du marché (taux de hausse de base à 252 j : 0,81 sur
le S&P 500). Les modèles apprennent surtout le bêta. La décision réelle est « surpondérer ou sous-pondérer une ligne
face à son indice » : la cible pertinente est le rendement **excédentaire**, dont le taux de base est proche de 0,5.

## 2. Définitions

Pour un actif *a*, un benchmark *b*, un horizon *h* (jours de séance) et une date *t* :

- `β_t` = cov(r_a, r_b) / var(r_b) sur les `window` rendements quotidiens se terminant à *t* inclus
  (`window = 252`, `min_obs = 60`; NaN avant). Aucune donnée postérieure à *t*.
- rendement excédentaire sur l'horizon : `α_t = (P^a_{t+h}/P^a_t − 1) − β_t · (P^b_{t+h}/P^b_t − 1)`.
  Le β est celui connu en *t*, figé sur toute la fenêtre de label.
- cible : mêmes quatre classes que `features/target.py` (DOWN_FORT / DOWN_FAIBLE / UP_FAIBLE / UP_FORT), appliquées à
  `α_t`, avec seuils ajustés sur le train du fold seulement et purge des *h* derniers points (`build_target`).
- Les deux séries sont d'abord alignées sur leurs dates communes (calendriers de places différents).

## 3. Baselines

- **alpha nul** : taux de hausse de base 0,5 (la cible n'a pas de dérive de marché);
- **persistance de l'alpha** : signe de l'alpha réalisé sur les *h* jours précédant *t* (`α` passé avec le même `β_t`).
  Critère d'entrée du jalon 2 : DM-HLN du modèle contre cette persistance sur le holdout, famille BH séparée des
  cibles brutes (F04, F05).

## 4. Livré dans ce jalon

- `features/alpha_target.py` : `point_in_time_beta`, `alpha_forward_return`, `alpha_persistence_signal`,
  `build_alpha_target`.
- `features/target.py::build_target` accepte un `ret` précalculé (paramètre optionnel, comportement inchangé par défaut).
- Tests : β retrouvé sur données synthétiques, test de fuite par corruption du futur (β et seuils), alignement des
  calendriers, taux de base de l'alpha contre celui de la cible brute.

## 5. Hors périmètre (jalon 2)

- Option de configuration `objective` (cible brute | alpha) et nom du benchmark par actif dans `RunConfig`.
- Famille de tests et registre d'essais séparés pour les cibles alpha.
- Mapping par défaut actif → benchmark. `wealth.ledger.DEFAULT_BENCHMARK` est **par type de compte** (PEA, CTO...), pas
  par actif : il ne sert pas ici. À décider : mapping explicite saisi, ou règle par classe d'actif.
- Affichage dans l'application.

## 6. Points ouverts

- β brut ou ajusté (Blume : 0,67 β + 0,33) : brut ici, l'option est triviale à ajouter si le holdout le justifie.
- Fenêtre de 252 j : paramètre, non optimisé (toute valeur testée compterait dans le registre d'essais).
