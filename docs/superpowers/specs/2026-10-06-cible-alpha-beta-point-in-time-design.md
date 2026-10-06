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

## 5. Jalon 2a : benchmark automatique ou choisi (livré)

`features/benchmark.py` : `auto_benchmark(symbole)` et `resolve_benchmark(symbole, override)`. Le choix manuel l'emporte
toujours; sans choix, le benchmark vient de la classe d'actif et de la région (classification du pipeline,
`data.session_calendar.classify_asset_class`) : action US → `^GSPC`, zone euro → `^STOXX50E`, Royaume-Uni → `^FTSE`,
Japon → `^N225`, Hong Kong → `^HSI`, crypto → `BTC-USD`, matière première → `DBC`, indice → l'indice régional puis le
monde (`URTH`), reste → monde. Jamais la cible elle-même (repli sur le monde). Aucun benchmark n'a de sens pour un change,
un indice de volatilité, une série macro ou bitcoin lui-même : l'erreur le dit et propose le choix manuel. Le résultat
porte sa raison et sa provenance (`auto` | `manual`), à enregistrer avec le run (reproductibilité si la table évolue).

## 5 bis. Jalon 2b : branchement au pipeline (à faire)

Décision de conception à ne pas prendre à la légère : `run.target` est lu à ~127 endroits (historique, prédictions,
simulation, rejeu patrimoine, champions). Un run alpha ne doit **jamais** se mélanger silencieusement aux runs bruts :

- un champion « implicite » (dernier run terminé) serait un modèle d'alpha à la place d'un modèle de direction;
- un modèle d'alpha prédit une surperformance, pas la direction du prix : le rejouer comme signal de prix serait faux.

Approche retenue : colonnes `run.target_kind` (`raw` par défaut) et `run.benchmark` (migration), `run.target` inchangé;
toutes les lectures « signal de direction » (champions, rejeu patrimoine, règles du fonds, simulation) filtrent
`target_kind = 'raw'`; le registre d'essais et les familles DM/BH utilisent la clé `symbole|alpha:benchmark`.
Ensuite : champs `objective.target_kind` et `objective.benchmark` (vide = automatique, valeur enregistrée dans le run),
ajout du benchmark à l'univers d'ingestion, constructeur de cible unique remplaçant les appels `build_target` du moteur,
de l'export et du suivi live, sélecteur dans la page « Lancer ».

## 6. Points ouverts

- β brut ou ajusté (Blume : 0,67 β + 0,33) : brut ici, l'option est triviale à ajouter si le holdout le justifie.
- Fenêtre de 252 j : paramètre, non optimisé (toute valeur testée compterait dans le registre d'essais).
