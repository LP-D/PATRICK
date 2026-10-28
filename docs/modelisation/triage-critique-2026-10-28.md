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

## Placebo FX du 28/10 : le signal des devises vient d'un décalage de date (cause trouvée)

Montage isolé (base, cache et cache de variables temporaires ; seul le data lake est lu), même config et mêmes réglages que le
run EURUSD h = 1 stocké (CatBoost, 10 variables), holdout 2025-07-07 -> 2026-10-07 (script : scratchpad `placebo_fx.py`).

| Variante | Exactitude directionnelle (jours non plats / tous les jours) | AUC (tous les jours) |
|---|---|---|
| A réel (retrouve le stocké : 70,8 % ; accord ligne à ligne 85 %) | 70,8 % / 63,1 % | 0,686 |
| B variables retardées d'**un jour de plus** | 45,8 % / 49,2 % | 0,512 |
| C variables retardées de 5 jours | 45,8 % / 48,0 % | 0,497 |
| D étiquettes d'entraînement mélangées | 47,5 % / 47,4 % | 0,440 |
| E variables avancées d'un jour (contrôle de fuite positif) | 100 % / 99,1 % | 0,999 |

- Le signal disparaît dès qu'on retarde toutes les variables d'un jour : il repose entièrement sur l'information du jour même.
- Variables retenues : rendements **du jour** de l'or, de l'argent, du cuivre, du cacao et du S&P 500. Leur AUC univarié sur la
  hausse d'EURUSD du lendemain : 0,56-0,59 (train), 0,63-0,67 (holdout), 0,47-0,54 une fois retardées d'un jour.
- Cause : les barres journalières Yahoo des changes (`=X`) portent le prix du **début** de la journée, pas de sa clôture.
  Brexit (chute de la livre le ven. 24/06/2016) : -1,56 % à la date 24/06 et -7,60 % à la date lundi 27/06. Choc du franc suisse
  (jeudi 15/01/2015) : EURCHF -17,2 % à la date vendredi 16/01. USDJPY au Brexit : -2,64 % à la date 27/06. Le S&P 500 (témoin) est
  à la bonne date (-11,98 % le lundi 16/03/2020).
- Conséquence : l'étiquette de la ligne d (prix d+1 / prix d) est le mouvement réel du jour d, que les clôtures du jour d (or,
  S&P) expliquent par simple corrélation du même jour. Le modèle « prédit » un mouvement déjà fait : pas de gain négociable.
- Pourquoi la garde ne l'a pas vu : `data/alignment.py` ne retarde une série que si la corrélation de rang de sa variation du
  jour avec la variation future de la cible atteint 0,30 (cas DXY : -0,40). L'or et l'argent sont en dessous.
  `session_calendar` suppose en outre que le change clôture à 22 h UTC le même jour.
- Portée : 46 champions de change (18 à 1 jour, 20 à 2 jours) sur 1 886 ; 13 des 46 runs de change ont un DM de holdout
  significatif à 5 %. La stratégie « Systematic Devises » existe déjà (1 ordre). Les autres classes ne sont pas testées.
- Le holdout n'est donc pas en cause (jours plats retirés) : c'est l'alignement des dates des séries de change.

## À décider (changent les résultats, rendent les 2 249 runs existants non comparables)

1.1 DM directionnel, 1.2 jours plats (seuil en multiple de la volatilité), 1.3 régimes de volatilité, 1.4 SHAP sur les
dernières lignes. Chacun demande un marqueur de version de méthode (ou une migration) et une régénération du golden CI.
