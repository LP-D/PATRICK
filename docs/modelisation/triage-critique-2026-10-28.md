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

## Statut en fin de séance du 28/10 (point par point)

Légende : **fait** = codé, testé, commité ; **périmé** = déjà traité ou faux dans le code actuel ; **non fait** = reste à faire (voir « Suite »).

| Point de la liste | Statut |
|---|---|
| 1.1 DM sur la direction | **fait** (méthode 2, `dm_result.loss`, ADR 0008) |
| 1.2 jours plats retirés de l'évaluation | **fait** (méthode 2 : seuil en volatilité, jours plats gardés dans l'évaluation) |
| 1.3 régimes par niveau de prix | **fait** (méthode 2 : terciles de volatilité, sauf indices de volatilité) |
| 1.4 SHAP sur les plus anciennes lignes | **fait** (méthode 2 : les plus récentes) |
| 1.5 stratégies de fonds sans preuve | **fait en partie** : défaut `strict`, un essai compté par modèle retenu à la mise en place (ADR 0010) ; Sharpe déflaté par stratégie **fait** (30/10, ADR 0011) ; **non fait** : choix de la meilleure classe |
| 1.6 PBO sous 3 plis | **périmé** (refusé sous 6 blocs depuis C5) |
| 1.7 variables de niveau brut, `fracdiff` | **fait, non activé** (30/10) : méthode 3, niveaux différenciés fractionnairement sous les mêmes noms, ADR 0011 ; panel de six cibles mesuré : AUC moyen -0,016, aucun gain distinguable du bruit, `CURRENT_METHOD_VERSION` reste 2 |
| 1.8 `holdout_access` vide | **périmé** (1 077 lignes) ; simulateur non compté : **périmé** (le DSR utilise `count_registered_trials`) ; **98 runs sans essai gagnant : élucidé** (113 aujourd'hui : 80 d'août = ancien export par horizon, 33 d'octobre = séries FRED mensuelles à 1 jour, zéro évaluation, désormais en échec avec la raison) ; mutants survivants, monde à pertes égales : non fait |
| 1.8 décalage de séance des actions européennes | **fait** : audité (corrélation 0,08 -> 0,04), règle FRED (ADR 0007) |
| (hors liste) barres de change du début de journée | **fait** (ADR 0007), cause du signal des devises |
| 2.1 verrou d'écriture à chaque connexion | **fait** |
| 2.2 verdict BH sur chaque page | **fait** |
| 2.3 synthèse : runs lus deux fois | **fait** ; `home_summary` en différé : **mesuré le 30/10, sans gain** (22 à 131 ms de rendu), non fait |
| 2.4 mémoïsation inopérante pendant un run | **fait** |
| 2.5 SQLite | `synchronous`, cache, mmap **fait** ; `ANALYZE` : **fait** le 29/10 (`sqlite_stat1`, 55 lignes) |
| 2.6 JSON de 100 Ko par page, `chart_kit.js` bloquant | **mesuré le 30/10, sans gain sur machine locale** (100 Ko de JSON, 22 à 131 ms de rendu) ; `glossary.js` / `names.js` lisent ces blocs de façon synchrone : non fait, justifié (ADR 0011) |
| 2.7 polling | onglet caché **fait** ; flux SSE : non fait, le sondage ne tourne que sur la page de suivi d'un run, onglet visible (ADR 0011) |
| 3.1 toutes les prédictions du scan écrites | **fait et exécuté le 29/10** : 15,7 M de lignes archivées (161 Mo de Parquet), base 31,4 Go -> 12,95 Go après compression et VACUUM (ADR 0009) : archivage Parquet automatique en fin de job + `patrick storage archive-predictions` ; index : `reindex`. Mesure : 45 % des lignes de scan partent avec le top-5, pas 92 % (le meilleur essai en garde beaucoup, surtout en CPCV) |
| 3.2 éviction de cache, float32 + zstd | **fait** : plafond LRU du cache de variables (150 Go), `vol_model_cache` comprimé (zlib, ÷2,3) et évinçable par âge ; float32 en option (zstd seul ne gagne que 6 % sur des flottants continus). Vraie cible de taille : `vol_model_cache` = 26 Go sur 31, pas les prédictions |
| 3.3 plusieurs workers | **non fait, justifié** : la machine (6 coeurs) est déjà saturée par `scan_jobs`/`parametric_jobs` (4 chacun) et le protocole de file suppose un seul worker (ADR 0009) |
| 3.4 reprise au niveau du scan | non fait (conception à faire : cache de résultats de fit qui conserve les prédictions des essais de tête, ADR 0009) ; les sélections SHAP sont déjà en cache |
| 3.5 ablation de Kalman | non fait : demande des runs complets appariés, protocole écrit dans l'ADR 0009 |
| 4 (SHAP global, DM sur score continu, journal synchronisé...) | DM sur le Brier **fait** (`dm_brier_result`) ; le reste non fait |
| 5.1 cible volatilité | non fait, conception écrite (ADR 0011) : l'étiquette de cible est lue par plus de vingt consommateurs qui doivent chacun décider quoi en faire |
| 5.2 placebo automatique par run | **fait** (`run_placebo`, verdict `same_day`), affiché sur la page d'un run |
| 5.3 population d'évaluation explicite | **fait** pour la méthode 2 (le jeu est celui du live) ; affichage côte à côte non fait |
| 5.4 badge de profil / méthode | **fait** : méthode, alignement et profil (déduit des réglages, 17 profils reconnus), page d'un run ; comparaisons limitées à un même profil : non fait |
| 5.5 calibration par défaut pour les runs du fonds | **fait** (30/10) : case cochée par défaut dans les formulaires ML et DL (`DEFAULT_FORM_CALIBRATION`) ; le schéma garde False (golden master, configs enregistrées) |
| 5.6 budget d'essais avant lancement | **fait** : API, commande (`patrick budget`) et bloc du formulaire de lancement (30/10) |
| 6 ergonomie (38 entrées de navigation, accueil, tableaux) | **fait en grande partie** : tableaux (tri, filtre, CSV), bloc « À faire » de l'accueil, onglets de run, qualité des données sous Données, navigation en arborescence (16 entrées visibles repliée + 3 utilitaires, 31 feuilles), comparateur à deux vues reliées (onglet « Comparer » d'un run corrigé : il menait à une erreur 400), états vides actionnables, guide de premier lancement ; non fait : page de run réellement fusionnée |
| 7 design v3 | **en partie** (30/10) : 30 `style="…"` en ligne ramenés au CSS (2 largeurs calculées restent), N_eff et plis à côté des métriques de tête, `chart_kit.js` accepte `vlines` (annotations) et `sync` (réticule partagé) ; diagramme de fiabilité de P(hausse) au survol des prédictions, champions repérés sur le graphique de dérive ; non fait : `sync` dans une page, petits multiples |

## Suite

Les points « non fait » de vitesse (2.3 en différé, 2.6, SSE) sont des chantiers indépendants, sans lien avec les
résultats ; ceux d'interface (6, 7, affichage du placebo, badge) aussi. Les points 1.5 (comptage des stratégies), 1.7 et 5.1 à 5.6 touchent la méthode et
demandent une décision de conception avant d'être codés.
