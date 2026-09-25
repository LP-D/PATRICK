# Audit de vitesse — familles de features (2026-09-25)

**Question posée (roadmap, bloc 2)** : les composants coûteux du pipeline
servent-ils à quelque chose ?

**Outil** : `patrick audit speed --db <base> --target <ticker> --output <md>`
(`patrick/audit_speed.py`). Il croise trois sources :

1. **Usage** — les features des modèles exportés (`drift_reference`, une ligne
   par feature retenue par le modèle final de chaque horizon) et la somme des
   fréquences de sélection (`feature_stability`) ;
2. **Pool** — les colonnes réellement construites par le run (pool complet
   base + paramétrique), classées par famille sur leurs vrais noms ;
3. **Coût** — temps mur de construction de chaque famille sur les données du
   run, une coupe de fold ; les familles paramétriques (refittées à chaque
   fold walk-forward) sont multipliées par le nombre de folds (5).

**Données** : run réel `^GSPC`, horizons 1 j et 5 j, univers complet (42 séries
après portes de qualité), config par défaut (`webapp/forms.default_config_dict`),
base `patrick_new.db` du 2026-09-25.

## Résultat

Coûts recalculés sur les seules familles activées dans ce run (la première
version de l'outil comptait ARIMA, mesurée « si activée », dans les parts de
coût — corrigé, test `test_a_family_absent_from_the_pool_is_reported_as_not_enabled`).

| Famille | Paramétrique | Colonnes du pool | Retenues (modèles exportés) | Σ fréq. sélection | Coût / run | Part du coût |
|---|---|---:|---:|---:|---:|---:|
| hmm | oui | 42 | 0 | 0.00 | 684,5 s | 64 % |
| kalman | oui | 42 | 1 | 0.20 | 230,5 s | 22 % |
| particle_filter | oui | 42 | 0 | 1.00 | 95,0 s | 9 % |
| spike_rolling | non | 126 | 0 | 2.20 | 36,6 s | 3 % |
| egarch | oui | 42 | 1 | 1.80 | 13,8 s | 1 % |
| technical | non | 546 | 9 | 9.80 | 0,7 s | 0 % |
| vrp_proxy | non | 42 | 0 | 0.00 | 0,1 s | 0 % |
| heston_proxy | non | 84 | 0 | 0.00 | 0,1 s | 0 % |
| ohlc_vol | non | 8 | 2 | 1.60 | — | — |
| raw_level | non | 42 | 3 | 0.40 | — | — |
| interactions | non | 0¹ | 4 | 3.00 | — | — |
| macro | non | 112 | 0 | 0.00 | — | — |
| arima_family | oui | 0 | 0 | 0.00 | non activée (216,9 s si activée) | — |

¹ Les interactions sont construites après la pré-sélection, hors du pool audité.

## Lecture

- **HMM : 64 % du temps de construction des features, 0 feature retenue, 0
  sélection sur les folds.** C'est le poste le plus coûteux et, sur ce run,
  le plus inutile.
- **Kalman : 22 % du coût pour 1 feature retenue** (sur 20).
- **Filtre particulaire : 9 %, 0 retenue** (sélectionné une fois sur les folds).
- Les features techniques (0,7 s) portent 9 des 20 features retenues.
- Au total, **~95 % du temps de construction** va à trois familles
  paramétriques qui fournissent **1 feature retenue sur 20**.

## Limites (à lire avant de décider)

- **Un seul actif, deux horizons, 20 features exportées.** Un comptage de 0
  sur 20 n'établit pas qu'une famille est inutile en général : sur une cible
  de volatilité (VIX) ou de régime, HMM peut être déterminant. La décision
  doit s'appuyer sur plusieurs cibles (au moins les 5 cibles de référence).
- « Retenue » = présente dans le modèle final exporté ; une famille peut
  améliorer la sélection sans y figurer (effet de substitution entre features
  corrélées). Le test causal est l'**ablation** : relancer sans la famille et
  comparer le F1_dir holdout (walk-forward) — non fait ici.
- Le coût est mesuré sur la machine de session (CPU partagé), une coupe de
  fold : l'ordre de grandeur est fiable, pas la décimale.

## Décision proposée (non appliquée — à trancher)

1. Lancer l'audit sur les 5 cibles de référence (`patrick audit speed` par
   cible) ; si HMM reste à 0 retenue sur toutes, le retirer de
   `DEFAULT_VOL_MODELS` (il reste activable par config).
2. Ablation HMM sur ^GSPC et ^VIX (F1_dir holdout avec/sans).
3. Le cache de pools (`features/pool_cache.py`, clé = contenu du vintage +
   config + coupe de fit + hash du code des features) supprime déjà le
   recalcul sur un relancement à l'identique ; il ne réduit pas le coût du
   premier run ni le refit par fold.
