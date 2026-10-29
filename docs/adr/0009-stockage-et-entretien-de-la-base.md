# ADR 0009 — Stockage : archivage des prédictions du scan, caches comprimés et évincés

Date : 2026-10-29 · Statut : acceptée · Code : `tracking/prediction_archive.py`, `cache_eviction.py`, `storage_cli.py` (commande `patrick storage`), `tracking/db.py` (`encode_cached_json`, `decode_cached_json`), `features/pool_cache.py`, `worker.py` (`_tidy_storage`), `tracking/journal.py` (`live_index_hint`) · Tests : `tests/test_storage.py`

## Contexte

Mesures du 29/10/2026 sur la vraie base (31,4 Go, aucun worker vivant) :

- `vol_model_cache` : 219 199 lignes de ~117 Ko de JSON (une série de ~6 600 flottants par ticker, modèle et pli), soit **~26 Go : 82 % de la base**.
  Avec `zlib` : ~58 Ko (÷2,3), sans perte.
- `prediction` : 27,8 M de lignes au 28/10 (34,6 M de lignes de scan au 29/10 après de nouveaux runs). 2 883 runs terminés, de ~13 à plusieurs centaines d'essais
  chacun. Si l'on ne garde que le meilleur essai et le top-5 de chaque run, **45 % des lignes de scan partent** (15,7 M sur 34,6 M) ; avec le seul meilleur essai, 54 %.
  Le reste est porté par les meilleurs essais eux-mêmes (CPCV : une ligne par chemin). L'échantillon des 60 runs les plus récents (profil Rapide, peu d'essais)
  ne gagne presque rien : le gain vient des anciens runs.
- `feature_cache` : 126 Go de Parquet (snappy, float64), sans plafond ni éviction. Sur trois fichiers réels de 277 Mo (7 009 lignes x 4 720 colonnes),
  `zstd` + `byte_stream_split` sans perte ne gagne que 6 % : des flottants continus ne se compressent pas, seul float32 (÷2) change l'ordre de grandeur.
- Aucune statistique SQLite (`sqlite_stat1` absent) ; 3 index sur `prediction`, dont `idx_pred_path` (path_id vaut -1 hors CPCV).
- Un seul worker, mais déjà parallèle : `scan_jobs = 4` et `parametric_jobs = 4` sur 6 coeurs.

## Décision

1. **Prédictions du scan** : `archive_run` garde en SQLite le meilleur essai (`is_best`) et les 5 essais de plus haut F1_dir moyen de chaque run ; les prédictions
   `test` / `test_path` / `valid` des autres vont dans `<archive>/predictions/<run_id>.parquet` (zstd), relues et comptées avant toute suppression, puis supprimées
   par paquets (verrou court). `holdout`, `live` et `fold_metric` ne sont jamais touchés (le PBO s'appuie sur `fold_metric`). `restore_run` remet tout en base.
   Automatique en fin de job dans le worker (runs de ce job seulement, jamais d'échec du job ; `PATRICK_KEEP_SCAN_PREDICTIONS=1` le désactive) ; l'existant par
   `patrick storage archive-predictions`.
   Aucun lecteur n'est cassé : tous (synthèse, page d'un run, équilibre des classes, simulateur, duel, analyse) ne lisent que le meilleur essai, le champion ou un
   essai de tête.
2. **Cache des modèles de volatilité** : les nouvelles entrées sont stockées en JSON compressé (zlib, octets) ; les anciennes, en clair, restent lisibles
   (`decode_cached_json` accepte les deux) et `patrick storage compress-caches` les compresse (reprenable). `patrick storage evict --db-days N` supprime les entrées
   plus vieilles que N jours (par paquets).
3. **Cache de variables** : écriture `zstd` + `byte_stream_split` (sans perte) ; la lecture marque le fichier comme utilisé ; plafond (réglage
   `feature_cache_max_gb`, 150 Go par défaut ; le dossier pesait 167 Go le 29/10) appliqué en fin de job, les moins récemment lus partent d'abord, jamais un fichier de moins d'une heure.
   **Mode float32 optionnel** (`feature_cache_float32` ou `PATRICK_FEATURE_CACHE_FLOAT32=1`, désactivé par défaut) : pools deux fois plus petits ; la valeur arrondie est
   aussi celle que reçoit l'appelant au premier calcul, donc aucun résultat ne dépend de l'état du cache, mais les résultats diffèrent de ceux du mode normal à la
   septième décimale (clé de cache propre).
4. **Index et statistiques** (`patrick storage reindex`, `analyze`) : `idx_pred_path` supprimé, `idx_pred_split` remplacé par `idx_pred_live` (partiel, lignes `live`) ;
   `ANALYZE` borné (`analysis_limit`) puis `PRAGMA optimize`. Jamais en migration automatique : créer un index sur 30 M de lignes tiendrait le verrou plusieurs minutes
   au démarrage de l'application. Les requêtes qui imposaient `idx_pred_split` demandent le nom à `live_index_hint`.
5. **Toute commande de masse de `patrick storage` refuse de tourner avec un worker vivant ou un job en cours** (suppressions en masse : incident du 27/09) ;
   arrêter aussi `patrick serve`. `patrick storage vacuum --yes` rend l'espace libéré au disque (il faut autant d'espace libre que la base).

## Ordre conseillé (worker et serveur arrêtés)

`patrick storage report`, `archive-predictions --dry-run`, `archive-predictions`, `compress-caches`, `evict --db-days 120` (facultatif), `reindex`, `analyze`, `vacuum --yes`,
`evict` (cache de variables, sans option de base).

## Non fait, et pourquoi

- **Plusieurs workers** : le protocole de file (battement de coeur unique `worker_heartbeat.id = 1`, reprise des jobs « en cours » d'un worker mort, entretien de masse
  « aucun worker vivant ») suppose un seul worker, et la machine est déjà saturée par `scan_jobs`/`parametric_jobs` (4 processus chacun sur 6 coeurs) : un second worker
  doublerait la charge sans gain démontré. À reprendre seulement après une mesure du débit sur une machine avec plus de coeurs.
- **Reprise au niveau du scan** : `patrick resume` crée de nouveaux runs ; sauter les couples (config, pli) déjà calculés demande un cache de résultats de fit par
  (données d'entraînement, réglages, graine) qui conserve les prédictions des essais de tête. Les sélections SHAP sont déjà en cache (`shap_selection_cache`) : seuls
  les ajustements sont rejoués. Conception à faire avant de coder.
- **Ablation de Kalman** (22 % du coût de construction pour 1 variable retenue sur 20) : elle demande des runs complets appariés (même snapshot, même graine, seul
  `features.vol_models` change, sans `kalman`) sur au moins une dizaine de cibles, avec comparaison des F1_dir / AUC de holdout et des durées. À lancer depuis un
  PowerShell de Léon, pas depuis l'application.

## Résultat mesuré le 29/10/2026 (exécution sur la vraie base, worker et serveur arrêtés)

- `archive-predictions` : 2 883 runs, **15 713 698 lignes** archivées en Parquet (**161 Mo** sur D:), toutes supprimées de la base (18,9 M de lignes `test` restent : le meilleur essai et le top-5 de chaque run).
- `compress-caches` : 219 199 entrées, **15,65 Go** gagnés (estimation avant : ~26 Go -> ~11 Go).
- `reindex` : `idx_pred_live` créé, `idx_pred_path` et `idx_pred_split` supprimés ; `analyze` : `sqlite_stat1` créé (55 lignes).
- `vacuum` : base **31,37 Go -> 12,95 Go** (-59 %), 0 page libre. La commande affichait « 44,42 Go » parce qu'elle lisait la taille avant la troncature du journal WAL
  (VACUUM écrit la nouvelle base dans le journal) ; corrigé (`PRAGMA wal_checkpoint(TRUNCATE)` avant la mesure).
- Contrôle après coup, en lecture seule : 219 199 entrées relues à l'identique après compression, empreinte de cache des prédictions live en 17 ms.

## Conséquences

- Gain attendu sur la base : `vol_model_cache` ~26 Go -> ~11 Go (compression), 15,7 M de lignes de prédiction en moins (~45 % des lignes de scan) ; l'espace
  n'est rendu au disque que par `vacuum`. Les gains sont mesurés après exécution dans `docs/modelisation/triage-critique-2026-10-28.md`.
- Une prédiction de scan archivée n'est plus relue par l'application (page d'un essai hors tête) : `restore_run` la remet.
- Aucun résultat de modèle ne change.
