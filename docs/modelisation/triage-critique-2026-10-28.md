# Triage de la critique du 28/10/2026

Liste collée le 28/10 (méthode, vitesse, entraînement, ergonomie, design), vérifiée contre le code et la base locale
(28 Go, lecture seule). Même méthode que `triage-feuille-de-route-2026-10-18.md`.

## Livré le 28/10 (vitesse, aucun résultat modifié)

| Point | Correctif |
|---|---|
| 2.1 verrou d'écriture à chaque connexion | `db.connect()` lit `schema_version` sans verrou (`_schema_is_current`) ; `migrate()` (BEGIN IMMEDIATE) n'est appelé que s'il manque une migration |
| 2.2 verdict BH sur chaque page | `_i18n_context(with_verdict=True)` seulement pour la synthèse (seul gabarit qui lit `verdict`) |
| 2.3 synthèse : `list_all_runs` deux fois | `home_summary` passe ses runs à `all_classes_summary` / `model_stats_by_asset` |
| 2.4 mémoïsation inopérante pendant un run | l'empreinte (`tracking/memo.py`) suit les prédictions **live** (nombre, dernière date) au lieu de `MAX(rowid)` sur toute la table ; 35 ms à froid sur 27,8 M de lignes |
| 2.5 SQLite | `synchronous=NORMAL`, `cache_size` 64 Mo, `mmap_size` 256 Mo dans `connect()` |
| 2.7 polling | l'onglet caché n'interroge plus `/runs/<id>/status` (reprise immédiate au retour) |

Pas fait dans ce lot : `PRAGMA optimize` / `ANALYZE` (la base n'a pas de `sqlite_stat1` ; à lancer sans worker vivant,
voir la note « pas de maintenance pendant un run »), JSON statiques versionnés + `defer` (2.6), flux SSE (2.7, le polling
ne tourne que sur la page de suivi d'un run).

## Vérifié, périmé

- **1.6 PBO** : déjà traité (C5). `pbo_reliability` refuse sous `MIN_BLOCKS = 6` (« PBO non calculé »), `run_detail.html`
  et `target.html` n'affichent le point que si la fiabilité l'accepte. 1 820 des 2 249 runs terminés ont 3 plis (81 %).
- **8 `holdout_access` vide** : 1 077 lignes aujourd'hui.
- **1.5 `trial_registry`** : 78 253 lignes ; reste vrai que les stratégies de fonds n'y sont pas comptées.

## Vérifié, confirmé dans le code

1.1 (DM sur 4 classes, `engine.py:1057`), 1.2 (`target.py:46`, seuil absolu 0,3 %), 1.3 (régimes par niveau,
`target.py:42-43`), 1.4 (SHAP sur les 500 plus anciennes lignes, `shap_select.py:21`), 1.5 (`tier: "large"` par défaut),
3.1 (92 % des 27,8 M de prédictions sont celles du scan : 25,5 M `test`, 0,5 M `holdout`, 13 k `live`).

## Mesure sur les holdouts stockés (devises, baseline `random_walk_no_drift`, 45 runs)

- Recalcul exact des p-values stockées (écart 0,0).
- DM 4 classes : 27 % des runs à p < 0,05. DM **direction** : 47 %. Le passage à la perte directionnelle **ne réduit pas**
  les rejets : l'hypothèse « le modèle ne prévoit que l'amplitude » n'est pas soutenue.
- Exactitude directionnelle holdout : 68,8 % à h = 1 (23 runs, ~127 lignes), 59,7 % à h = 2 ; live sur les mêmes cibles :
  57,6 % (n = 125) et 52,7 % (n = 55). Écart holdout / live de 11 points à h = 1, avec 40 % des jours seulement dans le
  holdout (jours plats retirés). Un tel score en holdout est suspect, non démontré faux : l'effet de sélection des jours
  plats ne suffit pas à l'expliquer sur le papier, un décalage de séance FX / autres marchés reste à contrôler.
- À faire pour trancher : le placebo (variables décalées d'un jour de plus, point 5.2) sur une cible FX, et la
  population d'évaluation explicite (tous les jours / jours non plats, point 5.3).

## À décider (changent les résultats, rendent les 2 249 runs existants non comparables)

1.1 DM directionnel, 1.2 jours plats (seuil en multiple de la volatilité), 1.3 régimes de volatilité, 1.4 SHAP sur les
dernières lignes. Chacun demande un marqueur de version de méthode (ou une migration) et une régénération du golden CI.
